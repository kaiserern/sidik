"""Mode B: read a free-text complaint, pull out what the router needs, write the reply.

The LLM never decides which worker broke. It only turns prose into query parameters
and turns the router's verdict back into a sentence a human wants to read.
"""

from __future__ import annotations

import json
import os
import re

import httpx

from .route import Verdict, render, route

TRX_HINT = re.compile(r"\b(?:TRX|TRF|ORD|INV|REF)[A-Z0-9]{6,}\b", re.IGNORECASE)

EXTRACT_PROMPT = """You read one complaint from a bank employee and return JSON.

Return exactly: {"trx_id": string|null, "symptom": string|null, "minutes": integer}

Rules:
- trx_id only if the employee literally wrote a transaction, reference or order id.
  Never invent one. Use null when absent.
- symptom is a short English phrase describing the failure, or null.
- minutes is how far back to read logs. Default 120. Max 1440.
"""


class NoLLM(RuntimeError):
    pass


def _cfg() -> tuple[str, str, str]:
    base = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if not (base and key and model):
        raise NoLLM("LLM_BASE_URL / LLM_API_KEY / LLM_MODEL belum diisi")
    return base, key, model


def _chat(system: str, user: str, json_mode: bool = False) -> str:
    base, key, model = _cfg()
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    r = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=40,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def extract(report: str) -> dict:
    """LLM when configured, regex when not. Same shape, so the router does not care."""
    try:
        raw = _chat(EXTRACT_PROMPT, report, json_mode=True)
        data = json.loads(raw)
        minutes = int(data.get("minutes") or 120)
        return {
            "trx_id": (data.get("trx_id") or None),
            "symptom": data.get("symptom"),
            "minutes": max(5, min(minutes, 1440)),
            "engine": "llm",
        }
    except (NoLLM, httpx.HTTPError, ValueError, KeyError):
        match = TRX_HINT.search(report)
        return {
            "trx_id": match.group(0) if match else None,
            "symptom": None,
            "minutes": 120,
            "engine": "fallback",
        }


def narrate(report: str, verdict: Verdict) -> str:
    """Optional. Failure here must never cost the answer, so the template is the fallback."""
    body = render(verdict)
    try:
        return _chat(
            "You write a Teams reply for a bank ops channel. Indonesian, plain, no emoji, "
            "max 3 sentences, no greeting. Use only the facts given.",
            f"Complaint: {report}\n\nRouter output:\n{body}",
        ).strip()
    except (NoLLM, httpx.HTTPError, KeyError, IndexError):
        return body


def triage(source, owners: dict, report: str, **kw) -> tuple[Verdict, dict]:
    """The LLM only turns prose into query parameters. The router still decides."""
    params = extract(report)
    return route(source, owners, key=params["trx_id"], minutes=params["minutes"],
                 text=report, **kw), params
