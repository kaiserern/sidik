"""Measure what one complaint actually costs, against a live OpenAI-compatible API.

Run it with the same env vars the bot uses:

    LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=deepseek-v4.1-flash-1017 \
    python tools/cost.py --complaints 200 --in-price 0.15 --out-price 0.60

It prints the token usage of the two calls a complaint makes (extract + narrate)
and the monthly bill at your volume. Numbers come from the API's own `usage`
field, not from a tokenizer guess.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from sidik import interpret  # noqa: E402
from sidik.route import load_owners, route  # noqa: E402
from sidik.source import ReplaySource  # noqa: E402

REPORT = ("nasabah komplain transfer Rp1.250.000 jam 14:00 dari BCA ke rekening tujuan "
          "belum masuk padahal saldo sudah kepotong, tolong cek")
SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample.jsonl")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--complaints", type=int, default=200, help="laporan per hari")
    p.add_argument("--in-price", type=float, default=0.15, help="USD per 1 juta token masuk")
    p.add_argument("--out-price", type=float, default=0.60, help="USD per 1 juta token keluar")
    p.add_argument("--model", default=os.environ.get("LLM_MODEL", ""))
    args = p.parse_args()

    usage, real_post = [], httpx.post

    def spy(url, **kw):
        r = real_post(url, **kw)
        usage.append(r.json().get("usage") or {})
        return r

    httpx.post = spy
    try:
        params = interpret.extract(REPORT)
        verdict = route(ReplaySource(SAMPLE), load_owners(), key=params["trx_id"],
                        minutes=params["minutes"], text=REPORT)
        interpret.narrate(REPORT, verdict)
    finally:
        httpx.post = real_post

    if not usage or not any(u.get("prompt_tokens") for u in usage):
        # No usage means the model never answered: a silent regex fallback would
        # report a fake $0.00 bill.
        print("Model tidak membalas dengan blok usage. Cek LLM_BASE_URL / LLM_API_KEY / LLM_MODEL.")
        print("usage mentah:", json.dumps(usage))
        return 1

    tin = sum(u.get("prompt_tokens", 0) for u in usage)
    tout = sum(u.get("completion_tokens", 0) for u in usage)
    per = tin / 1e6 * args.in_price + tout / 1e6 * args.out_price
    print(f"model       : {args.model or '(dari env)'}  (extract engine: {params['engine']})")
    print(f"panggilan   : {len(usage)} per laporan (extract + narasi)")
    print(f"token       : {tin} masuk, {tout} keluar -> {tin + tout} total")
    print(f"per laporan : ${per:.5f}")
    print(f"{args.complaints}/hari : ${per * args.complaints:.4f}/hari, "
          f"${per * args.complaints * 30:.2f}/bulan")
    print("usage mentah:", json.dumps(usage))
    return 0


if __name__ == "__main__":
    sys.exit(main())
