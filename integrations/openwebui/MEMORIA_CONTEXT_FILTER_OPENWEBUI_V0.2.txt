"""
MEMORIA Context Filter for Open WebUI V0.2

This is not a censorship filter.
It is a MEMORIA context injector:
current user message -> MEMORIA /context -> MEMORIA CONTEXT -> model prompt.

Policy:
- no secrets printed
- no chatlog scan
- no automatic memory writes
- only calls MEMORIA context server for the current user message
"""

from typing import Any, Optional
import json
import urllib.request

MEMORIA_ORIGIN_PREFIX = "[[MEMORIA_ORIGIN:"
MEMORIA_ORIGIN_SUFFIX = "]]"
USER_MESSAGE_ORIGIN = "user-message"
INTERNAL_REQUEST_ORIGIN = "internal-tool"


try:
    from pydantic import BaseModel, Field
except Exception:
    class BaseModel:
        pass

    def Field(default=None, description: str = ""):
        return default


class Filter:
    class Valves(BaseModel):
        enabled: bool = Field(
            default=True,
            description="Enable MEMORIA context injection",
        )
        memoria_context_url: str = Field(
            default="http://172.17.0.1:8765/context",
            description="MEMORIA context endpoint reachable from OpenWebUI container",
        )
        timeout_seconds: int = Field(
            default=30,
            description="Maximum wait time for the MEMORIA context endpoint",
        )
        model_profile: str = Field(
            default="gemma",
            description="MEMORIA retrieval/prompt model profile",
        )
        max_context_chars: int = Field(
            default=0,
            description=(
                "Optional additional context character limit; "
                "0 disables filter-side truncation"
            ),
        )
        attachment_probe_enabled: bool = Field(
            default=False,
            description=(
                "Temporarily log sanitized current-message "
                "attachment structure for transport testing"
            ),
        )

    def __init__(self):
        self.valves = self.Valves()

    def _last_user_message(self, messages: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        for message in reversed(messages):
            if message.get("role") == "user":
                return message
        return None

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            return "\n".join(parts).strip()

        return str(content or "").strip()

    def _extract_request_origin(
        self,
        text: str,
    ) -> tuple[str, str, bool]:
        value = str(text or "")
        first_line, separator, remainder = (
            value.partition("\n")
        )

        marked = (
            first_line.startswith(
                MEMORIA_ORIGIN_PREFIX
            )
            and first_line.endswith(
                MEMORIA_ORIGIN_SUFFIX
            )
        )

        if not marked:
            return (
                USER_MESSAGE_ORIGIN,
                value,
                False,
            )

        raw_origin = first_line[
            len(MEMORIA_ORIGIN_PREFIX):
            -len(MEMORIA_ORIGIN_SUFFIX)
        ].strip()

        origin = (
            USER_MESSAGE_ORIGIN
            if raw_origin == USER_MESSAGE_ORIGIN
            else INTERNAL_REQUEST_ORIGIN
        )

        clean_text = (
            remainder
            if separator
            else ""
        )

        return origin, clean_text, True

    def _replace_message_text(
        self,
        message: dict[str, Any],
        text: str,
    ) -> None:
        content = message.get("content")

        if isinstance(content, str):
            message["content"] = text
            return

        if not isinstance(content, list):
            return

        replaced = False

        for item in content:
            if not isinstance(item, dict):
                continue

            if item.get("type") != "text":
                continue

            if not replaced:
                item["text"] = text
                replaced = True
            else:
                item["text"] = ""

    def _fetch_context(
        self,
        text: str,
        origin: str = USER_MESSAGE_ORIGIN,
    ) -> str:
        payload = json.dumps(
            {
                "text": text,
                "origin": origin,
                "model_profile":
                    self.valves.model_profile,
                "include_history": False,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            self.valves.memoria_context_url,
            data=payload,
            headers={
                "Content-Type": "application/json"
            },
            method="POST",
        )

        with urllib.request.urlopen(
            request,
            timeout=self.valves.timeout_seconds,
        ) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        if not data.get("ok"):
            return ""

        if not data.get(
            "memory_context_found"
        ):
            return ""

        context = str(
            data.get("context_block") or ""
        ).strip()

        limit = max(
            0,
            int(self.valves.max_context_chars),
        )

        if limit == 0:
            return context

        return context[:limit]

    def _inject_system_context(self, messages: list[dict[str, Any]], context: str) -> None:
        injection = (
            "MEMORIA CONTEXT FOR THIS USER MESSAGE:\n"
            "Use this context when relevant. "
            "Do not invent details beyond the MEMORIA context.\n\n"
            f"{context}"
        )

        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = str(messages[0].get("content") or "") + "\n\n" + injection
        else:
            messages.insert(0, {"role": "system", "content": injection})

    def _attachment_probe_summary(
        self,
        metadata: Any,
    ) -> dict[str, Any]:
        source = (
            metadata
            if isinstance(metadata, dict)
            else {}
        )

        current_message = source.get(
            "user_message"
        )
        message_present = isinstance(
            current_message,
            dict,
        )

        files = (
            current_message.get("files")
            if message_present
            else None
        )
        files_list_present = isinstance(
            files,
            list,
        )
        file_list = (
            files
            if files_list_present
            else []
        )
        mappings = [
            item
            for item in file_list
            if isinstance(item, dict)
        ]

        return {
            "user_message_present":
                message_present,
            "files_list_present":
                files_list_present,
            "file_count":
                len(file_list),
            "id_present":
                any(
                    bool(item.get("id"))
                    for item in mappings
                ),
            "name_present":
                any(
                    bool(item.get("name"))
                    for item in mappings
                ),
            "content_type_present":
                any(
                    bool(
                        item.get("content_type")
                    )
                    for item in mappings
                ),
            "url_present":
                any(
                    bool(item.get("url"))
                    for item in mappings
                ),
            "chat_id_present":
                bool(source.get("chat_id")),
            "message_id_present":
                bool(
                    source.get("message_id")
                    or source.get(
                        "user_message_id"
                    )
                ),
        }

    def _emit_attachment_probe(
        self,
        metadata: Any,
    ) -> None:
        if not (
            self.valves
            .attachment_probe_enabled
        ):
            return

        summary = (
            self._attachment_probe_summary(
                metadata
            )
        )

        print(
            "MEMORIA_ATTACHMENT_PROBE_V0.1 "
            + json.dumps(
                summary,
                sort_keys=True,
                separators=(",", ":"),
            ),
            flush=True,
        )

    def inlet(
        self,
        body: dict[str, Any],
        __user__: Optional[dict[str, Any]] = None,
        __metadata__: Optional[
            dict[str, Any]
        ] = None,
    ) -> dict[str, Any]:
        if not self.valves.enabled:
            return body

        self._emit_attachment_probe(
            __metadata__
        )

        messages = body.get("messages")

        if not isinstance(messages, list):
            return body

        user_message = self._last_user_message(
            messages
        )

        if not user_message:
            return body

        text = self._content_to_text(
            user_message.get("content")
        )

        if not text:
            return body

        origin, clean_text, had_marker = (
            self._extract_request_origin(text)
        )

        if had_marker:
            self._replace_message_text(
                user_message,
                clean_text,
            )

        # Every marked non-user request is an
        # internal tool execution.
        #
        # The marker is removed before the model
        # receives the prompt, but /context and
        # Memory Auto are not called.
        if origin != USER_MESSAGE_ORIGIN:
            return body

        if not clean_text:
            return body

        try:
            # One positional argument preserves
            # compatibility with older tests and
            # monkeypatched filter instances.
            context = self._fetch_context(
                clean_text
            )
        except Exception:
            return body

        if context:
            self._inject_system_context(
                messages,
                context,
            )

        return body
