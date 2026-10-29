"""Two ways to answer the same complaint, one command each."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import cluster, interpret, ocr
from .flow import funnel
from .hints import load_hints
from .interpret import TRX_HINT
from .route import load_owners, render, route
from .source import LokiSource, Plan, ReplaySource

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample.jsonl")
DEMO_REPORT = "transfer saya gagal, dana sudah terpotong tapi belum masuk ke rekening tujuan"


def build_source(args):
    if args.replay:
        return ReplaySource(args.replay)
    return LokiSource()


def _guard(args) -> None:
    """Loki is the default source, so say why it is about to fail instead of raising a stack trace."""
    if not args.replay and not os.environ.get("LOKI_URL"):
        raise SystemExit("LOKI_URL belum diisi. Untuk mencoba tanpa infra: --replay data/sample.jsonl")


def _text(args) -> str:
    """The report as written, plus whatever a screenshot adds."""
    text = args.report
    if args.image:
        try:
            text += "\n" + ocr.read_image(args.image)
        except ocr.NoOCR as exc:
            print(f"[ocr] {exc}", file=sys.stderr)
    return text


def cmd_ask(args) -> int:
    """The reporter gave an id, so nothing is guessed."""
    source = build_source(args)
    verdict = route(source, load_owners(), key=args.trx, minutes=args.minutes,
                    baseline_days=args.baseline_days)
    print(json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False) if args.json else render(verdict))
    return 0 if verdict.sidik else 1


def cmd_triage(args) -> int:
    """Free text in, the ladder answers. Nothing is required up front."""
    source = build_source(args)
    text = _text(args)
    sig = cluster.signature(text)
    cluster.record(sig)
    reports = cluster.size(sig)

    verdict, params = interpret.triage(source, load_owners(), text, reports=reports,
                                       baseline_days=args.baseline_days)

    if args.json:
        print(json.dumps({"params": params, **verdict.to_dict()}, indent=2, ensure_ascii=False))
        return 0 if verdict.sidik else 1

    print(f"[extract/{params['engine']}] trx={params['trx_id']} window={params['minutes']}m")
    print(render(verdict))
    if params["engine"] == "fallback":
        print("\n(LLM tidak dikonfigurasi. Jawaban di atas murni regex + router, tanpa panggilan model.)")
    else:
        print("\n" + interpret.narrate(text, verdict))
    return 0 if verdict.sidik else 1


def cmd_compare(args) -> int:
    """Same complaint through both modes. This is the demo for a non-technical reader."""
    source = build_source(args)
    owners = load_owners()
    text = _text(args)
    key = args.trx or (m.group(0) if (m := TRX_HINT.search(text)) else None)

    print("=" * 72)
    print("MODE A  tanpa AI" + (f"  (ID dari laporan: {key})" if key else "  (laporan tanpa ID)"))
    print("=" * 72)
    a = route(source, owners, key=key, minutes=args.minutes, text=text,
              baseline_days=args.baseline_days)
    print(render(a))

    print()
    print("=" * 72)
    print(f"MODE B  pakai LLM  (pelapor menulis bebas: {text.splitlines()[0]!r})")
    print("=" * 72)
    b, params = interpret.triage(source, owners, text, baseline_days=args.baseline_days)
    print(f"[extract/{params['engine']}] trx={params['trx_id']} window={params['minutes']}m")
    print(render(b))
    return 0


def cmd_funnel(args) -> int:
    """Which hop of the flow drops transactions, from ids alone."""
    source = build_source(args)
    hints = load_hints()
    stages = hints.get("flow") or []
    if not stages:
        raise SystemExit("hints.json belum punya daftar flow")
    events = source.fetch(Plan(minutes=args.minutes))
    rows = funnel(events, stages)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"Alur {args.minutes} menit terakhir (jumlah transaksi unik per tahap):")
    for r in rows:
        lost = f"  -{r['lost']}" if r["lost"] else ""
        print(f"  {r['job']:<20} {r['ids']:>5}{lost}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["compare", DEMO_REPORT, "--replay"]

    p = argparse.ArgumentParser(prog="sidik", description="Cari worker yang bikin transaksi gagal.")
    sub = p.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask", help="kasih ID transaksi")
    ask.add_argument("trx", nargs="?", help="ID transaksi, misal TRX2026102900123")
    ask.set_defaults(func=cmd_ask)

    tri = sub.add_parser("triage", help="kasih keluhan bebas, boleh tanpa ID")
    tri.add_argument("report", help="keluhan apa adanya dari chat")
    tri.add_argument("--image", help="screenshot struk atau pesan error (butuh tesseract)")
    tri.set_defaults(func=cmd_triage)

    cmp_ = sub.add_parser("compare", help="jalankan dua mode sekaligus")
    cmp_.add_argument("report")
    cmp_.add_argument("--trx")
    cmp_.add_argument("--image")
    cmp_.set_defaults(func=cmd_compare)

    fun = sub.add_parser("funnel", help="tahap mana yang kehilangan transaksi")
    fun.set_defaults(func=cmd_funnel)

    for parser in (ask, tri, cmp_):
        parser.add_argument("--minutes", type=int, default=120)
        parser.add_argument("--baseline-days", type=int, default=7)

    fun.add_argument("--minutes", type=int, default=60)

    for parser in (ask, tri, cmp_, fun):
        parser.add_argument("--json", action="store_true")
        parser.add_argument(
            "--replay",
            nargs="?",
            const=SAMPLE,
            default=None,
            help="baca dari file JSONL, bukan Loki",
        )

    args = p.parse_args(argv)
    if args.cmd == "ask" and not args.trx:
        p.error("ask butuh ID transaksi, atau pakai `triage` untuk keluhan bebas")
    _guard(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
