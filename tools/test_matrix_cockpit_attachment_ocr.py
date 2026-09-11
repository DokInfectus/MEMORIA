#!/usr/bin/env python3
from __future__ import annotations

import builtins
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
COCKPIT = TOOLS / "memoria_matrix_cockpit.py"

for entry in (ROOT, TOOLS):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    brain = base / "brain"
    inbox = base / "inbox"

    brain.mkdir()
    inbox.mkdir()

    attachment_root = brain / "attachments"
    candidate_root = brain / "candidates"
    memory_root = brain / "memory"

    candidate_root.mkdir()
    memory_root.mkdir()

    ledger_config = base / "source-ledger.json"

    ledger_config.write_text(
        json.dumps(
            {
                "schema_version":
                    "memory-source-ledger-config-v0.1",
                "enabled": True,
                "inbox": str(inbox),
                "poll_interval_seconds": 40,
                "min_poll_interval_seconds": 10,
                "policy": {
                    "explicit_inbox_only": True,
                    "private_directory_scan": False,
                    "candidate_created": False,
                    "durable_memory_written": False,
                },
            }
        ),
        encoding="utf-8",
    )

    image_path = inbox / "01-gandalf-kraki.png"

    image = Image.new(
        "RGB",
        (1500, 320),
        "white",
    )
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            64,
        )
    except OSError:
        font = ImageFont.load_default()

    draw.text(
        (40, 65),
        "GANDALF FISH BEWACHT KRAKI",
        fill="black",
        font=font,
    )
    draw.text(
        (40, 165),
        "KEINE FISCHSUPPE",
        fill="black",
        font=font,
    )

    image.save(image_path)
    hash_before = sha256_file(image_path)

    (inbox / "02-not-an-image.txt").write_text(
        "DARF NICHT ALS OCR-BILD ERSCHEINEN",
        encoding="utf-8",
    )

    (inbox / ".hidden.png").write_bytes(
        image_path.read_bytes()
    )

    (inbox / "subdir").mkdir()

    symlink = inbox / "link.png"

    try:
        symlink.symlink_to(image_path)
    except OSError:
        pass

    env_values = {
        "MEMORIA_MEMORY_SOURCE_LEDGER_CONFIG":
            str(ledger_config),
        "MEMORIA_ROOT": str(brain),
        "MEMORIA_ATTACHMENT_DIR":
            str(attachment_root),
        "MEMORIA_CANDIDATE_DIR":
            str(candidate_root),
        "MEMORIA_MEMORY_DIR":
            str(memory_root),
    }

    previous = {
        key: os.environ.get(key)
        for key in env_values
    }

    os.environ.update(env_values)

    spec = importlib.util.spec_from_file_location(
        "memoria_matrix_ocr_test",
        COCKPIT,
    )

    assert spec is not None
    assert spec.loader is not None

    cockpit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cockpit)

    source = COCKPIT.read_text(encoding="utf-8")

    required = [
        '"61": "Ausgewählte Bilder lesen / OCR"',
        'if action_key == "61":',
        "def run_attachment_ocr_cockpit",
        "memoria_local_ocr.py",
        "OCR-Ergebnisse gespeichert: nein",
        '"--json"',
        "OCR-Status:",
        "Erkannt:",
        "Unsicher:",
        "Kein Text:",
    ]

    for marker in required:
        assert marker in source, marker

    start = source.find(
        "def run_attachment_ocr_cockpit"
    )
    end = source.find(
        "\ndef run_attachment_import_cockpit",
        start,
    )

    assert start >= 0
    assert end > start

    section = source[start:end]

    for forbidden in [
        "Pfad zur Bild",
        ".unlink(",
        "write_text(",
        "os.replace(",
        "memoria_memory_candidate_store",
        "memoria_memory_promote",
    ]:
        assert forbidden not in section, forbidden

    answers = iter(["1"])
    original_input = builtins.input
    builtins.input = lambda _prompt="": next(answers)

    output = io.StringIO()

    try:
        with redirect_stdout(output):
            cockpit.run_attachment_ocr_cockpit()
    finally:
        builtins.input = original_input

        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    result = output.getvalue()
    upper = result.upper()

    assert "1 | 01-gandalf-kraki.png |" in result
    assert "02-not-an-image.txt" not in result
    assert ".hidden.png" not in result
    assert "link.png" not in result

    assert "GANDALF" in upper, result
    assert "KRAKI" in upper, result
    assert "FISCHSUPPE" in upper, result

    assert "OCR GELESEN: 1" in upper
    assert (
        "OCR-STATUS: RECOGNIZED"
        in upper
    ), result
    assert "ERKANNT:     1" in upper
    assert "UNSICHER:    0" in upper
    assert "KEIN TEXT:   0" in upper
    assert "FEHLER:      0" in upper
    assert "OCR-ERGEBNISSE GESPEICHERT: NEIN" in upper
    assert "CANDIDATES ERZEUGT: 0" in upper
    assert "DURABLE MEMORIES GESCHRIEBEN: 0" in upper

    assert sha256_file(image_path) == hash_before
    assert not attachment_root.exists()
    assert not list(candidate_root.glob("CAND-*.json"))
    assert not list(memory_root.rglob("MEM-*.json"))


print(
    "Matrix Cockpit Local OCR Status V0.2 Test OK"
)
