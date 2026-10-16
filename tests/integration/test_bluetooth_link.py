"""Pi -> backend link: wire format, and the full path Pi sender -> receiver -> HTTP API -> model -> back.

Runs over TCP (no Bluetooth radio in CI); RFCOMM uses the same byte stream.
"""

import socket
import threading
import time

import cv2
import pytest
import uvicorn

from hemlock_sentinel.api.server import create_api
from hemlock_sentinel.bluetooth.pi_sender import describe, send_capture
from hemlock_sentinel.bluetooth.protocol import ProtocolError, recv_message, send_message
from hemlock_sentinel.bluetooth.receiver import ApiClient, serve
from tests.helpers import tree_view
from tests.integration.test_accounts_forests import make_accounts


def _jpeg(img):
    return cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes()


def test_wire_format_roundtrip_and_rejects_garbage():
    a, b = socket.socketpair()
    blobs = [b"\xff\xd8" + bytes(range(256)) * 400, b"", b"x"]
    send_message(a, {"type": "capture", "lat": 34.8, "view_keys": ["trunk_north"]}, blobs)
    header, got = recv_message(b)
    assert header == {"type": "capture", "lat": 34.8, "view_keys": ["trunk_north"]} and got == blobs
    a.sendall(b"GET / HTTP/1.1\r\n\r\n")
    with pytest.raises(ProtocolError):
        recv_message(b)
    with pytest.raises(ProtocolError):
        send_message(a, {"type": "capture"}, [b"x"] * 9)
    c, d = socket.socketpair()
    c.sendall(b"HSBT\x01")  # peer disappears mid-message
    c.close()
    with pytest.raises(ConnectionError):
        recv_message(d)


@pytest.fixture
def backend(tmp_path):
    acc = make_accounts(tmp_path)
    app = create_api(accounts=acc)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    t = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}", acc
    server.should_exit = True
    t.join(5)


def test_pi_to_model_over_link(backend):
    url, acc = backend
    user = acc.register("pi@example.org", "field-device-pw", "Pi team")
    forest = acc.create_forest(user.user_id, "Test stand", 34.8, -84.1)
    api = ApiClient(url, "pi@example.org", "field-device-pw")

    srv = socket.create_server(("127.0.0.1", 0))
    stop = threading.Event()
    threading.Thread(target=serve, args=(srv, api, forest.forest_id, stop), daemon=True).start()
    pi = socket.create_connection(srv.getsockname(), timeout=30)

    send_message(pi, {"type": "ping"})
    assert recv_message(pi)[0] == {"type": "pong"}

    photos = [_jpeg(tree_view(9, v)) for v in range(3)]
    r1 = send_capture(pi, photos, {"lat": 34.801, "lon": -84.101, "severity": 2})
    assert r1["ok"] and r1["result"]["status"] == "new" and r1["result"]["tree_id"] == "H-001"
    assert "New tree registered as H-001" in describe(r1)
    r2 = send_capture(pi, [_jpeg(tree_view(9, v, 5)) for v in range(3)], {"lat": 34.801, "lon": -84.101})
    assert r2["result"]["status"] == "existing" and r2["result"]["tree_id"] == "H-001"
    assert "Existing tree H-001" in describe(r2)

    bad = send_capture(pi, photos[:1], {})
    assert not bad["ok"] and bad["error"]["code"] == "wrong_view_count"
    other = send_capture(pi, photos, {"forest_id": 999})
    assert not other["ok"] and other["error"]["code"] == "forest_not_found"
    pi.close()
    stop.set()
    srv.close()

    # stored in the signed-in account's forest, with the Pi's GPS and severity
    repo = acc.pipeline(forest).repo
    t = repo.get_tree("H-001")
    assert t.observation_count == 2
    from hemlock_sentinel.api import health
    st = health.tree_status(repo)[0]
    assert st["severity"] == 2 and st["lat"] == pytest.approx(34.801)
