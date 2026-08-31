#!/usr/bin/env python3
"""
MEMORIA Docker / Tunnel Visibility V0.1

Read-only visibility for Docker containers, exposed ports and tunnel indicators.
No config changes. No secret/env dump. No container actions.
"""

import json
import shutil
import subprocess


WATCH_PORTS = ["3000", "8080", "9900", "6080", "5901"]
TUNNEL_WORDS = ["cloudflare", "cloudflared", "tunnel", "ngrok", "tailscale", "zerotier"]


def line():
    print("-" * 60)


def section(title):
    print()
    print(f"## {title}")
    line()


def status(label, message, ok=None):
    if ok is True:
        prefix = "OK  "
    elif ok is False:
        prefix = "FAIL"
    else:
        prefix = "INFO"
    print(f"{prefix} {label}: {message}")


def run(command):
    try:
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
        return result.returncode, result.stdout
    except Exception as exc:
        return 1, str(exc)


def docker_available():
    return shutil.which("docker") is not None


def docker_names():
    code, output = run(["docker", "ps", "--format", "{{.Names}}"])
    if code != 0:
        return []
    return [row.strip() for row in output.splitlines() if row.strip()]


def inspect_container(name):
    template = (
        "Name={{.Name}}\n"
        "Image={{.Config.Image}}\n"
        "State={{.State.Status}}\n"
        "Restart={{.HostConfig.RestartPolicy.Name}}\n"
        "Network={{.HostConfig.NetworkMode}}\n"
        "Command={{json .Config.Cmd}}\n"
        "Ports={{json .NetworkSettings.Ports}}\n"
    )
    code, output = run(["docker", "inspect", name, "--format", template])
    if code != 0:
        return None

    data = {}
    for row in output.splitlines():
        if "=" in row:
            key, value = row.split("=", 1)
            data[key.strip()] = value.strip()

    command = data.get("Command", "")
    try:
        parsed = json.loads(command)
        if isinstance(parsed, list):
            command = " ".join(str(item) for item in parsed)
    except Exception:
        pass

    data["Command"] = command
    return data


def service_hint(text):
    lowered = text.lower()
    if "open-webui" in lowered:
        return "Open WebUI"
    if "open-terminal" in lowered:
        return "Open WebUI Terminal"
    if "llama" in lowered:
        return "llama.cpp / llama-server"
    if "cloudflare" in lowered or "cloudflared" in lowered:
        return "Cloudflare Tunnel"
    if "websockify" in lowered:
        return "noVNC / websockify"
    if "xtigervnc" in lowered:
        return "VNC display"
    return "unknown"


def is_tunnel(text):
    lowered = text.lower()
    return any(word in lowered for word in TUNNEL_WORDS)


def show_containers():
    section("Docker Containers")

    if not docker_available():
        status("Docker", "docker command not found", ok=None)
        return

    names = docker_names()
    if not names:
        status("Docker", "no running containers found", ok=None)
        return

    for name in names:
        data = inspect_container(name)
        if not data:
            status("Container", f"{name}: inspect failed", ok=False)
            continue

        combined = f"{data.get('Name', '')} {data.get('Image', '')} {data.get('Command', '')}"

        status("Container", data.get("Name", name).lstrip("/"), ok=True)
        print(f"     Image: {data.get('Image', 'unknown')}")
        print(f"     State: {data.get('State', 'unknown')}")
        print(f"     Restart: {data.get('Restart', 'unknown')}")
        print(f"     Network: {data.get('Network', 'unknown')}")
        print(f"     Service Hint: {service_hint(combined)}")
        print(f"     Command: {data.get('Command', 'unknown')}")
        print(f"     Ports: {data.get('Ports', '{}')}")

        if is_tunnel(combined):
            status("External Access", "tunnel-like container detected; verify this is expected", ok=None)

        print()


def show_ports():
    section("Listening Ports")
    code, output = run(["ss", "-ltnp"])
    if code != 0:
        status("ss", "not available", ok=None)
        return

    found = False
    for row in output.splitlines():
        if not row.startswith("LISTEN"):
            continue
        if any(f":{port}" in row for port in WATCH_PORTS):
            found = True
            status("Port", row, ok=True)

    if not found:
        status("Ports", "no watched ports found", ok=None)


def main():
    print("MEMORIA DOCKER / TUNNEL VISIBILITY V0.1")
    line()
    print("Read-only Docker and external access visibility.")
    print("No config changes. No secret/env dump. No container actions.")
    line()

    show_containers()
    show_ports()

    section("Safety Notes")
    status("Secrets", "environment variables are not printed", ok=True)
    status("Inspect", "full docker inspect output is not printed", ok=True)
    status("Actions", "no containers are changed by this tool", ok=True)
    status("Network", "visibility only; no packet capture", ok=True)

    section("Result")
    status("Docker / Tunnel Visibility", "completed", ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
