#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "memoria_local_ocr.py"

spec = importlib.util.spec_from_file_location(
    "memoria_local_ocr_test_module",
    TOOL,
)

assert spec is not None
assert spec.loader is not None

ocr_module = importlib.util.module_from_spec(
    spec
)
spec.loader.exec_module(ocr_module)


def run(args: list[str]):
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


source_text = TOOL.read_text(encoding="utf-8")

required_markers = [
    "memoria-local-ocr-v0.2",
    "explicit_file_only",
    "private_directory_scan",
    "candidate_created",
    "durable_memory_written",
    "ocr_result_persisted",
    "subprocess.run(",
    '"stdout"',
    "--psm",
    '"tsv"',
    "parse_tesseract_tsv",
    "classify_ocr_quality",
    '"recognized"',
    '"uncertain"',
    '"no-text"',
]

for marker in required_markers:
    assert marker in source_text, marker

for forbidden in [
    "shell=True",
    "memoria_memory_candidate_store",
    "memoria_memory_promote",
    "memoria_memory_store",
    "write_text(",
    ".unlink(",
    "os.replace(",
    "rglob(",
    "os.walk",
]:
    assert forbidden not in source_text, forbidden


recognized_quality = (
    ocr_module.classify_ocr_quality(
        "GANDALF FISH BEWACHT KRAKI",
        [
            {
                "text": "GANDALF",
                "confidence": 96.0,
            },
            {
                "text": "FISH",
                "confidence": 94.0,
            },
            {
                "text": "BEWACHT",
                "confidence": 97.0,
            },
            {
                "text": "KRAKI",
                "confidence": 95.0,
            },
        ],
    )
)

assert (
    recognized_quality["status"]
    == "recognized"
)

uncertain_quality = (
    ocr_module.classify_ocr_quality(
        "GANDALF F1SH ???",
        [
            {
                "text": "GANDALF",
                "confidence": 96.0,
            },
            {
                "text": "F1SH",
                "confidence": 32.0,
            },
            {
                "text": "???",
                "confidence": 0.0,
            },
        ],
    )
)

assert (
    uncertain_quality["status"]
    == "uncertain"
)

no_text_quality = (
    ocr_module.classify_ocr_quality(
        "",
        [],
    )
)

assert (
    no_text_quality["status"]
    == "no-text"
)


with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    image_path = base / "kraki-lesebrille.png"

    image = Image.new(
        "RGB",
        (1400, 320),
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
        (40, 60),
        "GANDALF FISH BEWACHT KRAKI",
        fill="black",
        font=font,
    )
    draw.text(
        (40, 160),
        "KEINE FISCHSUPPE",
        fill="black",
        font=font,
    )

    image.save(image_path)

    hash_before = sha256_file(image_path)

    result = run(
        [
            "read",
            str(image_path),
            "--language",
            "deu+eng",
            "--psm",
            "6",
        ]
    )

    assert result.returncode == 0, result.stdout

    upper = result.stdout.upper()

    assert "GANDALF" in upper, result.stdout
    assert "KRAKI" in upper, result.stdout
    assert "FISCHSUPPE" in upper, result.stdout
    assert (
        "OCR-STATUS: RECOGNIZED"
        in upper
    ), result.stdout

    assert "QUELLDATEI VERÄNDERT: NEIN" in upper
    assert "OCR-ERGEBNIS GESPEICHERT: NEIN" in upper
    assert "CANDIDATE ERZEUGT: NEIN" in upper
    assert "DURABLE MEMORY GESCHRIEBEN: NEIN" in upper

    assert sha256_file(image_path) == hash_before

    json_result = run(
        [
            "read",
            str(image_path),
            "--json",
        ]
    )

    assert json_result.returncode == 0

    json_data = json.loads(
        json_result.stdout
    )

    assert (
        json_data["schema_version"]
        == "memoria-local-ocr-v0.2"
    )
    assert json_data["status"] == "recognized"
    assert (
        json_data["quality"]["word_count"]
        >= 3
    )
    assert (
        json_data["quality"][
            "average_confidence"
        ]
        is not None
    )
    assert (
        json_data["policy"][
            "candidate_created"
        ]
        is False
    )
    assert (
        json_data["policy"][
            "durable_memory_written"
        ]
        is False
    )
    assert (
        json_data["policy"][
            "ocr_result_persisted"
        ]
        is False
    )

    blank_image = base / "blank.png"

    Image.new(
        "RGB",
        (900, 420),
        "white",
    ).save(blank_image)

    blank_result = run(
        [
            "read",
            str(blank_image),
            "--json",
        ]
    )

    assert blank_result.returncode == 0

    blank_data = json.loads(
        blank_result.stdout
    )

    assert blank_data["status"] == "no-text"
    assert (
        blank_data["quality"]["word_count"]
        == 0
    )

    text_file = base / "not-an-image.txt"
    text_file.write_text(
        "GANDALF",
        encoding="utf-8",
    )

    unsupported = run(
        [
            "read",
            str(text_file),
        ]
    )

    assert unsupported.returncode == 2
    assert "unsupported OCR image type" in unsupported.stdout

    empty = base / "empty.png"
    empty.write_bytes(b"")

    empty_result = run(
        [
            "read",
            str(empty),
        ]
    )

    assert empty_result.returncode == 2
    assert "empty files" in empty_result.stdout

    symlink = base / "link.png"

    try:
        symlink.symlink_to(image_path)

        link_result = run(
            [
                "read",
                str(symlink),
            ]
        )

        assert link_result.returncode == 2
        assert "symbolic links" in link_result.stdout
    except OSError:
        pass

    remaining = sorted(
        item.name
        for item in base.iterdir()
    )

    assert "kraki-lesebrille.png" in remaining
    assert not any(
        name.endswith(".txt.txt")
        for name in remaining
    )


print("Local OCR Status V0.2 Test OK")
