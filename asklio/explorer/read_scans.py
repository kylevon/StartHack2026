#!/usr/bin/env python3
# pyright: basic, reportOptionalMemberAccess=false, reportArgumentType=false
"""Read scanned documents with a vision model (Gemini on Vertex AI) and cache the result.

Usage:
    python3 explorer/read_scans.py            # read every scan that is not cached yet
    python3 explorer/read_scans.py --force    # re-read everything

What it reads:
  - delivery-note scans (images under soony/receiving/)  -> structured lines, handwriting, stamps
  - PDFs without a text layer (e.g. scanned contracts)   -> full transcription + key terms

Results go to data/extracted/<sha256>.json, keyed by file content, so a new drop
only costs calls for new or changed files. build.py picks the cache up.

Auth: uses `gcloud auth print-access-token`. Project from GCP_PROJECT or the
active gcloud config. Stdlib only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "soony-data"
CACHE = ROOT / "data" / "extracted"
LOCATION = os.environ.get("GCP_LOCATION", "europe-west4")
MODEL = os.environ.get("SCAN_MODEL", "gemini-2.5-pro")
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf"}

DELIVERY_NOTE_PROMPT = """You are reading a scanned delivery note received at a warehouse.
Transcribe exactly what is on the paper.

Quantities: copy each quantity as TEXT exactly as it appears, character for character,
including any dots, commas or spaces ("14.000", "68 000", "5,000"). Do not convert it to a number.
- printed_quantity_text: the machine-printed quantity.
- final_quantity_text: the quantity the paper states after any pen correction. Equal to the
  printed text when nothing was corrected.

Handwriting: a handwritten correction means printed text is struck through or overwritten WITH A PEN
and a replacement is written by hand. Report it only when you can see both.
Signatures and handwritten package counts are normal and are not corrections.

Stamps: suppliers often put a round company seal over the table, and the warehouse adds a
rectangular "RECEIVED" stamp. Text that belongs to a stamp is NOT handwriting and NOT a correction.
List stamps under `stamps`, and if a stamp hides a value say so in `anomalies`.

Do not guess: if something is unreadable, say so in `anomalies`. Leave fields empty when the paper
does not have them. Write remarks and anomalies in English; keep the original text in `remarks_original`."""

DELIVERY_NOTE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "document_type": {"type": "STRING"},
        "document_number": {"type": "STRING"},
        "document_date": {"type": "STRING", "description": "ISO date YYYY-MM-DD"},
        "supplier_name": {"type": "STRING"},
        "po_number": {"type": "STRING"},
        "language": {"type": "STRING"},
        "lines": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "material_id": {"type": "STRING"},
                "description": {"type": "STRING"},
                "printed_quantity_text": {"type": "STRING"},
                "final_quantity_text": {"type": "STRING"},
                "handwritten_correction": {"type": "BOOLEAN"},
                "corrected_field": {"type": "STRING", "description": "quantity, unit, part number, or empty"},
                "correction_note": {"type": "STRING", "description": "what was changed by hand, if anything"},
                "uom": {"type": "STRING"},
                "packages": {"type": "INTEGER"},
            },
            "required": ["material_id", "printed_quantity_text", "final_quantity_text", "handwritten_correction"],
        }},
        "gross_weight_kg": {"type": "NUMBER"},
        "carrier": {"type": "STRING"},
        "remarks": {"type": "STRING", "description": "printed or handwritten remarks, in English"},
        "remarks_original": {"type": "STRING"},
        "handwritten_notes": {"type": "ARRAY", "items": {"type": "STRING"},
                              "description": "pen-written notes other than the signature and package counts"},
        "stamps": {"type": "ARRAY", "items": {"type": "STRING"}},
        "received_by": {"type": "STRING"},
        "received_stamp_date": {"type": "STRING", "description": "ISO date YYYY-MM-DD"},
        "anomalies": {"type": "ARRAY", "items": {"type": "STRING"},
                      "description": "anything unusual: corrections, damage notes, mismatches, unreadable parts"},
    },
    "required": ["document_number", "lines", "anomalies"],
}

DOCUMENT_PROMPT = """You are reading a scanned business document (for example a supply contract).
1. Transcribe the full text faithfully in its original language(s), page by page.
2. Summarise in English the terms a procurement team needs in a supply crisis.
Only report what the document says. If a term is not in the document, leave it empty.
Quote clause numbers where the document has them."""

DOCUMENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "document_type": {"type": "STRING"},
        "title": {"type": "STRING"},
        "parties": {"type": "ARRAY", "items": {"type": "STRING"}},
        "language": {"type": "STRING"},
        "effective_date": {"type": "STRING"},
        "term_and_termination": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "key_terms": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "topic": {"type": "STRING", "description": "e.g. lead time, express orders, late delivery penalty, "
                          "price adjustment, quality and acceptance, liability, force majeure, payment and bank details, "
                          "exclusivity, incoterms"},
                "clause": {"type": "STRING"},
                "what_it_says": {"type": "STRING"},
            },
            "required": ["topic", "what_it_says"],
        }},
        "handwritten_notes": {"type": "ARRAY", "items": {"type": "STRING"}},
        "anomalies": {"type": "ARRAY", "items": {"type": "STRING"}},
        "full_text": {"type": "STRING"},
    },
    "required": ["document_type", "summary", "key_terms", "full_text"],
}


def sh(*cmd: str) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


class Vertex:
    def __init__(self) -> None:
        if not shutil.which("gcloud"):
            sys.exit("gcloud not found: install the Google Cloud SDK and run `gcloud auth login`.")
        self.project = os.environ.get("GCP_PROJECT") or sh("gcloud", "config", "get-value", "project")
        self.token, self.token_at = "", 0.0

    def _token(self) -> str:
        if time.time() - self.token_at > 1800:
            self.token, self.token_at = sh("gcloud", "auth", "print-access-token"), time.time()
        return self.token

    def extract(self, path: Path, prompt: str, schema: dict) -> dict:
        return self.generate([
            {"inlineData": {"mimeType": MIME[path.suffix.lower()], "data": base64.b64encode(path.read_bytes()).decode()}},
            {"text": prompt}], schema)

    def ask(self, prompt: str, schema: dict) -> dict:
        return self.generate([{"text": prompt}], schema)

    def generate(self, parts: list, schema: dict) -> dict:
        url = (f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{self.project}/locations/{LOCATION}"
               f"/publishers/google/models/{MODEL}:generateContent")
        body = json.dumps({
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": schema,
                                 "maxOutputTokens": 32768},
        }).encode()
        last = None
        for attempt in range(5):
            req = urllib.request.Request(url, data=body, method="POST", headers={
                "Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    out = json.load(r)
                text = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
                return json.loads(text)
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}: {e.read().decode()[:300]}"
                if e.code not in (429, 500, 503):
                    break
            except Exception as e:  # truncated JSON, timeouts
                last = repr(e)
            time.sleep(4 * (attempt + 1))
        raise RuntimeError(last)


def has_text_layer(pdf: Path) -> bool:
    if not shutil.which("pdftotext"):
        return False
    return bool(subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout.strip())


def targets() -> list[tuple[Path, str]]:
    out = []
    for f in sorted(DATA.rglob("*")):
        ext = f.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png"):
            out.append((f, "delivery_note"))
        elif ext == ".pdf" and not has_text_layer(f):
            out.append((f, "document"))
    return out


def cache_path(f: Path) -> Path:
    return CACHE / (hashlib.sha256(f.read_bytes()).hexdigest() + ".json")


def main() -> None:
    force = "--force" in sys.argv
    CACHE.mkdir(parents=True, exist_ok=True)
    todo = [(f, kind) for f, kind in targets() if force or not cache_path(f).exists()]
    total = len(targets())
    print(f"{total} scanned files, {len(todo)} to read with {MODEL} ({LOCATION})")
    if not todo:
        return
    vx = Vertex()

    def work(item: tuple[Path, str]) -> str:
        f, kind = item
        try:
            prompt, schema = (DELIVERY_NOTE_PROMPT, DELIVERY_NOTE_SCHEMA) if kind == "delivery_note" \
                else (DOCUMENT_PROMPT, DOCUMENT_SCHEMA)
            data = vx.extract(f, prompt, schema)
            cache_path(f).write_text(json.dumps({
                "path": f.relative_to(ROOT).as_posix(), "kind": kind, "model": MODEL,
                "read_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "data": data}, ensure_ascii=False, indent=1), encoding="utf-8")
            return f"ok    {f.name}"
        except Exception as e:
            return f"FAIL  {f.name}: {e}"

    failed = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for line in pool.map(work, todo):
            failed += line.startswith("FAIL")
            print(line, flush=True)
    print(f"done: {len(todo) - failed} read, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
