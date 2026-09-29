"""Fail when repository-tracked research data or build artifacts are detected."""

from __future__ import annotations

import subprocess
from pathlib import Path

FORBIDDEN_SUFFIXES = {".csv", ".tsv", ".xls", ".xlsx", ".exe", ".msi", ".pt", ".pth"}
FORBIDDEN_PARTS = {"build", "dist", "installer-output", "runs"}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    tracked = [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]
    violations = [
        str(path)
        for path in tracked
        if path.suffix.lower() in FORBIDDEN_SUFFIXES
        or any(part.lower() in FORBIDDEN_PARTS for part in path.parts)
    ]
    if violations:
        print("Forbidden tracked artifacts:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print(f"SOURCE_ONLY_GUARD_OK tracked_files={len(tracked)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
