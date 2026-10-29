"""What each complaint sounds like, and the order the payment flow runs in.

Two small tables, both edited by a human. Nothing here is a regex zoo: three
buttons on the Teams card cover most reports, and the keyword lists are only
there to catch the same three things typed as free text.
"""

from __future__ import annotations

import json
import os

HINTS_PATH = os.path.join(os.path.dirname(__file__), "hints.json")


def load_hints(path: str = HINTS_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def symptom_key(hints: dict, text: str) -> str | None:
    """Map free text onto one of the known symptoms, or None."""
    low = (text or "").lower()
    for key, row in hints.get("symptoms", {}).items():
        if any(word in low for word in row.get("keyword", [])):
            return key
    return None
