"""Read-only browsing of local paths for authenticated form selections."""

from __future__ import annotations

import os
from pathlib import Path

from app.services import git_ops


def local_path(value: str) -> Path:
    # UNC/device paths can trigger remote authentication; this picker is local only.
    if value.startswith(("\\\\", "//")):
        raise ValueError("Choose a local drive, not a network or device path.")
    if os.name == "nt":
        import ctypes

        drive = Path(value).expanduser().anchor
        if drive and ctypes.windll.kernel32.GetDriveTypeW(drive) == 4:
            raise ValueError("Choose a local drive, not a mapped network drive.")
    path = Path(value).expanduser().resolve(strict=True)
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("Choose a local drive, not a network or device path.")
    return path


def browse_paths(kind: str, value: str, repository: str, select_path: bool, offset: int) -> dict:
    if kind not in {"repository", "subdirectory", "odt"}:
        raise ValueError("Unknown selection type.")
    root = local_path(repository) if kind == "subdirectory" else None
    if root is not None and not root.is_dir():
        raise ValueError("Choose an existing repository folder first.")
    path = local_path(value or str(root or Path.home()))
    if root is not None and not path.is_relative_to(root):
        raise ValueError("Choose a folder inside the selected repository.")
    if select_path:
        if kind == "odt":
            if not path.is_file() or path.suffix.lower() != ".odt":
                raise ValueError("Choose an existing .odt document.")
        else:
            if not path.is_dir():
                raise ValueError("Choose an existing folder.")
            if kind == "repository":
                if not (path / ".git").exists():
                    raise ValueError("Choose the repository root folder containing .git.")
                git_ops.status(path)
        return {"selected": str(path.relative_to(root)) if root else str(path)}
    if path.is_file():
        path = path.parent
    if not path.is_dir():
        raise ValueError("Choose an existing folder.")
    entries = []
    with os.scandir(path) as children:
        for child in children:
            try:
                resolved = local_path(child.path)
                if root is not None and not resolved.is_relative_to(root):
                    continue
                folder = resolved.is_dir()
                if folder or (
                    kind == "odt" and resolved.is_file() and resolved.suffix.lower() == ".odt"
                ):
                    entries.append({"name": child.name, "path": str(resolved), "folder": folder})
            except (OSError, ValueError, RuntimeError):
                continue
    entries.sort(key=lambda item: (not item["folder"], str(item["name"]).casefold()))
    offset = max(0, offset)
    return {
        "path": str(path),
        "parent": str(path.parent) if path != (root or path.parent) else None,
        "entries": entries[offset : offset + 100],
        "previous": max(0, offset - 100) if offset else None,
        "next": offset + 100 if offset + 100 < len(entries) else None,
        "roots": [str(root)] if root else local_roots(),
    }


def local_roots() -> list[str]:
    if os.name != "nt":
        return [str(Path.home()), "/"]
    import ctypes

    # Fixed/removable drives only: avoid mapped network drives.
    return [
        f"{letter}:\\"
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if ctypes.windll.kernel32.GetDriveTypeW(f"{letter}:\\") in (2, 3)
    ]
