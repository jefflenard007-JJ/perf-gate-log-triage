"""Parse JSON-lines or common plain-text log formats into LogEvent records."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

ERROR_LEVELS = {"ERROR", "CRITICAL", "FATAL"}

# e.g. "2026-10-20 09:15:02,123 ERROR [payments] Timeout calling bank-gateway after 3000 ms"
PLAIN_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s+"
    r"(?P<level>[A-Z]+)\s+(?:\[(?P<service>[^\]]+)\]\s+)?(?P<msg>.*)$"
)

# Variable parts replaced so identical problems group together
_NORMALISERS = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"(['\"]).*?\1"), "<str>"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "<n>"),
]


@dataclass(frozen=True)
class LogEvent:
    ts: datetime
    level: str
    service: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.level in ERROR_LEVELS

    @property
    def signature(self) -> str:
        return signature(self.message)


def signature(message: str) -> str:
    sig = message.strip()
    for pattern, repl in _NORMALISERS:
        sig = pattern.sub(repl, sig)
    return sig[:200]


def _parse_ts(value: str) -> datetime:
    value = value.strip().replace("Z", "+00:00")
    # Python accepts +1100 only from 3.11 onwards via fromisoformat; normalise to +11:00
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)
    dt = datetime.fromisoformat(value.replace(",", ".").replace(" ", "T", 1))
    return dt.replace(tzinfo=None)  # compare in the log's own local time


def parse_line(line: str, default_service: str = "unknown") -> LogEvent | None:
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            data = json.loads(line)
            ts = data.get("ts") or data.get("timestamp") or data.get("time") or data.get("@timestamp")
            msg = data.get("msg") or data.get("message") or ""
            if data.get("status") and data.get("path"):
                msg = f"{msg} {data.get('method', '')} {data['path']} -> {data['status']}".strip()
            return LogEvent(
                ts=_parse_ts(str(ts)),
                level=str(data.get("level", "INFO")).upper(),
                service=str(data.get("service", default_service)),
                message=msg,
            )
        except (ValueError, TypeError):
            return None
    match = PLAIN_RE.match(line)
    if not match:
        return None
    return LogEvent(
        ts=_parse_ts(match["ts"]),
        level=match["level"].upper(),
        service=match["service"] or default_service,
        message=match["msg"],
    )


def parse_lines(lines: Iterable[str]) -> Iterator[LogEvent]:
    for line in lines:
        event = parse_line(line)
        if event is not None:
            yield event
