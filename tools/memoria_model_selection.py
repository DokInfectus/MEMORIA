#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from configure.model_catalog import format_model_selection, select_model_profile


RUNTIME_CONFIG = ROOT / "config" / "runtime.json"


def read_runtime_model() -> Optional[str]:
    if not RUNTIME_CONFIG.exists():
        return None

    try:
        data = json.loads(RUNTIME_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return None

    model = data.get("model")
    if model:
        return str(model)

    backend = data.get("backend")
    if isinstance(backend, dict) and backend.get("model"):
        return str(backend.get("model"))

    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Suggest MEMORIA prompt/context profiles for a local LLM model name."
    )
    parser.add_argument(
        "model_name",
        nargs="?",
        help="Model name to inspect. If omitted, config/runtime.json is used when possible.",
    )

    args = parser.parse_args()

    model_name = args.model_name or read_runtime_model() or ""

    selection = select_model_profile(model_name)
    print(format_model_selection(selection))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
