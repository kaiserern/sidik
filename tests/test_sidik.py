"""Self-check: the router must reproduce the sample incident, and nothing may leak."""

import json
import os

import pytest

from sidik import interpret
from sidik.redact import redact
from sidik.route import load_owners, render, route
from sidik.source import ReplaySource

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample.jsonl")
TRX = "TRX2026102900123"


@pytest.fixture()
def source():
    return ReplaySource(SAMPLE)


@pytest.fixture()
def owners():
    return load_owners()


def test_redact_masks_card_nik_phone_email():
    raw = "acct=1234567890123 card=4111111111111111 hp=+6281234567890 mail=ops.desk@example.co.id"
    out = redact(raw)
    assert "4111111111111111" not in out
    assert "1234567890123" not in out
    assert "6281234567890" not in out
    assert "ops.desk@example.co.id" not in out


def test_key_path_blames_payment(source, owners):
    v = route(source, owners, key=TRX)
    assert v.sidik == "worker-payment"
    assert v.confidence == "high"
    assert v.owner == "Payment Ops"
    assert v.channel == "payment-war-room"
    assert v.counts["worker-payment"] == 2


def test_key_path_evidence_is_redacted(source, owners):
    v = route(source, owners, key=TRX)
    blob = render(v)
    assert "4111111111111111" not in blob
    assert "1234567890123" not in blob
    assert "[REDACTED-ID]" in blob


def test_density_path_ranks_but_flags_low_confidence(source, owners):
    v = route(source, owners, key=None)
    assert v.sidik == "worker-payment"
    assert v.confidence == "low"
    assert v.basis == "density"


def test_unknown_key_returns_nothing(source, owners):
    v = route(source, owners, key="TRX0000000000000")
    assert v.sidik is None
    assert v.basis == "empty"


def test_extract_without_llm_still_finds_the_id(monkeypatch):
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    params = interpret.extract("tolong cek TRX2026102900123 transfer gagal")
    assert params["trx_id"] == TRX
    assert params["engine"] == "fallback"


def test_triage_end_to_end(source, owners, monkeypatch):
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    verdict, params = interpret.triage(source, owners, "cek dong TRX2026102900123 kok gagal")
    assert params["engine"] == "fallback"
    assert verdict.sidik == "worker-payment"
    assert verdict.confidence == "high"


def test_json_output_is_serialisable(source, owners):
    v = route(source, owners, key=TRX)
    assert json.loads(json.dumps(v.to_dict()))["sidik"] == "worker-payment"


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_post(content):
    return lambda *a, **kw: _Resp({"choices": [{"message": {"content": content}}]})


def test_extract_parses_llm_json(monkeypatch, source, owners):
    monkeypatch.setenv("LLM_BASE_URL", "http://example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setattr(
        interpret.httpx, "post",
        _fake_post('{"trx_id": "TRX2026102900123", "symptom": "transfer failed", "minutes": 45}'),
    )
    verdict, params = interpret.triage(source, owners, "nasabah komplain transfer gagal")
    assert params["engine"] == "llm"
    assert params["minutes"] == 45
    assert verdict.sidik == "worker-payment"
    assert verdict.confidence == "high"


def test_narrate_never_costs_the_answer(monkeypatch, source, owners):
    monkeypatch.setenv("LLM_BASE_URL", "http://example.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setenv("LLM_MODEL", "m")

    def boom(*a, **kw):
        raise interpret.httpx.ConnectError("down")

    monkeypatch.setattr(interpret.httpx, "post", boom)
    verdict = route(source, owners, key=TRX)
    assert "worker-payment" in interpret.narrate("komplain", verdict)


# --- the ladder for reports that arrive without an id -----------------------

from datetime import datetime, timedelta  # noqa: E402

from sidik import cluster, ocr  # noqa: E402
from sidik.find import amounts, find_trx  # noqa: E402
from sidik.flow import funnel, worst_hop  # noqa: E402
from sidik.source import Event, Plan, ReplaySource as Replay  # noqa: E402

NOW = datetime.fromisoformat("2026-10-29T14:10:00+07:00")


def _write(tmp_path, rows):
    path = tmp_path / "log.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(path)


def _ev(ts, job, msg, level="error"):
    return Event(ts=ts, job=job, level=level, msg=msg)


def test_amounts_read_rupiah_forms():
    assert amounts("Rp1.250.000") == {1250000}
    assert 1250000 in amounts("transfer 1250000 gagal")


def test_find_trx_needs_two_signals(source):
    events = source.fetch(Plan(minutes=1440), now=NOW)
    assert find_trx(events, "transfer gagal tanpa detail") == (None, 0)
    trx, score = find_trx(events, "nasabah transfer Rp1.250.000 jam 14:00 gagal")
    assert trx == TRX
    assert score >= 2


def test_find_trx_refuses_a_tie():
    ts = NOW
    events = [
        _ev(ts, "worker-payment", "transfer received trx_id=TRX2026102900999 amount=Rp500.000"),
        _ev(ts, "worker-payment", "transfer received trx_id=TRX2026102900888 amount=Rp500.000"),
    ]
    trx, _ = find_trx(events, "transfer Rp500.000 jam 14:09 gagal")
    assert trx is None


def test_route_discovers_id_from_amount(source, owners):
    v = route(source, owners, text="nasabah transfer Rp1.250.000 jam 14:00 gagal", now=NOW)
    assert v.basis == "found"
    assert v.found_trx == TRX
    assert v.sidik == "worker-payment"
    assert v.confidence == "medium"  # inferred id never claims high


def test_baseline_beats_raw_volume(tmp_path, owners):
    rows = []
    for d in range(1, 8):
        day = NOW - timedelta(days=d)
        rows += [
            {"ts": (day - timedelta(minutes=m)).isoformat(), "job": "worker-notify",
             "level": "error", "msg": f"sms gateway timeout attempt={m}"}
            for m in range(10)
        ]
    rows += [
        {"ts": (NOW - timedelta(minutes=m)).isoformat(), "job": "worker-payment",
         "level": "error", "msg": f"upstream timeout trx_id=TRX2026102900{m:03d}"}
        for m in range(3)
    ]
    v = route(Replay(_write(tmp_path, rows)), owners, minutes=120, now=NOW)
    assert v.basis == "baseline"
    assert v.sidik == "worker-payment"  # 4x normal, while notify went quiet
    assert v.baseline["worker-notify"] == 10.0


def test_symptom_narrows_the_pool(tmp_path, owners):
    rows = [
        {"ts": (NOW - timedelta(minutes=m)).isoformat(), "job": "worker-notify",
         "level": "error", "msg": f"sms gateway timeout attempt={m}"}
        for m in range(9)
    ] + [
        {"ts": (NOW - timedelta(minutes=m)).isoformat(), "job": "worker-payment",
         "level": "error", "msg": f"upstream timeout trx_id=TRX1{m:06d}"}
        for m in range(2)
    ]
    source = Replay(_write(tmp_path, rows))
    loud = route(source, owners, minutes=120, now=NOW)
    assert loud.sidik == "worker-notify"

    narrowed = route(source, owners, minutes=120, now=NOW,
                     text="dana kepotong tapi belum masuk")
    assert narrowed.basis == "symptom"
    assert narrowed.sidik == "worker-payment"


def test_funnel_finds_the_hop_that_lost_transactions():
    ts = NOW
    events = [_ev(ts, "worker-payment", f"received trx_id=TRX2026102900{i:03d}") for i in range(10)]
    events += [_ev(ts, "worker-core", f"ok trx_id=TRX2026102900{i:03d}") for i in range(3)]
    rows = funnel(events, ["worker-payment", "worker-core", "worker-notify"])
    assert [r["ids"] for r in rows] == [10, 3, 0]
    assert worst_hop(rows)["job"] == "worker-core"


def test_route_uses_the_funnel_when_the_gap_is_big(owners):
    class Synthetic:
        name = "synthetic"

        def fetch(self, plan, now=None):
            return events

    ts = NOW
    events = [_ev(ts, "worker-payment", f"received trx_id=TRX2026102900{i:03d}") for i in range(10)]
    events += [_ev(ts, "worker-core", f"ok trx_id=TRX2026102900{i:03d}") for i in range(3)]
    v = route(Synthetic(), owners, now=NOW, baseline_days=0)
    assert v.basis == "flow"
    assert v.sidik == "worker-core"


def test_cluster_counts_reports_in_the_window(tmp_path, monkeypatch):
    db = str(tmp_path / "c.db")
    now = 1_000_000.0
    for i in range(3):
        cluster.record("gagal transfer", path=db, ts=now - i * 60)
    cluster.record("gagal transfer", path=db, ts=now - 3600)
    assert cluster.size("gagal transfer", path=db, now=now) == 3
    assert cluster.size("lain", path=db, now=now) == 0


def test_ocr_without_tesseract_says_so(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda _: None)
    with pytest.raises(ocr.NoOCR):
        ocr.read_image("struk.png")


def test_replay_ignores_events_after_now(source):
    early = datetime.fromisoformat("2026-10-29T12:00:00+07:00")
    assert source.fetch(Plan(minutes=120), now=early) == []
