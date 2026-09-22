from __future__ import annotations

import argparse
from pathlib import Path

from app.db import SessionLocal
from app.services.importer import import_odt


def main() -> None:
    parser = argparse.ArgumentParser(description="Read an ODT reference document into CareerForge.")
    parser.add_argument("source", type=Path, help="Path to a source .odt file (read-only).")
    args = parser.parse_args()
    source = args.source.resolve()
    if source.suffix.lower() != ".odt" or not source.is_file():
        raise SystemExit("Provide an existing .odt source file.")
    with SessionLocal() as session:
        run = import_odt(session, source)
    print(f"Import status: {run.status}; records added: {run.imported_count}")


if __name__ == "__main__":
    main()
