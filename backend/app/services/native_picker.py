"""A local Windows desktop picker; remote browsers must use server navigation."""

from __future__ import annotations

import ctypes
import ipaddress
import json
import os
import subprocess
import threading
from pathlib import Path

from fastapi import Request

from app.services.file_browser import browse_paths, local_path

_picker_lock = threading.Lock()


def available(request: Request) -> bool:
    if os.name != "nt" or not request.client:
        return False
    if any(key in request.headers for key in ("forwarded", "x-forwarded-for", "x-forwarded-host")):
        return False
    try:
        if not ipaddress.ip_address(request.client.host).is_loopback:
            return False
    except ValueError:
        return False
    if request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return False
    session_id = ctypes.c_ulong()
    return bool(
        ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id))
        and session_id.value
    )


def choose(kind: str, value: str, repository: str) -> dict:
    if kind not in {"repository", "subdirectory", "odt"}:
        raise ValueError("Unknown selection type.")
    if kind == "subdirectory" and not repository.strip():
        raise ValueError("Choose a repository folder first.")
    root = local_path(repository) if kind == "subdirectory" else None
    initial = root or Path.home()
    if value.strip():
        try:
            candidate = local_path(str(root / value) if root else value)
            if root is not None and not candidate.is_relative_to(root):
                raise ValueError("Choose a folder inside the selected repository.")
            initial = candidate if candidate.is_dir() else candidate.parent
        except FileNotFoundError:
            pass
    if not _picker_lock.acquire(blocking=False):
        raise ValueError("A Windows picker is already open. Finish or cancel it first.")
    try:
        executable = (
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        result = subprocess.run(
            [
                str(executable),
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(Path(__file__).with_suffix(".ps1")),
            ],
            input=json.dumps(
                {
                    "folder": kind != "odt",
                    "initial": str(initial),
                    "title": {
                        "repository": "CareerForge - Select Git repository",
                        "subdirectory": "CareerForge - Select export folder inside repository",
                        "odt": "CareerForge - Select ODT source document",
                    }[kind],
                }
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError(
                "Windows could not open the picker. Use advanced path entry or the server-browser fallback."
            )
        data = json.loads(result.stdout)
        if data.get("canceled"):
            return {"canceled": True}
        selected = data.get("selected")
        if not isinstance(selected, str) or not selected:
            raise ValueError("No file or folder was selected.")
        return browse_paths(kind, selected, repository, True, 0)
    finally:
        _picker_lock.release()
