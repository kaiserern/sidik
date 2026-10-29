"""The router: given a report, decide which worker owns the failure.

This is the part that never calls an LLM. It walks a ladder, cheapest and most
certain first, and it says which rung answered:

  key      a transaction id was supplied, follow it across every worker
  found    no id typed, but amount/time in the report picked one log line,
           and that line carries the id
  flow     the id never surfaced, but the payment stages lost transactions
           between one hop and the next
  baseline one worker is erroring far above its own 7-day normal
  symptom  only a symptom was given, so the pool is narrowed by hand
  empty    nothing to go on, so it asks for one specific datum
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .find import find_trx
from .flow import funnel, worst_hop
from .hints import load_hints, symptom_key
from .redact import redact_event
from .source import Event, Plan

OWNERS_PATH = os.path.join(os.path.dirname(__file__), "owners.json")
ASK = "Minta satu hal ini: nominal transaksi dan jam kejadiannya, atau screenshot detail transaksinya."


@dataclass
class Verdict:
    sidik: str | None
    confidence: str  # high | medium | low
    basis: str
    reason: str
    evidence: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    owner: str | None = None
    channel: str | None = None
    found_trx: str | None = None
    baseline: dict[str, float] = field(default_factory=dict)
    reports: int = 0
    ask: str | None = None
    funnel: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sidik": self.sidik,
            "confidence": self.confidence,
            "basis": self.basis,
            "reason": self.reason,
            "owner": self.owner,
            "channel": self.channel,
            "found_trx": self.found_trx,
            "evidence": self.evidence,
            "counts": self.counts,
            "baseline": self.baseline,
            "reports": self.reports,
            "ask": self.ask,
            "funnel": self.funnel,
        }


def load_owners(path: str = OWNERS_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _baseline(source, minutes: int, now: datetime | None, days: int) -> dict[str, float]:
    """Average error lines per worker in the same clock window, over past days.

    One query per day. Seven of them per complaint only happens when no id was
    given, which is the case this exists for.
    """
    total: Counter = Counter()
    for d in range(1, days + 1):
        at = (now or datetime.now()) - timedelta(days=d)
        for e in source.fetch(Plan(minutes=minutes), now=at):
            if e.is_error:
                total[e.job] += 1
    return {job: round(n / days, 1) for job, n in total.items()}


def _rank(events: list[Event], allowed: list[str] | None) -> tuple[list[tuple[str, int]], Counter]:
    pool = [e for e in events if e.is_error] or events
    counts = Counter(e.job for e in pool)
    rows = [(job, n) for job, n in counts.items() if not allowed or job in allowed]
    return (rows or list(counts.items())), counts


def route(source, owners: dict, key: str | None = None, minutes: int = 120,
          now: datetime | None = None, text: str | None = None,
          hints: dict | None = None, baseline_days: int = 7,
          reports: int = 0) -> Verdict:
    hints = hints or load_hints()
    events = source.fetch(Plan(minutes=minutes, contains=key), now=now)
    discovered = False

    if not key and text and events:
        found, score = find_trx(events, text)
        if found:
            key, discovered = found, True
            events = source.fetch(Plan(minutes=minutes, contains=key), now=now)

    if not events:
        return Verdict(None, "low", "empty",
                       f"Tidak ada log dalam {minutes} menit terakhir untuk filter ini.",
                       reports=reports, ask=ASK)

    errors = [e for e in events if e.is_error]
    counts = Counter(e.job for e in events if e.is_error)
    if key:
        verdict = _by_key(key, counts, events, owners, discovered)
    elif errors:
        verdict = _by_evidence(source, events, owners, hints, minutes, now,
                               baseline_days, text)
    else:
        return Verdict(None, "low", "empty",
                       f"Ada {len(events)} baris log dalam {minutes} menit terakhir, "
                       "tapi tidak satu pun bertanda error.",
                       counts=dict(counts), reports=reports, ask=ASK)

    if reports >= 3 and verdict.sidik:
        verdict.reason += f" Sudah {reports} laporan serupa dalam 10 menit terakhir."
    return verdict


def _by_key(key: str, counts: Counter, events: list[Event], owners: dict,
            discovered: bool = False) -> Verdict:
    errors = [e for e in events if e.is_error]
    hit_jobs = {e.job for e in errors}
    base = counts.most_common()
    if base:
        top_job, top_n = base[0]
    else:
        top_job, top_n = (sorted(hit_jobs)[0] if hit_jobs else events[0].job), 0

    if len(hit_jobs) == 1:
        # An id found from amount+time is one inference away from the truth,
        # so it never claims high confidence.
        confidence = "medium" if discovered else "high"
        reason = (f"Transaksi {key} muncul di {len(counts)} worker, error hanya di "
                  f"{top_job} ({top_n} baris).")
    else:
        confidence = "medium"
        reason = (f"Transaksi {key} error di {len(hit_jobs)} worker, volume tertinggi "
                  f"di {top_job} ({top_n} baris).")

    basis = "found" if discovered else "key"
    return _build(top_job, confidence, basis, reason, events, owners, found_trx=key)


def _by_evidence(source, events, owners, hints, minutes, now, baseline_days, text) -> Verdict:
    flow = hints.get("flow") or []
    rows = funnel(events, flow) if flow else []
    hop = worst_hop(rows)
    first = rows[0]["ids"] if rows else 0
    if hop and first >= 5 and hop["lost"] >= max(1, first * 0.2):
        reason = (f"Dari {first} transaksi yang masuk {flow[0]}, hanya {hop['ids']} yang "
                  f"sampai {hop['job']} ({hop['lost']} hilang di hop sebelumnya).")
        v = _build(hop["job"], "medium", "flow", reason, events, owners)
        v.funnel = rows
        return v

    ref = now or events[-1].ts
    base = _baseline(source, minutes, ref, baseline_days) if baseline_days else {}
    sym = symptom_key(hints, text or "")
    allowed = (hints.get("symptoms", {}).get(sym) or {}).get("jobs") if sym else None
    ranked, counts = _rank(events, allowed)
    top_job = max(ranked, key=lambda r: (ranked_ratio(r, base), r[1]))[0]
    cur, avg = counts[top_job], base.get(top_job, 0.0)

    if base:
        usual = f"biasanya {avg} di jam yang sama" if avg else "biasanya tidak ada error di jam ini"
        reason = (f"Tanpa ID transaksi. {top_job} sekarang {cur} baris error, {usual} "
                  f"({round((cur + 1) / (avg + 1), 1)}x normal). Ini lead, bukan putusan.")
        basis = "baseline"
    else:
        reason = (f"Tanpa ID transaksi dan belum ada data pembanding 7 hari. {top_job} "
                  f"paling ramai ({cur} baris error). Ini lead, bukan putusan.")
        basis = "density"
    if sym:
        reason = f"{hints['symptoms'][sym]['label']}: {reason}"
        basis = "symptom"

    v = _build(top_job, "low", basis, reason, events, owners)
    v.baseline = base
    v.counts = dict(counts)
    v.funnel = rows
    return v


def ranked_ratio(row: tuple[str, int], base: dict[str, float]) -> float:
    return (row[1] + 1) / (base.get(row[0], 0.0) + 1)


def _build(job: str, confidence: str, basis: str, reason: str, events, owners, **kw) -> Verdict:
    owner_row = owners.get(job, {})
    evidence = [f"{e.ts:%H:%M:%S} {e.job} {redact_event(e.msg)}"
                for e in events if e.job == job and e.is_error][-3:]
    return Verdict(
        sidik=job,
        confidence=confidence,
        basis=basis,
        reason=reason,
        evidence=evidence,
        counts=dict(Counter(e.job for e in events if e.is_error)),
        owner=owner_row.get("owner"),
        channel=owner_row.get("channel"),
        **kw,
    )


def render(v: Verdict) -> str:
    if v.sidik is None:
        lines = [f"Belum bisa ditentukan. {v.reason}"]
        if v.ask:
            lines.append(f"Butuh dari lu: {v.ask}")
        return "\n".join(lines)

    lines = [
        f"Penyebab: {v.sidik}" + (f" ({v.owner})" if v.owner else ""),
        f"Keyakinan: {v.confidence}",
        f"Dasar: {v.reason}",
    ]
    if v.found_trx and v.basis != "key":
        lines.append(f"ID yang dipakai: {v.found_trx}")
    if v.channel:
        lines.append(f"Eskalasi ke: #{v.channel}")
    if v.counts:
        lines.append("Sebaran: " + ", ".join(f"{j}={n}" for j, n in v.counts.items()))
    if v.reports >= 2:
        lines.append(f"Laporan serupa: {v.reports} dalam 10 menit")
    if v.funnel:
        lines.append("Alur: " + " -> ".join(f"{r['job'].removeprefix('worker-')}={r['ids']}"
                                            for r in v.funnel))
    if v.evidence:
        lines.append("Bukti:")
        lines.extend(f"  {e}" for e in v.evidence)
    if v.ask:
        lines.append(f"Butuh dari lu: {v.ask}")
    return "\n".join(lines)
