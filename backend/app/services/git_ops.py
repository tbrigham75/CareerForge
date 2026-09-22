from __future__ import annotations

import subprocess
from pathlib import Path


class GitOperationError(RuntimeError):
    pass


def _run(repo: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        shell=False,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise GitOperationError(result.stderr.strip() or "Git command failed.")
    return result.stdout


def status(repo: Path) -> str:
    return _run(repo, ["status", "--short"])


def diff(repo: Path) -> str:
    return _run(repo, ["diff", "--", "."])


def commit(repo: Path, files: list[str], message: str, confirmed: bool) -> str:
    if not confirmed:
        raise GitOperationError("Commit requires explicit confirmation.")
    if not files or any(Path(item).is_absolute() or ".." in Path(item).parts for item in files):
        raise GitOperationError("Invalid export file selection.")
    _run(repo, ["add", "--", *files])
    _run(repo, ["commit", "-m", message])
    return _run(repo, ["rev-parse", "HEAD"]).strip()


def push(repo: Path, remote: str, branch: str, confirmed: bool) -> str:
    if not confirmed:
        raise GitOperationError("Push requires explicit confirmation.")
    if status(repo).strip():
        raise GitOperationError("Push blocked because the repository has uncommitted changes.")
    return _run(repo, ["push", remote, branch])
