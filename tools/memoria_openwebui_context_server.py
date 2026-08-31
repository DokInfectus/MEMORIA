#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"

for item in [str(PROJECT_ROOT), str(TOOLS_DIR)]:
    if item not in sys.path:
        sys.path.insert(0, item)

from memoria_openwebui_bridge import DEFAULT_SYSTEM_PROMPT, build_prompt, memory_context_found


VERSION = "openwebui-context-server-v0.2"

USER_MESSAGE_ORIGIN = "user-message"
INTERNAL_REQUEST_ORIGIN = "internal-tool"


def normalize_request_origin(
    value: str | None,
) -> str:
    if str(value or "").strip() == USER_MESSAGE_ORIGIN:
        return USER_MESSAGE_ORIGIN

    return INTERNAL_REQUEST_ORIGIN


DEFAULT_HOST = os.environ.get("MEMORIA_CONTEXT_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("MEMORIA_CONTEXT_PORT", "8765"))


def extract_memoria_context(prompt: str) -> str:
    marker = "=== MEMORIA CONTEXT ==="
    start = prompt.find(marker)

    if start < 0:
        return ""

    next_section = prompt.find("\n===", start + len(marker))

    if next_section >= 0:
        return prompt[start:next_section].strip()

    return prompt[start:].strip()



def run_memory_auto_policy(
    text: str,
    origin: str = "",
) -> dict:
    """Run Memory Auto only for explicit user-message origin."""
    normalized_origin = normalize_request_origin(origin)

    result = {
        "request_origin": normalized_origin,
        "candidate_requested": False,
        "candidate_created": False,
        "candidate_id": None,
        "candidate_reason": "not run",
        "durable_memory_written": False,
        "error": None,
    }

    if normalized_origin != USER_MESSAGE_ORIGIN:
        result["candidate_reason"] = (
            "blocked for non-user request origin"
        )
        return result

    if not str(text or "").strip():
        result["candidate_reason"] = "empty text"
        return result

    try:
        from memoria_memory_auto import process_text

        processed = process_text(text)
        auto = processed.get("auto", {}) if isinstance(processed, dict) else {}

        result["candidate_requested"] = bool(auto.get("candidate_requested"))
        result["candidate_created"] = bool(auto.get("candidate_created"))
        result["candidate_id"] = auto.get("candidate_id")
        result["candidate_reason"] = str(auto.get("candidate_reason") or "")
        result["durable_memory_written"] = bool(auto.get("durable_memory_written"))
        return result

    except Exception as exc:
        result["candidate_reason"] = "auto policy failed"
        result["error"] = str(exc)
        return result


def build_context_response(
    text: str,
    model_profile: str = "gemma",
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    include_history: bool = False,
    max_history_entries: int = 0,
    max_history_characters: int = 0,
    request_origin: str = "",
) -> dict[str, Any]:
    prompt, retrieval_query = build_prompt(
        text=text,
        model_profile=model_profile,
        system_prompt=system_prompt,
        include_history=include_history,
        max_history_entries=max_history_entries,
        max_history_characters=max_history_characters,
    )

    found = memory_context_found(prompt)
    context_block = extract_memoria_context(prompt) if found else ""
    if request_origin:
        memory_auto = run_memory_auto_policy(
            text,
            request_origin,
        )
    else:
        # Backward-compatible one-argument call for older
        # tests; default remains fail-closed internal-tool.
        memory_auto = run_memory_auto_policy(text)

    return {
        "version": VERSION,
        "request_origin": normalize_request_origin(
            request_origin
        ),
        "retrieval_query": retrieval_query,
        "memory_context_found": found,
        "context_block": context_block,
        "prompt_characters": len(prompt),
        "safety": {
            "token_printed": False,
            "private_openwebui_chats_read": False,
            "auto_memory_storage": bool(memory_auto.get("candidate_requested")),
            "candidate_created": bool(memory_auto.get("candidate_created")),
            "candidate_id": memory_auto.get("candidate_id"),
            "candidate_reason": memory_auto.get("candidate_reason"),
            "durable_memory_written": bool(memory_auto.get("durable_memory_written")),
        },
    }


class ContextHandler(BaseHTTPRequestHandler):
    server_version = "MEMORIAOpenWebUIContext/0.2"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep logs quiet; no private prompt text in access logs.
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"ok": True, "version": VERSION})
            return

        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/context":
            self._send_json(404, {"ok": False, "error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8") or "{}")
            text = str(data.get("text") or "").strip()

            if not text:
                self._send_json(400, {"ok": False, "error": "missing text"})
                return

            result = build_context_response(
                text=text,
                model_profile=str(data.get("model_profile") or "gemma"),
                system_prompt=str(data.get("system_prompt") or DEFAULT_SYSTEM_PROMPT),
                include_history=bool(data.get("include_history", False)),
                max_history_entries=int(data.get("max_history_entries", 0)),
                max_history_characters=int(data.get("max_history_characters", 0)),
                request_origin=str(
                    data.get("origin") or ""
                ),
            )
            result["ok"] = True
            self._send_json(200, result)
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})


def command_context(args: argparse.Namespace) -> int:
    result = build_context_response(
        text=args.text,
        model_profile=args.model_profile,
        system_prompt=args.system_prompt,
        include_history=args.include_history,
        max_history_entries=args.max_history_entries,
        max_history_characters=args.max_history_characters,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("MEMORIA OPENWEBUI CONTEXT SERVER V0.1")
        print("-" * 56)
        print("No secrets printed. No private OpenWebUI chats read. No writes.")
        print(f"Retrieval Query: {result['retrieval_query']}")
        print(f"Memory Context Found: {'yes' if result['memory_context_found'] else 'no'}")
        print()
        print(result["context_block"] or "No context block.")

    return 0


def command_serve(args: argparse.Namespace) -> int:
    server = ThreadingHTTPServer((args.host, args.port), ContextHandler)
    print("MEMORIA OPENWEBUI CONTEXT SERVER V0.1")
    print("-" * 56)
    print(f"Listening on http://{args.host}:{args.port}")
    print("POST /context with JSON: {\"text\": \"...\"}")
    print("Policy: local context only, no secrets printed, no writes.")
    server.serve_forever()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MEMORIA OpenWebUI context endpoint")
    sub = parser.add_subparsers(dest="command", required=True)

    context = sub.add_parser("context")
    context.add_argument("--text", required=True)
    context.add_argument("--model-profile", default="gemma")
    context.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    context.add_argument("--include-history", action="store_true")
    context.add_argument("--max-history-entries", type=int, default=0)
    context.add_argument("--max-history-characters", type=int, default=0)
    context.add_argument("--json", action="store_true")
    context.set_defaults(func=command_context)

    serve = sub.add_parser("serve")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.set_defaults(func=command_serve)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
