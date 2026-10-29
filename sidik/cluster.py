"""How many people are reporting the same thing right now.

One complaint is noise. Five complaints in ten minutes is an incident, and that
is often the only signal available when nobody has an id. Kept in sqlite so the
count survives a restart of the bot.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time

DB_PATH = os.environ.get("SIDIK_DB", "sidik.db")
SIG = re.compile(r"[a-z]+")


def signature(text: str, limit: int = 6) -> str:
    """Word bag of the complaint, so 'gagal transfer' and 'transfer gagal' match."""
    words = sorted(set(SIG.findall((text or "").lower())))[:limit]
    return " ".join(words)


def _db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("create table if not exists complaint (sig text, ts real)")
    conn.execute("create index if not exists complaint_sig on complaint(sig, ts)")
    return conn


def record(sig: str, path: str | None = None, ts: float | None = None) -> None:
    if not sig:
        return
    with _db(path or DB_PATH) as conn:
        conn.execute("insert into complaint values (?, ?)", (sig, ts or time.time()))


def size(sig: str, minutes: int = 10, path: str | None = None,
         now: float | None = None) -> int:
    """Including the complaint that just came in."""
    if not sig:
        return 0
    floor = (now or time.time()) - minutes * 60
    with _db(path or DB_PATH) as conn:
        row = conn.execute(
            "select count(*) from complaint where sig = ? and ts >= ?", (sig, floor)
        ).fetchone()
    return int(row[0])
