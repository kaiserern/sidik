"""Read the text off a screenshot, but only if tesseract is already on the box.

No Python dependency: this shells out to the same binary a human would use.
"""

from __future__ import annotations

import shutil
import subprocess


class NoOCR(RuntimeError):
    pass


def read_image(path: str) -> str:
    if not shutil.which("tesseract"):
        raise NoOCR("tesseract belum terpasang: sudo apt install tesseract-ocr")
    for lang in ("ind+eng", "eng"):
        out = subprocess.run(
            ["tesseract", path, "-", "-l", lang, "--psm", "6"],
            capture_output=True, text=True, timeout=90,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout
    raise NoOCR("tidak ada teks yang terbaca dari gambar itu")
