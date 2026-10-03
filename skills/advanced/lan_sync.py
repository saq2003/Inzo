"""LAN sync protocol: offline device-to-device message envelopes.

Real protocol, stdlib only, no cloud. :class:`SyncEnvelope` is the wire
unit ``{kind, payload, node_id, ts}``; :class:`SyncProtocol` builds
advertise/discover/push/pull messages and parses/validates raw bytes
(pure functions — no sockets). :class:`LocalLoopbackTransport`
implements the :class:`Transport` protocol over ``socket.socketpair``
so the full send/recv path can be exercised honestly on one machine.

Plug-in point for real LAN use: implement :class:`Transport` with UDP
broadcast (``SO_BROADCAST``) for discovery plus TCP for push/pull, and
pass it wherever a ``Transport`` is expected — the envelope format and
``SyncProtocol`` stay unchanged.
"""

from __future__ import annotations

import json
import secrets
import select
import socket
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE_FILE = "lan_sync.db"
_NODE_KEY = "lan_sync:node_id"
_FRAME_HEADER = struct.Struct("!I")
_KINDS = ("advertise", "discover", "push", "pull")


class SyncError(Exception):
    """Raised when a sync envelope fails validation."""


@dataclass(frozen=True)
class SyncEnvelope:
    """Wire unit for device-to-device sync."""

    kind: str  # one of advertise | discover | push | pull
    payload: dict[str, Any]
    node_id: str
    ts: str  # ISO-8601 UTC


class SyncProtocol:
    """Pure message constructors + parse/validate for the sync protocol."""

    VERSION = 1

    @staticmethod
    def _envelope(kind: str, node_id: str, payload: dict[str, Any]) -> SyncEnvelope:
        if kind not in _KINDS:
            raise SyncError(f"unknown envelope kind: {kind!r}")
        if not node_id:
            raise SyncError("node_id must be non-empty")
        return SyncEnvelope(
            kind=kind,
            payload=dict(payload),
            node_id=node_id,
            ts=datetime.now(UTC).isoformat(),
        )

    @staticmethod
    def advertise(node_id: str, capabilities: list[str]) -> SyncEnvelope:
        """'I am here' broadcast: node identity + capabilities."""
        return SyncProtocol._envelope(
            "advertise",
            node_id,
            {"version": SyncProtocol.VERSION, "capabilities": list(capabilities)},
        )

    @staticmethod
    def discover(node_id: str) -> SyncEnvelope:
        """'Who is here?' broadcast soliciting advertisements."""
        return SyncProtocol._envelope("discover", node_id, {"version": SyncProtocol.VERSION})

    @staticmethod
    def push(node_id: str, kind: str, payload: dict[str, Any]) -> SyncEnvelope:
        """Push a payload of application ``kind`` to a peer."""
        return SyncProtocol._envelope("push", node_id, {"data_kind": kind, "data": dict(payload)})

    @staticmethod
    def pull(node_id: str, kinds: list[str]) -> SyncEnvelope:
        """Request payloads of the given application kinds from a peer."""
        return SyncProtocol._envelope("pull", node_id, {"wanted": list(kinds)})

    @staticmethod
    def to_bytes(envelope: SyncEnvelope) -> bytes:
        """Serialize an envelope to JSON bytes (framing is transport's job)."""
        return json.dumps(
            {
                "kind": envelope.kind,
                "payload": envelope.payload,
                "node_id": envelope.node_id,
                "ts": envelope.ts,
            }
        ).encode("utf-8")

    @staticmethod
    def parse(data: bytes) -> SyncEnvelope:
        """Parse and validate raw bytes into a :class:`SyncEnvelope`."""
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SyncError(f"envelope is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise SyncError("envelope must be a JSON object")
        kind = raw.get("kind")
        payload = raw.get("payload")
        node_id = raw.get("node_id")
        ts = raw.get("ts")
        if kind not in _KINDS:
            raise SyncError(f"unknown envelope kind: {kind!r}")
        if not isinstance(payload, dict):
            raise SyncError("envelope payload must be an object")
        if not isinstance(node_id, str) or not node_id:
            raise SyncError("envelope node_id must be a non-empty string")
        if not isinstance(ts, str):
            raise SyncError("envelope ts must be a string")
        try:
            datetime.fromisoformat(ts)
        except ValueError as exc:
            raise SyncError(f"envelope ts is not ISO-8601: {ts!r}") from exc
        return SyncEnvelope(
            kind=cast("str", kind),
            payload=cast("dict[str, Any]", payload),
            node_id=node_id,
            ts=ts,
        )


class Transport(Protocol):
    """Byte transport for sync envelopes (implemented per medium)."""

    def send(self, data: bytes) -> None:
        """Send one framed message."""
        ...

    def recv(self, timeout: float = 5.0) -> bytes:
        """Receive one framed message; raises ``TimeoutError`` on timeout."""
        ...


class LocalLoopbackTransport:
    """Honest local transport over ``socket.socketpair``.

    Each transport owns one end of the pair (sockets are full-duplex);
    use :meth:`peer` to wrap the other end, e.g. in tests or when
    bridging two local agents. Frames are 4-byte big-endian
    length-prefixed.
    """

    def __init__(self, sock: socket.socket | None = None) -> None:
        if sock is None:
            self._sock, mate = socket.socketpair()
            self._mate: socket.socket | None = mate
        else:
            self._sock = sock
            self._mate = None
        self._closed = False

    def peer(self) -> LocalLoopbackTransport:
        """Return a transport bound to the other end of this pair (one-shot)."""
        if self._mate is None:
            raise SyncError("peer end already taken")
        mate, self._mate = self._mate, None
        return LocalLoopbackTransport(sock=mate)

    def send(self, data: bytes) -> None:
        if self._closed:
            raise SyncError("transport is closed")
        frame = _FRAME_HEADER.pack(len(data)) + data
        self._sock.sendall(frame)

    def recv(self, timeout: float = 5.0) -> bytes:
        if self._closed:
            raise SyncError("transport is closed")
        ready, _, _ = select.select([self._sock], [], [], timeout)
        if not ready:
            raise TimeoutError("timed out waiting for sync frame")
        header = self._recvall(_FRAME_HEADER.size)
        (length,) = _FRAME_HEADER.unpack(header)
        if length > 16 * 1024 * 1024:
            raise SyncError(f"frame too large: {length} bytes")
        return self._recvall(length)

    def _recvall(self, count: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            chunk = self._sock.recv(count - len(chunks))
            if not chunk:
                raise SyncError("peer closed the connection")
            chunks.extend(chunk)
        return bytes(chunks)

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass


def _node_id(data_dir: Path) -> str:
    store = SQLiteKVStore(data_dir / _STORE_FILE)
    node_id = store.get(_NODE_KEY)
    if not node_id:
        node_id = "inzo-" + secrets.token_hex(8)
        store.put(_NODE_KEY, node_id)
    return node_id


class LanSyncSkill(Skill):
    """Builds LAN sync envelopes (advertise/push) for this node."""

    name = "lan_sync"
    description = (
        "Offline LAN sync protocol: 'advertise' builds this node's "
        "advertisement envelope; 'push <kind> <json>' builds a push envelope."
    )
    intents = ("sync.advertise", "sync.push")
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        data_dir = require_data_dir(context)
        node_id = _node_id(data_dir)
        message = context.message.strip()
        lowered = message.lower()
        if lowered == "advertise" or lowered.startswith("advertise"):
            envelope = SyncProtocol.advertise(node_id, capabilities=["sync", "envelopes-v1"])
            raw = SyncProtocol.to_bytes(envelope)
            return (
                f"advertise envelope (node_id={node_id}, {len(raw)} bytes):\n{raw.decode('utf-8')}"
            )
        if lowered.startswith("push "):
            parts = message.split(None, 2)
            if len(parts) < 3:
                return "usage: push <kind> <json payload>"
            _, kind, payload_text = parts
            try:
                payload = cast("dict[str, Any]", json.loads(payload_text))
            except json.JSONDecodeError as exc:
                return f"payload is not valid JSON: {exc}"
            if not isinstance(payload, dict):
                return "payload must be a JSON object"
            envelope = SyncProtocol.push(node_id, kind, payload)
            raw = SyncProtocol.to_bytes(envelope)
            return (
                f"push envelope (kind={kind}, node_id={node_id}, {len(raw)} bytes):\n"
                f"{raw.decode('utf-8')}"
            )
        return "lan_sync: 'advertise' or 'push <kind> <json payload>'."


SKILLS: list[Skill] = [LanSyncSkill()]
