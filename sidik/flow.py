"""Where in the payment flow the transaction stopped.

Reads nothing but the ids already in the log: how many distinct transactions
reached payment, core, notify, settlement. The hop that loses the most is the
answer, and it needs no vocabulary at all.
"""

from __future__ import annotations

from .find import TRX
from .source import Event


def funnel(events: list[Event], stages: list[str]) -> list[dict]:
    seen: dict[str, set[str]] = {job: set() for job in stages}
    for e in events:
        if e.job not in seen:
            continue
        for trx in TRX.findall(e.msg):
            seen[e.job].add(trx.upper())

    rows, before = [], None
    for job in stages:
        ids = len(seen[job])
        rows.append({
            "job": job,
            "ids": ids,
            "lost": 0 if before is None else max(0, before - ids),
        })
        before = ids
    return rows


def worst_hop(rows: list[dict]) -> dict | None:
    """The stage that dropped the most transactions. None when nothing dropped."""
    losing = [r for r in rows if r["lost"] > 0]
    return max(losing, key=lambda r: r["lost"]) if losing else None
