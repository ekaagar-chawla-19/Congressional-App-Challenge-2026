"""In-app AI assistant (Claude Haiku) and AI photo inspection of twig close-ups.

* Assistant: answers questions about the signed-in user's forests ("where is it worst?",
  "what's most common?", "what should we do?") by calling read-only tools over that
  user's data; it never sees other accounts. Conversations are kept server-side and
  append-only (thinking blocks are replayed unchanged, as the API requires).
* Photo inspection: looks at twig/needle-underside close-ups for HWA wool and scale
  covers and returns signs with confidence. It is an assistant to the observer, not
  a validated detector: results are stored as "ai_suggested" signs for the user to
  confirm.

Needs ANTHROPIC_API_KEY (an API key from console.anthropic.com; billed per use).
"""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from collections.abc import Callable

try:
    import anthropic
    API_ERRORS: tuple = (anthropic.APIError,)
except ImportError:  # optional extra: pip install -e ".[assistant]"
    anthropic = None
    API_ERRORS = ()

MODEL = "claude-haiku-5-5"
MAX_TOOL_ROUNDS = 8
CONVERSATION_TTL_S = 2 * 3600

SYSTEM = """You are the Hemlock Sentinel assistant, built into an app that monitors individual Eastern hemlocks \
(Tsuga canadensis) in North Georgia forests.

The app identifies individual trees from trunk-bark photos, stores every visit (photos, ESP32 sensor-node \
readings: soil moisture %, air temperature °C, relative humidity %, light lux; observer-checked signs; a 0-3 \
severity rating) and assesses three threats: hemlock woolly adelgid (HWA), elongate hemlock scale (EHS), and \
drought stress with secondary decline (root rot, borers).

Use the tools to look up the user's data before answering; never invent trees, numbers or locations. Rules:
- Insects are confirmed only by seeing them on twig/needle undersides. Trunk photos cannot show HWA or EHS; \
"unknown" means not checked, not healthy.
- Sensor readings indicate stress or risk, never a diagnosis. Thresholds are heuristic.
- Never give pesticide doses or tell users to apply restricted products themselves: point to the product label, \
a licensed applicator, the Georgia Forestry Commission, UGA Extension or Save Georgia's Hemlocks.
- Say how confident a finding is and what would confirm it.
- Be concise and practical: lead with the answer, then the 2-4 most useful next steps. Use tree IDs \
(e.g. H-012) and zone ranks so the user can find them on the map.
- You can explain how to use the app: guided capture (3 trunk photos, then optional twig close-up), the map \
and zones, tree history, the review queue for uncertain matches, and reading the ESP32 sensor node."""

TOOLS = [
    {"name": "get_account_overview",
     "description": "All forests on the user's account with tree counts, severity breakdown and the most prominent "
                    "condition in each. Call first when the question is not about a specific forest.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_forest_analysis",
     "description": "Full analysis of one forest: severity, condition prevalence (likely/possible/assessed counts), "
                    "sensor averages, data coverage, and recommendations for the conditions present.",
     "input_schema": {"type": "object", "properties": {"forest_id": {"type": "integer"}},
                      "required": ["forest_id"], "additionalProperties": False}},
    {"name": "get_forest_zones",
     "description": "The forest divided into square grid zones, ranked worst first by stress score (severity plus "
                    "condition likelihood). Use for 'where are the trees suffering most'.",
     "input_schema": {"type": "object", "properties": {
         "forest_id": {"type": "integer"},
         "cell_m": {"type": "number", "description": "zone size in metres, default 150"}},
         "required": ["forest_id"], "additionalProperties": False}},
    {"name": "list_trees",
     "description": "Trees of a forest with location, latest severity, main condition and latest sensor reading; "
                    "optionally filtered.",
     "input_schema": {"type": "object", "properties": {
         "forest_id": {"type": "integer"},
         "condition": {"type": "string", "enum": ["hwa", "ehs", "drought_stress"]},
         "min_severity": {"type": "integer", "minimum": 0, "maximum": 3},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
         "required": ["forest_id"], "additionalProperties": False}},
    {"name": "get_tree",
     "description": "One tree's full visit history: per visit the photos (yes/no), sensor readings (or null = not "
                    "recorded), observed signs, severity, and condition findings with evidence.",
     "input_schema": {"type": "object", "properties": {"forest_id": {"type": "integer"},
                                                       "tree_id": {"type": "string"}},
                      "required": ["forest_id", "tree_id"], "additionalProperties": False}},
    {"name": "get_health_guide",
     "description": "Reference: the three conditions (signs, how to confirm, recommendations), the sign checklist, "
                    "the 0-3 severity scale and the sensor thresholds the app uses.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
]

INSPECT_SCHEMA = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean", "description": "photos show twig/needle undersides sharply enough to judge"},
        "signs": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string", "enum": ["hwa_wool", "ehs_scale", "needle_yellow_banding",
                                               "gray_green_foliage", "needle_loss", "branch_dieback"]},
            "confidence": {"type": "number"},
            "where": {"type": "string"}},
            "required": ["key", "confidence", "where"], "additionalProperties": False}},
        "look_alikes": {"type": "string", "description": "anything that could be mistaken for a sign, or empty"},
        "summary": {"type": "string"},
    },
    "required": ["usable", "signs", "look_alikes", "summary"],
    "additionalProperties": False,
}

INSPECT_PROMPT = """These are close-up photos of Eastern hemlock twigs or needles from a field survey.
Report only what is visible:
- hwa_wool: white, cottony, round masses about 1-3 mm at the BASE of needles on twig undersides
- ehs_scale: flat, elongate brown covers (~1.5 mm) or white waxy specks ON needle undersides
- needle_yellow_banding: yellow bands/flecks on the top of needles
- gray_green_foliage, needle_loss, branch_dieback: only if clearly visible
Do not report spider silk, spittle (wet foam), resin, bird droppings or lint as signs; mention them in \
look_alikes. Confidence 0-1. If the photos are blurry, too far, or show bark rather than twigs, set usable to \
false and report no signs."""


class NotConfigured(Exception):
    pass


class Assistant:
    def __init__(self, client=None):
        self._client = client
        self._convs: dict[str, dict] = {}
        self._lock = threading.Lock()

    @property
    def client(self):
        if self._client is None:
            if anthropic is None:
                raise NotConfigured("install the assistant extra: pip install -e '.[assistant]'")
            try:
                self._client = anthropic.Anthropic()
            except anthropic.AnthropicError as e:
                raise NotConfigured("set ANTHROPIC_API_KEY (from console.anthropic.com) to enable the assistant") from e
        return self._client

    def _create(self, **kw):
        client = self.client
        try:
            return client.messages.create(**kw)
        except anthropic.AuthenticationError as e:
            raise NotConfigured("ANTHROPIC_API_KEY was rejected; check the key at console.anthropic.com") from e
        except TypeError as e:  # SDK raises this at request time when no credentials are found
            if "authentication" in str(e).lower():
                raise NotConfigured("set ANTHROPIC_API_KEY (from console.anthropic.com) to enable the assistant") from e
            raise

    # ------------------------------------------------------------- chat
    def chat(self, owner: str, message: str, tools: dict[str, Callable[[dict], object]],
             conversation_id: str | None = None, context: str | None = None) -> dict:
        """One user turn. ``tools`` maps tool name -> implementation (already scoped to the user)."""
        with self._lock:
            self._gc()
            conv = self._convs.get(conversation_id or "")
            if conv is None or conv["owner"] != owner:
                conversation_id = uuid.uuid4().hex
                conv = {"owner": owner, "messages": [], "t": time.time()}
                self._convs[conversation_id] = conv
            conv["t"] = time.time()
        text = message if not context else f"{message}\n\n[App context: {context}]"
        msgs = conv["messages"]
        msgs.append({"role": "user", "content": text})
        used = []
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                resp = self._create(model=MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=msgs,
                                    thinking={"type": "adaptive"}, output_config={"effort": "medium"})
            except (NotConfigured, *API_ERRORS):
                if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], str):
                    msgs.pop()  # nothing was answered; keep the history consistent
                raise
            msgs.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "refusal":
                return self._reply(conversation_id, "I can't help with that request.", used, resp.stop_reason)
            if resp.stop_reason != "tool_use":
                reply = "".join(b.text for b in resp.content if b.type == "text").strip()
                return self._reply(conversation_id, reply, used, resp.stop_reason)
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                used.append({"tool": b.name, "input": b.input})
                fn = tools.get(b.name)
                try:
                    if fn is None:
                        raise KeyError(f"unknown tool {b.name}")
                    out = json.dumps(fn(b.input), default=str)[:60_000]
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
                except Exception as e:  # noqa: BLE001 - reported back to the model, which can recover
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"error: {e}",
                                    "is_error": True})
            msgs.append({"role": "user", "content": results})
        return self._reply(conversation_id, "That needed too many lookups; please ask a narrower question.",
                           used, "max_tool_rounds")

    @staticmethod
    def _reply(cid, text, used, stop) -> dict:
        return {"conversation_id": cid, "reply": text, "tools_used": used, "stop_reason": stop, "model": MODEL}

    def _gc(self) -> None:
        now = time.time()
        for k in [k for k, v in self._convs.items() if now - v["t"] > CONVERSATION_TTL_S]:
            del self._convs[k]

    # --------------------------------------------------- photo inspection
    def inspect_photos(self, images: list[bytes]) -> dict:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.standard_b64encode(b).decode()}} for b in images[:4]]
        content.append({"type": "text", "text": INSPECT_PROMPT})
        resp = self._create(
            model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": content}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": INSPECT_SCHEMA}})
        if resp.stop_reason == "refusal":
            raise NotConfigured("the photo check was declined")
        data = json.loads(next(b.text for b in resp.content if b.type == "text"))
        data["model"] = MODEL
        return data
