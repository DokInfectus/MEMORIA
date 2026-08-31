#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def managed_path(name: str, env_var: str | None = None, fallback_rel: str | None = None) -> Path:
    """
    Resolve a MEMORIA managed storage path.

    Priority:
    1. explicit environment override, used by tests/admins
    2. Memory Storage Manager selected root
    3. project-local fallback

    This helper does not create, move, mount, format or scan private content.
    """
    if env_var and os.environ.get(env_var):
        return Path(os.environ[env_var]).expanduser().resolve()

    try:
        from memoria_memory_storage_manager import managed_paths

        paths = managed_paths()
        if name in paths:
            return paths[name].resolve()
    except Exception:
        pass

    if not fallback_rel:
        raise KeyError(f"No managed storage path known for {name}")

    return (PROJECT_ROOT / fallback_rel).resolve()
