#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from prompt_engine.manager import PromptEngineManager

BASE_URL = "http://127.0.0.1:8080"
DEFAULT_API_KEY_FILE = PROJECT_ROOT / "config" / "secrets" / "openwebui_api_key"


def read_api_key_file(path: Path) -> str:
    if not path.exists():
        return ""

    mode = path.stat().st_mode
    if mode & 0o077:
        raise SystemExit(
            f"API key file permissions are too open: {path}. Use chmod 600."
        )

    return path.read_text(encoding="utf-8").strip().strip('"').strip("'")


def load_api_key():
    env_key = os.environ.get("MEMORIA_OPENWEBUI_API_KEY", "").strip().strip('"').strip("'")
    if env_key:
        return env_key, "environment"

    env_file = os.environ.get("MEMORIA_OPENWEBUI_API_KEY_FILE", "").strip()
    if env_file:
        key = read_api_key_file(Path(env_file).expanduser())
        if key:
            return key, "env-file"

    key = read_api_key_file(DEFAULT_API_KEY_FILE)
    if key:
        return key, "default-file"

    return "", "not-set"


TOKEN, TOKEN_SOURCE = load_api_key()

print("MEMORIA OPEN WEBUI MEMORY LIVE TEST V0.1")
print("-" * 40)
print(f"Base URL: {BASE_URL}")
print(f"API Token: {'present' if TOKEN else 'not set'}")
print(f"API Key Source: {TOKEN_SOURCE}")
print("Token value is never printed.")
print()

if not TOKEN:
    raise SystemExit("Missing MEMORIA_OPENWEBUI_API_KEY")

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

def get_json(endpoint):
    req = urllib.request.Request(
        BASE_URL + endpoint,
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))

def post_json(endpoint, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + endpoint,
        data=data,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))

models_body = get_json("/api/models")
models = models_body.get("data", [])

if not models:
    raise SystemExit("No Open WebUI models returned.")

model = models[0]
model_id = model.get("id") or model.get("name")

if not model_id:
    raise SystemExit("Could not determine Open WebUI model id.")

print(f"OK   Open WebUI Model: {model_id}")

engine = PromptEngineManager()
engine.history.build_context = lambda: ""

prompt = engine.generate(
    user_prompt="Was entscheidet der Benutzer bei MEMORIA?",
    model="gemma",
    system_prompt=(
        "Du bist MEMORIA Open WebUI Memory Test. "
        "Nutze den MEMORIA CONTEXT. Antworte kurz auf Deutsch."
    ),
    max_history_entries=0,
    max_history_characters=0,
    include_history_metadata=False,
)

required_memory = "MEMORIA bleibt immer nur das, was der Benutzer will."

if required_memory not in prompt:
    print("SKIP Memory Context: personal reference memory is not configured")
    print("INFO No memory was created or modified.")
    raise SystemExit(0)

print("OK   Memory Context: found in prompt")
print(f"INFO Retrieval Query: {engine.get_retrieval_query()}")

payload = {
    "model": model_id,
    "messages": [
        {"role": "user", "content": prompt}
    ],
    "stream": False,
}

answer_body = post_json("/api/chat/completions", payload)
message = answer_body["choices"][0]["message"]["content"].strip()

print()
print("## Result")
print("-" * 40)
print("OK   Open WebUI Response: received")
print(f"INFO Response Text: {message}")

lowered = message.lower()

memory_terms = [
    "benutzer",
    "user",
    "wille",
    "will",
    "souveränität",
    "entscheid",
    "bestimmt",
]

if "memoria" in lowered and any(term in lowered for term in memory_terms):
    print("OK   Memory Answer: response appears to use MEMORIA memory context")
else:
    print("INFO Memory Answer: response received; memory wording not obvious")

print("OK   Open WebUI Memory Live Test: completed")
