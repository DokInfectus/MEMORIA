#!/usr/bin/env python3
"""
MEMORIA Patch Guard V0.2

Read-only security preflight for MEMORIA patch archives.

Checks:
- SHA256
- archive member listing
- path traversal
- absolute archive paths
- apply_patch.sh presence
- active risky shell/code patterns
- passive denylist/test strings without false BLOCKED results

No extraction.
No installation.
No config changes.
No network access.
No automatic apply.
"""

import argparse
import hashlib
import re
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional, Tuple


VERSION = "MEMORIA PATCH GUARD V0.2"
MAX_TEXT_BYTES = 256 * 1024


@dataclass
class Finding:
    level: str
    label: str
    message: str


@dataclass
class TextMember:
    name: str
    text: str


@dataclass
class ArchiveData:
    names: List[str]
    texts: List[TextMember]


ACTIVE_BLOCK_PATTERNS = [
    ("network download", re.compile(r"(^|[;&|]\s*)(curl|wget)\b", re.IGNORECASE)),
    ("python exfil request", re.compile(r"requests\s*\.\s*(post|put|patch)\s*\(", re.IGNORECASE)),
    ("socket connect", re.compile(r"socket\s*\.\s*create_connection\s*\(", re.IGNORECASE)),
    ("packet capture", re.compile(r"(^|[;&|]\s*)(tcpdump|wireshark|tshark)\b", re.IGNORECASE)),
    ("disk format", re.compile(r"(^|[;&|]\s*)mkfs(\.|\s|$)", re.IGNORECASE)),
    ("raw disk write", re.compile(r"(^|[;&|]\s*)dd\s+[^#]*\bof=/dev/", re.IGNORECASE)),
    ("service autostart", re.compile(r"systemctl\s+enable\b", re.IGNORECASE)),
    ("setuid chmod", re.compile(r"chmod\s+(u\+s|\+s|[0-7]*4[0-7]{3})\b", re.IGNORECASE)),
    ("telemetry marker", re.compile(r"\b(telemetry_upload|packet_capture|secret_exfiltration)\b", re.IGNORECASE)),
]

ACTIVE_WARN_PATTERNS = [
    ("shell eval", re.compile(r"(^|[;&|]\s*)(eval|exec)\b", re.IGNORECASE)),
    ("remote shell/file transfer", re.compile(r"(^|[;&|]\s*)(nc|netcat|scp|rsync|ssh)\b", re.IGNORECASE)),
    ("destructive remove", re.compile(r"(^|[;&|]\s*)rm\s+-[a-zA-Z]*r[f]?\b", re.IGNORECASE)),
    ("root path reference", re.compile(r"/(etc|usr|bin|sbin|root|home)/", re.IGNORECASE)),
]

PASSIVE_HINTS = [
    "forbidden",
    "required",
    "pattern",
    "patterns",
    "denylist",
    "allowlist",
    "block_patterns",
    "warn_patterns",
    "automatic_mount_markers",
    "absent",
    "found patch guard text",
]

TEXT_SUFFIXES = (
    ".sh",
    ".py",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
)


def line() -> None:
    print("-" * 60)


def section(title: str) -> None:
    print()
    print(f"## {title}")
    line()


def status(label: str, message: str, ok=None) -> None:
    if ok is True:
        prefix = "OK  "
    elif ok is False:
        prefix = "FAIL"
    else:
        prefix = "INFO"
    print(f"{prefix} {label}: {message}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_kind(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return "tar"
    if name.endswith(".zip"):
        return "zip"
    return "unknown"


def normalize_member_name(name: str) -> str:
    return name.replace(chr(92), "/")


def safe_member_path(name: str) -> Tuple[bool, str]:
    normalized = normalize_member_name(name)
    if normalized.startswith("/"):
        return False, "absolute archive path"
    if not normalized.strip():
        return False, "empty archive path"
    for part in PurePosixPath(normalized).parts:
        if part == "..":
            return False, "path traversal component '..'"
    return True, "ok"


def is_text_member(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(TEXT_SUFFIXES)


def read_tar(path: Path, member_limit: int) -> ArchiveData:
    names: List[str] = []
    texts: List[TextMember] = []
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            names.append(member.name)
            if len(names) > member_limit:
                continue
            if not member.isfile() or not is_text_member(member.name):
                continue
            if member.size > MAX_TEXT_BYTES:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            raw = extracted.read(MAX_TEXT_BYTES)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
            texts.append(TextMember(member.name, text))
    return ArchiveData(names=names, texts=texts)


def read_zip(path: Path, member_limit: int) -> ArchiveData:
    names: List[str] = []
    texts: List[TextMember] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            names.append(info.filename)
            if len(names) > member_limit:
                continue
            if info.is_dir() or not is_text_member(info.filename):
                continue
            if info.file_size > MAX_TEXT_BYTES:
                continue
            raw = archive.read(info.filename)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
            texts.append(TextMember(info.filename, text))
    return ArchiveData(names=names, texts=texts)


def read_archive(path: Path, member_limit: int) -> Tuple[str, ArchiveData]:
    kind = archive_kind(path)
    if kind == "tar":
        return kind, read_tar(path, member_limit)
    if kind == "zip":
        return kind, read_zip(path, member_limit)
    raise RuntimeError("unsupported archive type")


def scan_paths(names: List[str]) -> List[Finding]:
    findings: List[Finding] = []
    if not names:
        findings.append(Finding("BLOCKED", "Archive", "no archive members found"))
        return findings

    for name in names:
        safe, reason = safe_member_path(name)
        if not safe:
            findings.append(Finding("BLOCKED", "Path Guard", f"{name}: {reason}"))

    if not any(Path(normalize_member_name(n)).name == "apply_patch.sh" for n in names):
        findings.append(Finding("WARNING", "apply_patch.sh", "not found"))

    return findings


def looks_passive_line(line_text: str, context: str) -> bool:
    stripped = line_text.strip()
    lowered = stripped.lower()

    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
    if stripped.startswith(("//", "/*", "*")):
        return True
    if context in {"heredoc", "test", "readme"}:
        return True
    if any(hint in lowered for hint in PASSIVE_HINTS) and ("'" in stripped or '"' in stripped):
        return True
    if re.search(r"[A-Z_]*PATTERNS?\s*=\s*\[", stripped):
        return True
    return False


def line_context(member_name: str, in_heredoc: bool) -> str:
    lowered = member_name.lower()
    if in_heredoc:
        return "heredoc"
    if "/test_" in lowered or lowered.startswith("test_") or lowered.endswith("test_patch_guard.py"):
        return "test"
    if lowered.endswith((".md", ".txt")):
        return "readme"
    return "active"


def scan_line(member_name: str, number: int, text: str, context: str) -> List[Finding]:
    findings: List[Finding] = []
    passive = looks_passive_line(text, context)
    location = f"{member_name}:{number}"

    for label, regex in ACTIVE_BLOCK_PATTERNS:
        if regex.search(text):
            if passive:
                findings.append(Finding("INFO", label, f"passive pattern mention at {location}"))
            else:
                findings.append(Finding("BLOCKED", label, f"active risky pattern at {location}"))

    for label, regex in ACTIVE_WARN_PATTERNS:
        if regex.search(text):
            if passive:
                findings.append(Finding("INFO", label, f"passive pattern mention at {location}"))
            else:
                findings.append(Finding("WARNING", label, f"review line at {location}"))

    return findings


def heredoc_end_token(line_text: str) -> Optional[str]:
    match = re.search(r"<<-?\s*['\"]?([A-Za-z0-9_]+)['\"]?", line_text)
    if not match:
        return None
    return match.group(1)


def scan_text_member(item: TextMember) -> List[Finding]:
    findings: List[Finding] = []
    in_heredoc = False
    end_token: Optional[str] = None

    for number, line_text in enumerate(item.text.splitlines(), start=1):
        stripped = line_text.strip()

        if in_heredoc:
            if stripped == end_token:
                in_heredoc = False
                end_token = None
                continue
            context = line_context(item.name, True)
            findings.extend(scan_line(item.name, number, line_text, context))
            continue

        token = heredoc_end_token(line_text)
        if token:
            in_heredoc = True
            end_token = token
            # Scan the heredoc start line itself as active shell, but not the future content.
            findings.extend(scan_line(item.name, number, line_text, line_context(item.name, False)))
            continue

        findings.extend(scan_line(item.name, number, line_text, line_context(item.name, False)))

    return findings


def scan_texts(texts: List[TextMember]) -> List[Finding]:
    findings: List[Finding] = []
    for item in texts:
        findings.extend(scan_text_member(item))
    return findings


def print_findings(findings: List[Finding]) -> None:
    if not findings:
        status("Security Scan", "no risky patterns detected", ok=True)
        return

    for item in findings:
        if item.level == "BLOCKED":
            status(item.label, item.message, ok=False)
        elif item.level == "WARNING":
            status(item.label, item.message, ok=None)
        else:
            status(item.label, item.message, ok=True)


def result_level(findings: List[Finding]) -> str:
    if any(item.level == "BLOCKED" for item in findings):
        return "BLOCKED"
    if any(item.level == "WARNING" for item in findings):
        return "WARNING"
    return "SAFE"


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MEMORIA patch security preflight.")
    parser.add_argument("patch", help="Patch archive path (.tar.gz, .tgz or .zip)")
    parser.add_argument("--member-limit", type=int, default=80, help="Maximum archive members to print/read. Default: 80")
    args = parser.parse_args()

    patch_path = Path(args.patch)

    print(VERSION)
    line()
    print("Read-only patch preflight. No extraction. No installation. No config changes.")
    line()

    section("Patch")
    if not patch_path.exists():
        status("Patch", f"not found: {patch_path}", ok=False)
        return 2
    if not patch_path.is_file():
        status("Patch", f"not a file: {patch_path}", ok=False)
        return 2

    status("Path", str(patch_path), ok=True)
    status("SHA256", sha256_file(patch_path), ok=True)
    status("Type", archive_kind(patch_path), ok=True if archive_kind(patch_path) != "unknown" else False)

    section("Archive Members")
    findings: List[Finding] = []
    try:
        kind, archive = read_archive(patch_path, args.member_limit)
    except Exception as exc:
        status("Archive", str(exc), ok=False)
        return 2

    names = archive.names
    texts = archive.texts

    if names:
        for name in names[: args.member_limit]:
            status("Member", name, ok=True)
        if len(names) > args.member_limit:
            status("Members", f"{len(names) - args.member_limit} more not shown", ok=None)
    else:
        status("Members", "none", ok=False)

    section("Security Scan")
    findings.extend(scan_paths(names))
    findings.extend(scan_texts(texts))
    print_findings(findings)

    result = result_level(findings)
    section("Result")
    if result == "SAFE":
        status("Patch Guard", "SAFE - no active risky patterns detected", ok=True)
        print()
        print("Manual next step: review output above, then extract manually only if you trust the source.")
        return 0
    if result == "WARNING":
        status("Patch Guard", "WARNING - review carefully before applying", ok=None)
        print()
        print("MEMORIA will not apply this patch automatically.")
        return 1
    status("Patch Guard", "BLOCKED - do not apply this patch without investigation", ok=False)
    print()
    print("MEMORIA will not apply this patch automatically.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

