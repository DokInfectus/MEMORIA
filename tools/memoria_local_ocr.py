#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import statistics
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".webp",
}

SUPPORTED_LANGUAGES = {
    "deu",
    "eng",
    "deu+eng",
    "eng+deu",
}


def validate_image(raw_path: str) -> Path:
    source = Path(raw_path).expanduser()

    if source.is_symlink():
        raise ValueError(
            "symbolic links are not accepted for OCR"
        )

    source = source.resolve()

    if not source.exists():
        raise FileNotFoundError(source)

    if not source.is_file():
        raise ValueError(
            "OCR source is not a regular file"
        )

    if source.stat().st_size <= 0:
        raise ValueError(
            "empty files are not accepted for OCR"
        )

    if source.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(
            "unsupported OCR image type: "
            f"{source.suffix.lower() or '(none)'}"
        )

    try:
        with Image.open(source) as image:
            image.verify()
    except (
        OSError,
        UnidentifiedImageError,
    ) as exc:
        raise ValueError(
            f"invalid or unreadable image: {exc}"
        ) from exc

    return source


def normalize_text(value: str) -> str:
    lines = [
        line.rstrip()
        for line in str(value or "").replace(
            "\r\n",
            "\n",
        ).replace(
            "\r",
            "\n",
        ).splitlines()
    ]

    while lines and not lines[0].strip():
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


def parse_tesseract_tsv(
    value: str,
) -> list[dict[str, Any]]:
    reader = csv.DictReader(
        io.StringIO(str(value or "")),
        delimiter="\t",
    )

    required_columns = {
        "level",
        "conf",
        "text",
    }

    fieldnames = set(reader.fieldnames or [])

    if not required_columns.issubset(fieldnames):
        raise RuntimeError(
            "tesseract TSV output is missing "
            "required columns"
        )

    words: list[dict[str, Any]] = []

    for row in reader:
        word_text = str(
            row.get("text") or ""
        ).strip()

        if not word_text:
            continue

        try:
            confidence = float(
                row.get("conf") or "-1"
            )
        except ValueError:
            continue

        if confidence < 0:
            continue

        words.append(
            {
                "text": word_text,
                "confidence": round(
                    confidence,
                    2,
                ),
            }
        )

    return words


def classify_ocr_quality(
    text: str,
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_text = normalize_text(text)

    confidences = [
        float(word["confidence"])
        for word in words
        if "confidence" in word
    ]

    if not normalized_text or not confidences:
        return {
            "status": "no-text",
            "status_reason": (
                "no valid OCR words were detected"
            ),
            "word_count": 0,
            "average_confidence": None,
            "median_confidence": None,
            "minimum_confidence": None,
            "maximum_confidence": None,
            "low_confidence_words": 0,
            "very_low_confidence_words": 0,
            "low_confidence_ratio": 0.0,
            "very_low_confidence_ratio": 0.0,
        }

    word_count = len(confidences)
    average_confidence = statistics.fmean(
        confidences
    )
    median_confidence = statistics.median(
        confidences
    )

    low_confidence_words = sum(
        confidence < 50
        for confidence in confidences
    )
    very_low_confidence_words = sum(
        confidence < 20
        for confidence in confidences
    )

    low_confidence_ratio = (
        low_confidence_words / word_count
    )
    very_low_confidence_ratio = (
        very_low_confidence_words / word_count
    )

    if word_count == 1:
        token = str(
            words[0].get("text") or ""
        )
        alphanumeric_count = sum(
            character.isalnum()
            for character in token
        )

        recognized = (
            average_confidence >= 95
            and alphanumeric_count >= 4
        )
    else:
        recognized = (
            average_confidence >= 80
            and median_confidence >= 85
            and low_confidence_ratio <= 0.20
            and very_low_confidence_ratio <= 0.05
        )

    if recognized:
        status = "recognized"
        status_reason = (
            "OCR confidence passed the "
            "conservative recognition threshold"
        )
    else:
        status = "uncertain"
        status_reason = (
            "OCR confidence did not pass the "
            "conservative recognition threshold"
        )

    return {
        "status": status,
        "status_reason": status_reason,
        "word_count": word_count,
        "average_confidence": round(
            average_confidence,
            2,
        ),
        "median_confidence": round(
            median_confidence,
            2,
        ),
        "minimum_confidence": round(
            min(confidences),
            2,
        ),
        "maximum_confidence": round(
            max(confidences),
            2,
        ),
        "low_confidence_words":
            low_confidence_words,
        "very_low_confidence_words":
            very_low_confidence_words,
        "low_confidence_ratio": round(
            low_confidence_ratio,
            4,
        ),
        "very_low_confidence_ratio": round(
            very_low_confidence_ratio,
            4,
        ),
    }


def run_tesseract(
    source: Path,
    *,
    language: str,
    psm: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    executable = shutil.which("tesseract")

    if not executable:
        raise RuntimeError(
            "tesseract executable was not found"
        )

    def execute(
        output_format: str | None = None,
    ) -> str:
        command = [
            executable,
            str(source),
            "stdout",
            "-l",
            language,
            "--psm",
            str(psm),
        ]

        if output_format:
            command.append(output_format)

        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )

        if completed.returncode != 0:
            error = normalize_text(
                completed.stderr
            )

            raise RuntimeError(
                "tesseract failed with code "
                f"{completed.returncode}: "
                f"{error or 'no error text'}"
            )

        return completed.stdout

    text = normalize_text(execute())
    tsv = execute("tsv")
    words = parse_tesseract_tsv(tsv)

    quality = classify_ocr_quality(
        text,
        words,
    )

    return {
        "schema_version":
            "memoria-local-ocr-v0.2",
        "source_name": source.name,
        "source_size_bytes":
            source.stat().st_size,
        "language": language,
        "page_segmentation_mode": psm,
        "status": quality["status"],
        "status_reason":
            quality["status_reason"],
        "quality": quality,
        "text": text,
        "policy": {
            "explicit_file_only": True,
            "private_directory_scan": False,
            "source_modified": False,
            "candidate_created": False,
            "durable_memory_written": False,
            "ocr_result_persisted": False,
        },
    }


def command_read(args: argparse.Namespace) -> int:
    if args.language not in SUPPORTED_LANGUAGES:
        raise ValueError(
            "unsupported OCR language selection: "
            f"{args.language}"
        )

    if args.psm < 0 or args.psm > 13:
        raise ValueError(
            "page segmentation mode must be between 0 and 13"
        )

    source = validate_image(args.image)

    result = run_tesseract(
        source,
        language=args.language,
        psm=args.psm,
        timeout_seconds=args.timeout,
    )

    if args.json:
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print("## MEMORIA LOCAL OCR V0.2")
    print("-" * 60)
    print(f"Datei: {result['source_name']}")
    print(f"Sprache: {result['language']}")
    print(f"PSM: {result['page_segmentation_mode']}")
    print(f"OCR-Status: {result['status']}")

    quality = result["quality"]

    print(
        "OCR-Wörter: "
        f"{quality['word_count']}"
    )

    average = quality[
        "average_confidence"
    ]

    if average is None:
        print("Confidence Durchschnitt: n/a")
    else:
        print(
            "Confidence Durchschnitt: "
            f"{average:.2f}"
        )

    if result["status"] == "recognized":
        print(
            "OK Text mit ausreichender "
            "OCR-Qualität erkannt."
        )
    elif result["status"] == "uncertain":
        print(
            "WARN Ich konnte den Text auf "
            "diesem Bild nicht zuverlässig "
            "erkennen. Bitte Ergebnis prüfen."
        )
    else:
        print("INFO Kein Text erkannt.")

    print()
    print("Erkannter Text:")
    print("-" * 60)

    if result["text"]:
        print(result["text"])
    else:
        print("INFO Kein Text erkannt.")

    print("-" * 60)
    print("Quelldatei verändert: nein")
    print("OCR-Ergebnis gespeichert: nein")
    print("Candidate erzeugt: nein")
    print("Durable Memory geschrieben: nein")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Local read-only OCR for one explicitly "
            "selected image"
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    read = subparsers.add_parser(
        "read",
        help=(
            "Read visible text from one explicitly "
            "selected local image"
        ),
    )
    read.add_argument("image")
    read.add_argument(
        "--language",
        default="deu+eng",
        choices=sorted(SUPPORTED_LANGUAGES),
    )
    read.add_argument(
        "--psm",
        type=int,
        default=6,
    )
    read.add_argument(
        "--timeout",
        type=int,
        default=120,
    )
    read.add_argument(
        "--json",
        action="store_true",
    )
    read.set_defaults(func=command_read)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        return int(args.func(args))
    except subprocess.TimeoutExpired:
        print("FAIL Local OCR: Zeitlimit überschritten")
        return 24
    except FileNotFoundError as exc:
        print(f"FAIL Local OCR: Datei nicht gefunden: {exc}")
        return 2
    except (
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"FAIL Local OCR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
