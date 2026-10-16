/**
 * Hemlock Sentinel API client for React Native / Expo (also works in browsers and Node 18+).
 *
 *   const api = new HemlockClient({ baseUrl: "http://192.168.1.20:8000" });
 *   const r = await api.identify([{ uri: photo1.uri }, { uri: photo2.uri }, { uri: photo3.uri }]);
 *   if (r.action === "review") showCandidates(r.candidates);
 *
 * Types in ./schema.d.ts are generated from the server's OpenAPI spec (npm run gen).
 */
import type { components } from "./schema";

type Schemas = components["schemas"];
export type Health = Schemas["Health"];
export type ModelInfo = Schemas["ModelInfo"];
export type Protocol = Schemas["Protocol"];
export type ViewSpec = Schemas["ViewSpecOut"];
export type ViewQuality = Schemas["ViewQuality"];
export type CaptureCreated = Schemas["CaptureCreated"];
export type CaptureState = Schemas["CaptureState"];
export type ViewAdded = Schemas["ViewAdded"];
export type IdentifyResult = Schemas["IdentifyResult"];
export type Candidate = Schemas["Candidate"];
export type Species = Schemas["Species"];
export type Location = Schemas["Location"];
export type Observation = Schemas["Observation"];
export type ObservationPage = Schemas["ObservationPage"];
export type TreeSummary = Schemas["TreeSummary"];
export type TreeDetail = Schemas["TreeDetail"];
export type TreePage = Schemas["TreePage"];
export type AssignResult = Schemas["AssignResult"];
export type LoginResult = Schemas["LoginResult"];
export type User = Schemas["UserOut"];
export type AccountOverview = Schemas["AccountOverview"];
export type ForestSummary = Schemas["ForestSummary"];
export type ForestMap = Schemas["ForestMap"];
/** 0 none, 1 light, 2 moderate, 3 severe — the observer's rating, not a model output. */
export type Severity = 0 | 1 | 2 | 3;
export type IdentifyStatus = IdentifyResult["status"];
export type NextAction = IdentifyResult["action"];

/** A photo: React Native file reference ({ uri } from expo-camera / image-picker) or a web Blob/File. */
export type ImageFile = { uri: string; name?: string; type?: string } | Blob;

export interface ClientOptions {
  /** e.g. "http://192.168.1.20:8000" (no trailing /api/v1) */
  baseUrl: string;
  /** only if the server was started with HEMLOCK_API_KEY */
  apiKey?: string;
  /** sign-in token (from login/register); can also be set later with setToken() */
  token?: string;
  /** forest that tree/capture calls work in (setForest()) */
  forestId?: number;
  /** default 60 s; identification of 3 photos takes ~0.5 s on a laptop, longer on a Pi */
  timeoutMs?: number;
}

export class HemlockApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
    this.name = "HemlockApiError";
  }
}

export class HemlockClient {
  private base: string;

  constructor(private opts: ClientOptions) {
    this.base = opts.baseUrl.replace(/\/+$/, "") + "/api/v1";
  }

  // --------------------------------------------------------------- account
  /** Signs in and keeps the token for later calls (persist it with e.g. expo-secure-store). */
  async login(email: string, password: string): Promise<LoginResult> {
    const r = await this.req<LoginResult>("POST", "/auth/login", { email, password });
    this.opts.token = r.token;
    return r;
  }
  async register(email: string, password: string, name: string): Promise<LoginResult> {
    const r = await this.req<LoginResult>("POST", "/auth/register", { email, password, name });
    this.opts.token = r.token;
    return r;
  }
  async logout(): Promise<void> {
    await this.req("POST", "/auth/logout");
    this.opts.token = undefined;
  }
  setToken(token: string | undefined): void {
    this.opts.token = token;
  }
  /** Choose the forest that trees / captures / identify / map calls use. */
  setForest(forestId: number | undefined): void {
    this.opts.forestId = forestId;
  }
  /** Everything on the account: forests with tree counts and severity breakdown. */
  me(): Promise<AccountOverview> {
    return this.req("GET", "/me");
  }
  listForests(): Promise<ForestSummary[]> {
    return this.req("GET", "/forests");
  }
  createForest(name: string, center?: { lat: number; lon: number }): Promise<ForestSummary> {
    return this.req("POST", "/forests", { name, lat: center?.lat ?? null, lon: center?.lon ?? null });
  }
  /** GeoJSON FeatureCollection: one point per tree with severity (react-native-maps: render as Markers). */
  forestMap(forestId?: number): Promise<ForestMap> {
    const id = forestId ?? this.opts.forestId;
    return id == null ? this.req("GET", "/map") : this.req("GET", `/forests/${id}/map`);
  }

  // ------------------------------------------------------------------ meta
  health(): Promise<Health> {
    return this.req("GET", "/health");
  }
  model(): Promise<ModelInfo> {
    return this.req("GET", "/model");
  }
  /** The guided photo sequence (instructions to show the user for each view). */
  protocol(): Promise<Protocol> {
    return this.req("GET", "/protocol");
  }

  // -------------------------------------------------------- guided capture
  /** Start a guided capture: then addView() per photo, then identifyCapture(). */
  createCapture(): Promise<CaptureCreated> {
    return this.req("POST", "/captures");
  }
  getCapture(captureId: string): Promise<CaptureState> {
    return this.req("GET", `/captures/${enc(captureId)}`);
  }
  /** Upload one photo; check `view.accepted` and show `view.problems` if it must be retaken. */
  addView(captureId: string, image: ImageFile, opts: { viewKey?: string; headingDeg?: number } = {}): Promise<ViewAdded> {
    const form = new FormData();
    appendImage(form, "image", image, 0);
    if (opts.viewKey) form.append("view_key", opts.viewKey);
    if (opts.headingDeg != null) form.append("heading_deg", String(opts.headingDeg));
    return this.req("POST", `/captures/${enc(captureId)}/views`, form);
  }
  /**
   * action "done": stored as tree_id; "capture_another_view": take `next_view` then call again;
   * "review": stored unassigned, let the user pick from `candidates` (assignObservation);
   * "retake": not enough good photos.
   */
  identifyCapture(
    captureId: string,
    opts: { forceCommit?: boolean; location?: Location; severity?: Severity; healthNotes?: string } = {},
  ): Promise<IdentifyResult> {
    return this.req("POST", `/captures/${enc(captureId)}/identify`, {
      force_commit: opts.forceCommit ?? false,
      location: opts.location ?? null,
      severity: opts.severity ?? null,
      health_notes: opts.healthNotes ?? null,
    });
  }
  cancelCapture(captureId: string): Promise<void> {
    return this.req("DELETE", `/captures/${enc(captureId)}`);
  }

  // -------------------------------------------------------------- one-shot
  /** All 3-7 photos at once (trunk north, +90°, +180°, ...). Stored unless commit=false. */
  identify(
    images: ImageFile[],
    opts: {
      viewKeys?: string[];
      headings?: (number | null)[];
      location?: Location;
      severity?: Severity;
      healthNotes?: string;
      commit?: boolean;
    } = {},
  ): Promise<IdentifyResult> {
    const form = new FormData();
    images.forEach((im, i) => appendImage(form, "images", im, i));
    if (opts.viewKeys) form.append("view_keys", opts.viewKeys.join(","));
    if (opts.headings) form.append("headings", opts.headings.map((h) => (h == null ? "" : String(h))).join(","));
    if (opts.location) {
      form.append("lat", String(opts.location.lat));
      form.append("lon", String(opts.location.lon));
      if (opts.location.accuracy_m != null) form.append("accuracy_m", String(opts.location.accuracy_m));
    }
    if (opts.severity != null) form.append("severity", String(opts.severity));
    if (opts.healthNotes) form.append("health_notes", opts.healthNotes);
    if (opts.commit === false) form.append("commit", "false");
    return this.req("POST", "/identify", form);
  }

  // ----------------------------------------------------------------- trees
  listTrees(opts: { species?: string; limit?: number; offset?: number } = {}): Promise<TreePage> {
    return this.req("GET", "/trees" + query(opts));
  }
  getTree(treeId: string): Promise<TreeDetail> {
    return this.req("GET", `/trees/${enc(treeId)}`);
  }
  updateTree(treeId: string, patch: { notes: string | null }): Promise<TreeSummary> {
    return this.req("PATCH", `/trees/${enc(treeId)}`, patch);
  }
  /** Fold a duplicate tree into treeId (the duplicate's ID is retired). */
  mergeTrees(treeId: string, duplicateTreeId: string): Promise<TreeDetail> {
    return this.req("POST", `/trees/${enc(treeId)}/merge`, { duplicate_tree_id: duplicateTreeId });
  }

  // ---------------------------------------------------------- observations
  listObservations(
    opts: { status?: string[]; unassigned?: boolean; limit?: number; offset?: number } = {},
  ): Promise<ObservationPage> {
    return this.req("GET", "/observations" + query(opts));
  }
  /** Uncertain observations waiting for the user to pick a tree. */
  reviewQueue(opts: { limit?: number; offset?: number } = {}): Promise<ObservationPage> {
    return this.listObservations({ ...opts, status: ["uncertain"], unassigned: true });
  }
  getObservation(observationId: string): Promise<Observation> {
    return this.req("GET", `/observations/${enc(observationId)}`);
  }
  /** Record or change the severity rating of a visit. */
  setHealth(observationId: string, severity: Severity | null, notes?: string): Promise<Observation> {
    return this.req("PUT", `/observations/${enc(observationId)}/health`, { severity, notes: notes ?? null });
  }
  /** Resolve an uncertain observation or correct a wrong match. treeId: "H-001" or "new". */
  assignObservation(observationId: string, treeId: string): Promise<AssignResult> {
    return this.req("POST", `/observations/${enc(observationId)}/assign`, { tree_id: treeId });
  }

  // ---------------------------------------------------------------- images
  /** Absolute URL for an `image_url` / `thumbnail_url` returned by the API. */
  imageUrl(path: string): string {
    return this.opts.baseUrl.replace(/\/+$/, "") + path;
  }
  /** Ready for React Native <Image source={...}> (adds sign-in / forest / API key headers). */
  imageSource(path: string): { uri: string; headers: Record<string, string> } {
    return { uri: this.imageUrl(path), headers: this.authHeaders() };
  }

  private authHeaders(): Record<string, string> {
    const h: Record<string, string> = {};
    if (this.opts.apiKey) h["X-API-Key"] = this.opts.apiKey;
    if (this.opts.token) h.Authorization = `Bearer ${this.opts.token}`;
    if (this.opts.forestId != null) h["X-Forest-Id"] = String(this.opts.forestId);
    return h;
  }

  // --------------------------------------------------------------- private
  private async req<T>(method: string, path: string, body?: FormData | object): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json", ...this.authHeaders() };
    let payload: FormData | string | undefined;
    if (body instanceof FormData) payload = body; // fetch sets the multipart boundary itself
    else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.opts.timeoutMs ?? 60_000);
    let res: Response;
    try {
      res = await fetch(this.base + path, { method, headers, body: payload, signal: ctrl.signal });
    } catch (e) {
      const aborted = (e as Error)?.name === "AbortError";
      throw new HemlockApiError(0, aborted ? "timeout" : "network_error",
        aborted ? "request timed out" : `cannot reach ${this.opts.baseUrl}: ${(e as Error)?.message ?? e}`);
    } finally {
      clearTimeout(timer);
    }
    if (res.status === 204) return undefined as T;
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const err = data?.error;
      throw new HemlockApiError(res.status, err?.code ?? "http_error", err?.message ?? `HTTP ${res.status}`);
    }
    return data as T;
  }
}

function appendImage(form: FormData, field: string, image: ImageFile, i: number): void {
  if (typeof Blob !== "undefined" && image instanceof Blob) {
    form.append(field, image, `photo${i}.jpg`);
  } else {
    const f = image as { uri: string; name?: string; type?: string };
    // React Native's FormData accepts { uri, name, type } file parts.
    form.append(field, { uri: f.uri, name: f.name ?? `photo${i}.jpg`, type: f.type ?? "image/jpeg" } as unknown as Blob);
  }
}

function enc(s: string): string {
  return encodeURIComponent(s);
}

function query(o: Record<string, unknown>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) {
    if (v == null) continue;
    if (Array.isArray(v)) v.forEach((x) => q.append(k, String(x)));
    else q.append(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
