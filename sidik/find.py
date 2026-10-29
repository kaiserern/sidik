"""Find the transaction id inside the logs when the reporter did not type one.

Usually the complaint carries an amount, a clock time, or both. That is enough
to pick one line out of the window, and that line already holds the trx_id, so
the reporter never has to look it up. Nothing here guesses: a match either
survives the filters or the caller gets told it is ambiguous.
"""

from __future__ import annotations

import re
from datetime import datetime

from .source import Event

# Amounts are written Rp1.250.000 or 1250000. Thousand separators are dropped,
# the rest of the punctuation goes away.
NUM = re.compile(r"\d[\d.,]*")
CLOCK = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
TRX = re.compile(r"\b(?:TRX|TRF|ORD|INV|REF)[A-Z0-9]{6,}\b", re.IGNORECASE)
SEP = re.compile(r"(?<=\d)[.,](?=\d{3}\b)")


def _digits(tok: str) -> str:
    # shortcut: "1,5" reads as 15. Complaints quote whole rupiah, so this holds.
    return SEP.sub("", tok.rstrip(".,")).replace(".", "").replace(",", "")


def amounts(text: str) -> set[int]:
    out = set()
    for m in NUM.finditer(text):
        d = _digits(m.group(0))
        if 3 <= len(d) <= 12:
            out.add(int(d))
    return out


def clock(text: str) -> tuple[int, int] | None:
    m = CLOCK.search(text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _minutes_off(ts: datetime, hh: int, mm: int) -> int:
    """How far the event sits from a bare clock time, in minutes, wrapping a day."""
    off = abs((ts.hour * 60 + ts.minute) - (hh * 60 + mm))
    return min(off, 1440 - off)


def find_trx(events: list[Event], text: str, slop_minutes: int = 15) -> tuple[str | None, int]:
    """Return the id (or None) and how many independent signals backed it."""
    want = amounts(text)
    at = clock(text)
    if not (want or at):
        return None, 0

    scored: list[tuple[int, str]] = []
    for e in events:
        found = TRX.findall(e.msg)
        if not found:
            continue
        score = 0
        if want & amounts(e.msg):
            score += 2
        if at and _minutes_off(e.ts, *at) <= slop_minutes:
            score += 1
        if score:
            scored.append((score, found[0].upper()))

    if not scored:
        return None, 0

    best = max(s for s, _ in scored)
    winner = {trx for s, trx in scored if s == best}
    # One amount match is coincidence-prone; demand an amount or two signals.
    if best < 2 or len(winner) != 1:
        return None, best
    return winner.pop(), best
