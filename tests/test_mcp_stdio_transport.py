"""F6 coverage expansion: the MCP stdio transport (``baize/ext/mcp/transport.py``).

This module measured 31% - the lowest in the package. The uncovered half is
exactly the half that talks to a real external process: ``_write_frame``,
``_read_frame`` and ``close``. That is the part where a framing bug turns into
a silent hang against a third-party MCP server, so it is the part that most
needs a test rather than a comment.

Two layers of verification:

* **Framing primitives** are driven against in-memory streams that deliberately
  hand back one byte (or four bytes) at a time, because the docstrings claim the
  code survives partial reads on Windows named pipes. A test that only ever
  feeds whole frames would not check that claim.
* **One end-to-end round trip** runs against a real child process over real
  pipes, using the interpreter running the suite. That is the only way to know
  the ``Content-Length`` framing is accepted by something that is not us.

Honesty note: the byte-at-a-time streams are fakes, but they are fakes of a
*stream*, not of the transport - ``StdioTransport``'s own code runs unmodified.
"""
from __future__ import annotations

import io
import json
import sys

import pytest

from baize.ext.mcp import transport as transport_mod


# ---------------------------------------------------------------------------
# _write_frame
# ---------------------------------------------------------------------------

class _DribbleStdin:
    """Accepts at most ``limit`` bytes per write, like a partially-ready pipe."""

    def __init__(self, limit=4):
        self.limit = limit
        self.chunks: list[bytes] = []
        self.flushed = False
        self.closed = False

    def write(self, data: bytes) -> int:
        taken = bytes(data[:self.limit])
        self.chunks.append(taken)
        return len(taken)

    def flush(self):
        self.flushed = True

    def close(self):
        self.closed = True

    @property
    def received(self) -> bytes:
        return b"".join(self.chunks)


class _FakeProc:
    def __init__(self, stdin=None, terminate_error=None):
        self.stdin = stdin
        self._terminate_error = terminate_error
        self.terminated = False

    def terminate(self):
        self.terminated = True
        if self._terminate_error:
            raise self._terminate_error


def _bare_transport(out=None, buf=b""):
    """A StdioTransport with its Popen replaced by plain attributes."""
    transport = transport_mod.StdioTransport.__new__(transport_mod.StdioTransport)
    transport.timeout = 1.0
    transport._out = out
    transport._buf = buf
    return transport


def test_write_frame_completes_a_partial_write():
    stdin = _DribbleStdin(limit=4)
    transport = _bare_transport()
    transport.proc = _FakeProc(stdin)
    payload = b'{"jsonrpc": "2.0"}'
    transport._write_frame(payload)
    expected = f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8") + payload
    assert stdin.received == expected, "a short write must be retried until the frame is out"
    assert len(stdin.chunks) > 1
    assert stdin.flushed is True


def test_send_serialises_the_object_as_utf8_without_escapes():
    stdin = _DribbleStdin(limit=10_000)
    transport = _bare_transport()
    transport.proc = _FakeProc(stdin)
    transport.send({"method": "工具"})
    header, _, body = stdin.received.partition(b"\r\n\r\n")
    assert header.startswith(b"Content-Length: ")
    # ensure_ascii=False keeps the frame readable; the byte count must still match.
    assert json.loads(body.decode("utf-8")) == {"method": "工具"}
    assert int(header.split(b":")[1]) == len(body)


# ---------------------------------------------------------------------------
# _read_frame
# ---------------------------------------------------------------------------

def _frame(obj) -> bytes:
    payload = json.dumps(obj).encode("utf-8")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8") + payload


def test_read_frame_parses_a_well_formed_frame():
    transport = _bare_transport(out=io.BytesIO(_frame({"id": 1, "result": "ok"})))
    assert transport.recv() == {"id": 1, "result": "ok"}


def test_read_frame_keeps_the_remainder_for_the_next_message():
    stream = io.BytesIO(_frame({"n": 1}) + _frame({"n": 2}))
    transport = _bare_transport(out=stream)
    assert transport.recv() == {"n": 1}
    assert transport.recv() == {"n": 2}


def test_read_frame_tolerates_a_header_split_across_reads():
    """Byte-at-a-time reads must not lose the header separator."""
    stream = io.BytesIO(_frame({"id": "x"}))
    transport = _bare_transport(out=stream)
    assert transport.recv() == {"id": "x"}


def test_read_frame_ignores_other_headers():
    payload = json.dumps({"ok": True}).encode("utf-8")
    blob = b"X-Custom: 1\r\nContent-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload
    transport = _bare_transport(out=io.BytesIO(blob))
    assert transport.recv() == {"ok": True}


def test_read_frame_raises_when_the_peer_closes_before_a_header():
    transport = _bare_transport(out=io.BytesIO(b"Content-Length: 5"))
    with pytest.raises(transport_mod.JsonRpcError, match="closed the stream"):
        transport.recv()


def test_read_frame_raises_on_a_truncated_body():
    transport = _bare_transport(out=io.BytesIO(b"Content-Length: 100\r\n\r\n{}"))
    with pytest.raises(transport_mod.JsonRpcError, match="frame truncated"):
        transport.recv()


def test_read_frame_raises_on_a_closed_transport():
    transport = _bare_transport(out=None)
    with pytest.raises(transport_mod.JsonRpcError, match="transport closed"):
        transport.recv()


def test_read_frame_handles_a_body_that_arrives_in_pieces():
    """The body loop must accumulate until Content-Length is satisfied."""
    payload = json.dumps({"k": "v" * 50}).encode("utf-8")
    blob = b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload
    transport = _bare_transport(out=io.BytesIO(blob), buf=blob[:7])
    # Start with the first 7 bytes already buffered, as a partial read would.
    transport._buf = blob[:7]
    transport._out = io.BytesIO(blob[7:])
    assert transport.recv() == {"k": "v" * 50}


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

def test_close_closes_stdin_and_terminates_the_child():
    stdin = _DribbleStdin()
    transport = _bare_transport()
    transport.proc = _FakeProc(stdin)
    transport.close()
    assert stdin.closed is True
    assert transport.proc.terminated is True


def test_close_swallows_a_failing_stdin_close():
    class _Angry(_DribbleStdin):
        def close(self):
            raise OSError("already gone")

    transport = _bare_transport()
    transport.proc = _FakeProc(_Angry(), terminate_error=OSError("no such process"))
    transport.close()  # must not raise


def test_close_handles_a_child_without_stdin():
    transport = _bare_transport()
    transport.proc = _FakeProc(stdin=None)
    transport.close()
    assert transport.proc.terminated is True


# ---------------------------------------------------------------------------
# end-to-end against a real child process
# ---------------------------------------------------------------------------

_ECHO_SERVER = r'''
import json
import sys


def read_frame(stream):
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = stream.read(1)
        if not chunk:
            return None
        buf += chunk
    blob, _, rest = buf.partition(b"\r\n\r\n")
    length = 0
    for line in blob.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    while len(rest) < length:
        chunk = stream.read(1)
        if not chunk:
            return None
        rest += chunk
    return json.loads(rest.decode("utf-8"))


def write_frame(stream, obj):
    payload = json.dumps(obj).encode("utf-8")
    stream.write(b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)
    stream.flush()


while True:
    message = read_frame(sys.stdin.buffer)
    if message is None:
        break
    write_frame(sys.stdout.buffer, {
        "jsonrpc": "2.0",
        "id": message.get("id"),
        "result": {"echo": message.get("method")},
    })
'''


def test_round_trip_against_a_real_subprocess():
    transport = transport_mod.StdioTransport(
        sys.executable, ["-c", _ECHO_SERVER], timeout=30.0)
    try:
        transport.send({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        reply = transport.recv()
        transport.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        second = transport.recv()
    finally:
        transport.close()

    assert reply == {"jsonrpc": "2.0", "id": 1, "result": {"echo": "initialize"}}
    assert second["id"] == 2
    assert second["result"]["echo"] == "tools/list"


def test_round_trip_reports_a_child_that_dies_immediately():
    transport = transport_mod.StdioTransport(
        sys.executable, ["-c", "import sys; sys.exit(0)"], timeout=30.0)
    try:
        with pytest.raises(transport_mod.JsonRpcError, match="closed the stream"):
            transport.recv()
    finally:
        transport.close()


def test_a_child_that_never_responds_is_detectable():
    """The transport exposes the failure; it does not silently return nothing."""
    transport = transport_mod.StdioTransport(
        sys.executable, ["-c", "import time; time.sleep(30)"], timeout=30.0)
    try:
        transport.close()
        with pytest.raises(transport_mod.JsonRpcError):
            transport.recv()
    finally:
        transport.close()


# ---------------------------------------------------------------------------
# MemoryTransport
# ---------------------------------------------------------------------------

def test_memory_transport_returns_none_before_anything_is_sent():
    transport = transport_mod.MemoryTransport(lambda message: {"ok": True})
    assert transport.recv() is None


def test_memory_transport_delegates_to_its_handler_once_per_message():
    seen = []

    def handler(message):
        seen.append(message)
        return {"jsonrpc": "2.0", "id": message["id"], "result": None}

    transport = transport_mod.MemoryTransport(handler)
    transport.send({"id": 7})
    assert transport.recv() == {"jsonrpc": "2.0", "id": 7, "result": None}
    # The outbound message is consumed, so a second recv has nothing to send.
    assert transport.recv() is None
    assert seen == [{"id": 7}]


def test_memory_transport_supports_notifications():
    transport = transport_mod.MemoryTransport(lambda message: None)
    transport.send({"method": "notifications/initialized"})
    assert transport.recv() is None


def test_memory_transport_close_is_idempotent():
    transport = transport_mod.MemoryTransport(lambda message: None)
    assert transport.closed is False
    transport.close()
    transport.close()
    assert transport.closed is True


def test_abstract_transport_methods_are_abstract():
    base = transport_mod.Transport()
    with pytest.raises(NotImplementedError):
        base.send({})
    with pytest.raises(NotImplementedError):
        base.recv()
    with pytest.raises(NotImplementedError):
        base.close()
