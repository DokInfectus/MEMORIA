#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from adapter.openwebui import OpenWebUIAdapter
from adapter.exceptions import AdapterExecutionError
from prompt_engine.manager import PromptEngineManager


DEFAULT_SYSTEM_PROMPT = (
    "Du bist MEMORIA Open WebUI Bridge. "
    "Nutze den MEMORIA CONTEXT, wenn relevante Erinnerungen vorhanden sind. "
    "Antworte hilfreich, knapp und transparent."
)


def build_prompt(
    text: str,
    model_profile: str,
    system_prompt: str,
    include_history: bool,
    max_history_entries: int,
    max_history_characters: int,
) -> tuple[str, str]:
    engine = PromptEngineManager()

    # V0.1 safety: do not read any conversation history unless explicitly requested.
    if not include_history:
        engine.history.build_context = lambda: ""

    prompt = engine.generate(
        user_prompt=text,
        model=model_profile,
        system_prompt=system_prompt,
        max_history_entries=max_history_entries if include_history else 0,
        max_history_characters=max_history_characters if include_history else 0,
        include_history_metadata=False,
    )

    return prompt, engine.get_retrieval_query()


def memory_context_found(prompt: str) -> bool:
    return (
        "=== MEMORIA CONTEXT ===" in prompt
        and "Keine passende Erinnerung gefunden." not in prompt
    )


def run_ask(args: argparse.Namespace) -> dict[str, Any]:
    text = (args.text or "").strip()
    if not text:
        raise SystemExit("Missing --text")

    prompt, retrieval_query = build_prompt(
        text=text,
        model_profile=args.model_profile,
        system_prompt=args.system_prompt,
        include_history=args.include_history,
        max_history_entries=args.max_history_entries,
        max_history_characters=args.max_history_characters,
    )

    result: dict[str, Any] = {
        "version": "openwebui-memory-bridge-v0.1",
        "safety": {
            "token_printed": False,
            "private_openwebui_chats_read": False,
            "auto_memory_storage": False,
            "candidate_created": False,
            "durable_memory_written": False,
        },
        "auto_intake": {
            "requested": bool(args.auto_intake),
            "performed": False,
            "skipped_reason": "not requested" if not args.auto_intake else "",
            "result": None,
        },
        "retrieval_query": retrieval_query,
        "prompt_characters": len(prompt),
        "memory_context_found": memory_context_found(prompt),
        "sent_to_openwebui": False,
        "answer": "",
    }

    if args.auto_intake and args.dry_run:
        result["auto_intake"]["skipped_reason"] = "dry-run skips auto-intake side effects"
    elif args.auto_intake:
        from memoria_memory_auto import process_text

        intake_result = process_text(text)
        auto = intake_result.get("auto", {})
        candidate_created = bool(auto.get("candidate_created"))
        durable_written = bool(auto.get("durable_memory_written"))

        result["auto_intake"]["performed"] = True
        result["auto_intake"]["skipped_reason"] = ""
        result["auto_intake"]["result"] = intake_result
        result["safety"]["candidate_created"] = candidate_created
        result["safety"]["durable_memory_written"] = durable_written
        result["safety"]["auto_memory_storage"] = candidate_created or durable_written

    if args.dry_run:
        return result

    adapter = OpenWebUIAdapter(
        base_url=args.base_url,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )

    result["answer"] = adapter.send(prompt)
    result["sent_to_openwebui"] = True
    return result


def print_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        return

    print("MEMORIA OPEN WEBUI MEMORY BRIDGE V0.1")
    print("-" * 48)
    print("Token value is never printed.")
    print("No private Open WebUI chats are read.")
    if result["auto_intake"]["requested"]:
        print("Auto intake follows configured user policy.")
        print("Durable memory is only written if policy explicitly allows it.")
    else:
        print("No automatic memory intake/storage is performed.")
    print()
    print(f"Retrieval Query: {result['retrieval_query']}")
    print(f"Memory Context Found: {'yes' if result['memory_context_found'] else 'no'}")
    print(f"Sent To Open WebUI: {'yes' if result['sent_to_openwebui'] else 'no'}")
    print(f"Auto Intake Requested: {'yes' if result['auto_intake']['requested'] else 'no'}")
    print(f"Auto Intake Performed: {'yes' if result['auto_intake']['performed'] else 'no'}")
    if result["auto_intake"].get("skipped_reason"):
        print(f"Auto Intake Skipped: {result['auto_intake']['skipped_reason']}")
    print(f"Candidate Created: {'yes' if result['safety']['candidate_created'] else 'no'}")
    print(f"Durable Memory Written: {'yes' if result['safety']['durable_memory_written'] else 'no'}")
    print()
    if result.get("answer"):
        print("## Answer")
        print(result["answer"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA Open WebUI Memory Bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask")
    ask.add_argument("--text", required=True)
    ask.add_argument("--base-url", default="http://127.0.0.1:8080")
    ask.add_argument("--model-profile", default="gemma")
    ask.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    ask.add_argument("--temperature", type=float, default=0.2)
    ask.add_argument("--max-tokens", type=int, default=None)
    ask.add_argument("--include-history", action="store_true")
    ask.add_argument("--max-history-entries", type=int, default=3)
    ask.add_argument("--max-history-characters", type=int, default=4000)
    ask.add_argument("--dry-run", action="store_true")
    ask.add_argument("--auto-intake", action="store_true")
    ask.add_argument("--json", action="store_true")
    ask.set_defaults(func=lambda args: print_result(run_ask(args), args.json) or 0)

    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return int(args.func(args))
    except AdapterExecutionError as e:
        print(f"FAIL OpenWebUI Bridge: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
