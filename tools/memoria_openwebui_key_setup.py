#!/usr/bin/env python3
import argparse
import getpass
import stat
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = PROJECT_ROOT / "config" / "secrets"
KEY_FILE = SECRETS_DIR / "openwebui_api_key"
GITIGNORE = PROJECT_ROOT / ".gitignore"


def line():
    print("-" * 60)


def section(title: str):
    print()
    print(f"## {title}")
    line()


def status(label: str, message: str, ok=None):
    prefix = "INFO"
    if ok is True:
        prefix = "OK  "
    elif ok is False:
        prefix = "FAIL"

    print(f"{prefix} {label}: {message}")


def file_mode(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode))


def ensure_gitignore():
    text = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""
    changed = False

    for entry in ["config/secrets/", "*.key"]:
        if entry not in text.splitlines():
            text = text.rstrip() + "\n" + entry + "\n"
            changed = True

    if changed:
        GITIGNORE.write_text(text.lstrip(), encoding="utf-8")

    return changed


def save_key_value(raw_key: str) -> Path:
    key = (raw_key or "").strip().strip('"').strip("'")

    if not key:
        raise ValueError("empty Open WebUI API key rejected")

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.chmod(0o700)

    KEY_FILE.write_text(key + "\n", encoding="utf-8")
    KEY_FILE.chmod(0o600)

    ensure_gitignore()

    return KEY_FILE

def command_status(_args) -> int:
    section("MEMORIA OPEN WEBUI API KEY SETUP V0.1")
    print("Token value is never printed.")
    print("No Open WebUI private data is scanned or backed up.")

    section("Key File")

    if not KEY_FILE.exists():
        status("Open WebUI API Key", "not configured", ok=None)
        status("Expected Path", str(KEY_FILE), ok=None)
        return 0

    mode = stat.S_IMODE(KEY_FILE.stat().st_mode)
    mode_text = oct(mode)

    status("Open WebUI API Key", "configured", ok=True)
    status("Path", str(KEY_FILE), ok=True)
    status("Permissions", mode_text, ok=(mode == 0o600))

    if mode & 0o077:
        status("Security", "permissions too open; run chmod 600", ok=False)
        return 1

    status("Security", "key file permissions are restricted", ok=True)
    return 0


def command_set(_args) -> int:
    section("MEMORIA OPEN WEBUI API KEY SETUP V0.1")
    print("This writes only the local Open WebUI API key file.")
    print("Token value is never printed.")
    print("Target: config/secrets/openwebui_api_key")
    print("Permissions: chmod 600")
    print()

    confirm = input("Type SAVE to store/update the Open WebUI API key: ").strip()

    if confirm != "SAVE":
        status("Open WebUI API Key", "not changed", ok=None)
        return 0

    key = getpass.getpass("Open WebUI API key: ").strip().strip('"').strip("'")

    if not key:
        status("Open WebUI API Key", "empty key rejected", ok=False)
        return 1

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.chmod(0o700)

    KEY_FILE.write_text(key + "\n", encoding="utf-8")
    KEY_FILE.chmod(0o600)

    ensure_gitignore()

    section("Result")
    status("Open WebUI API Key", "stored locally", ok=True)
    status("Path", str(KEY_FILE), ok=True)
    status("Permissions", file_mode(KEY_FILE), ok=True)
    status("Token", "value was not printed", ok=True)
    status("Git Ignore", "config/secrets/ is ignored", ok=True)

    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Configure local Open WebUI API key for MEMORIA."
    )

    sub = parser.add_subparsers(dest="command", required=True)

    status_cmd = sub.add_parser("status", help="Show key setup status without printing the key.")
    status_cmd.set_defaults(func=command_status)

    set_cmd = sub.add_parser("set", help="Store/update the Open WebUI API key locally.")
    set_cmd.set_defaults(func=command_set)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
