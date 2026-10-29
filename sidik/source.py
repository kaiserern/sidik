"""Structured worker log events, from Loki or a local replay file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

ERROR_MARKERS = ("error", "fatal", "panic", "timeout", "declined", "failed", "refused", "exception")
DISPLAY_TZ = ZoneInfo(os.environ.get("DISPLAY_TZ", "Asia/Jakarta"))


@dataclass
class Event:
    ts: datetime
    job: str
    level: str
    msg: str

    @property
    def is_error(self) -> bool:
        blob = f"{self.level} {self.msg}".lower()
        return any(m in blob for m in ERROR_MARKERS)


@dataclass
class Plan:
    """What the router wants to read. Both sources understand this, so no LogQL parsing."""

    minutes: int = 120
    contains: str | None = None


class ReplaySource:
    """Reads bundled JSONL. Same interface as the live source, no infra needed."""

    name = "replay"

    def __init__(self, path: str):
        self.path = path

    def fetch(self, plan: Plan, now: datetime | None = None) -> list[Event]:
        events = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                ev = Event(
                    ts=datetime.fromisoformat(row["ts"]),
                    job=row["job"],
                    level=row.get("level", "info"),
                    msg=row["msg"],
                )
                events.append(ev)
        if plan.contains:
            events = [e for e in events if plan.contains.lower() in e.msg.lower()]
        if now is not None:
            floor = now - timedelta(minutes=plan.minutes)
            # Both bounds: a replay used to count events newer than `now`, which
            # quietly faked a baseline for the shifted windows.
            events = [e for e in events if floor <= e.ts <= now]
        return sorted(events, key=lambda e: e.ts)


class LokiSource:
    """Live Loki. One query_range call per plan, newest first."""

    name = "loki"

    def __init__(self, base_url: str | None = None, jobs: str | None = None):
        self.base_url = (base_url or os.environ.get("LOKI_URL", "http://localhost:3100")).rstrip("/")
        self.jobs = jobs or os.environ.get("LOKI_JOB_REGEX", "worker-.+")

    def _logql(self, plan: Plan) -> str:
        q = f'{{job=~"{self.jobs}"}}'
        if plan.contains:
            q += f' |= {json.dumps(plan.contains)}'
        return q

    def fetch(self, plan: Plan, now: datetime | None = None) -> list[Event]:
        end = now or datetime.now(DISPLAY_TZ)
        start = end - timedelta(minutes=plan.minutes)
        r = httpx.get(
            f"{self.base_url}/loki/api/v1/query_range",
            params={
                "query": self._logql(plan),
                "start": str(int(start.timestamp() * 1e9)),
                "end": str(int(end.timestamp() * 1e9)),
                "limit": 500,
                "direction": "backward",
            },
            timeout=15,
        )
        r.raise_for_status()
        events = []
        for stream in r.json().get("data", {}).get("result", []):
            job = stream.get("stream", {}).get("job", "unknown")
            for ts_ns, line in stream.get("values", []):
                event = _parse_line(job, line)
                event.ts = datetime.fromtimestamp(int(ts_ns) / 1e9, tz=DISPLAY_TZ)
                events.append(event)
        return sorted(events, key=lambda e: e.ts)


def _parse_line(job: str, line: str) -> Event:
    """Workers log JSON. Fall back to the raw line if they do not."""
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return Event(ts=datetime.now(UTC), job=job, level="unknown", msg=line)
    return Event(
        ts=datetime.now(UTC),
        job=job,
        level=str(row.get("level", row.get("severity", "info"))).lower(),
        msg=str(row.get("msg", row.get("message", line))),
    )
