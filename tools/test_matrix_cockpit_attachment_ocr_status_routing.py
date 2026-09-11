#!/usr/bin/env python3
from __future__ import annotations

import builtins
import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
COCKPIT = TOOLS / "memoria_matrix_cockpit.py"

for entry in (ROOT, TOOLS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

spec = importlib.util.spec_from_file_location(
    "memoria_matrix_ocr_routing_test",
    COCKPIT,
)

assert spec is not None
assert spec.loader is not None

cockpit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cockpit)

rows = [
    {
        "name": "01-recognized.png",
        "path": Path("/tmp/01-recognized.png"),
        "size_bytes": 100,
        "mime_type": "image/png",
    },
    {
        "name": "02-uncertain.png",
        "path": Path("/tmp/02-uncertain.png"),
        "size_bytes": 200,
        "mime_type": "image/png",
    },
    {
        "name": "03-no-text.png",
        "path": Path("/tmp/03-no-text.png"),
        "size_bytes": 300,
        "mime_type": "image/png",
    },
]

payloads = {
    "01-recognized.png": {
        "status": "recognized",
        "quality": {
            "word_count": 4,
            "average_confidence": 96.25,
        },
        "text": "GANDALF FISH BEWACHT KRAKI",
    },
    "02-uncertain.png": {
        "status": "uncertain",
        "quality": {
            "word_count": 3,
            "average_confidence": 42.50,
        },
        "text": "GANDALF F1SH ???",
    },
    "03-no-text.png": {
        "status": "no-text",
        "quality": {
            "word_count": 0,
            "average_confidence": None,
        },
        "text": "",
    },
}

calls: list[list[str]] = []


def fake_inbox_rows():
    return Path("/tmp/inbox"), rows


def fake_ocr_capture(arguments):
    calls.append(list(arguments))

    source_name = Path(arguments[1]).name

    return SimpleNamespace(
        returncode=0,
        stdout=json.dumps(
            payloads[source_name],
            ensure_ascii=False,
        ),
    )


original_input = builtins.input
original_rows = cockpit._attachment_inbox_rows
original_capture = cockpit._run_local_ocr_capture

builtins.input = lambda _prompt="": "a"
cockpit._attachment_inbox_rows = fake_inbox_rows
cockpit._run_local_ocr_capture = fake_ocr_capture

output = io.StringIO()

try:
    with redirect_stdout(output):
        cockpit.run_attachment_ocr_cockpit()
finally:
    builtins.input = original_input
    cockpit._attachment_inbox_rows = original_rows
    cockpit._run_local_ocr_capture = original_capture

result = output.getvalue()
upper = result.upper()

assert len(calls) == 3
assert all("--json" in call for call in calls)

assert "OCR-STATUS: RECOGNIZED" in upper
assert "OCR-STATUS: UNCERTAIN" in upper
assert "OCR-STATUS: NO-TEXT" in upper

assert "NICHT ZUVERLÄSSIG ERKENNEN" in upper
assert "CONFIDENCE DURCHSCHNITT: N/A" in upper

assert "OCR GELESEN: 3" in upper
assert "ERKANNT:     1" in upper
assert "UNSICHER:    1" in upper
assert "KEIN TEXT:   1" in upper
assert "FEHLER:      0" in upper

assert "OCR-ERGEBNISSE GESPEICHERT: NEIN" in upper
assert "CANDIDATES ERZEUGT: 0" in upper
assert "DURABLE MEMORIES GESCHRIEBEN: 0" in upper

print(
    "Matrix Cockpit OCR Status Routing "
    "V0.2 Test OK"
)
