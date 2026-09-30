"""Write ``release_notes.md`` for the current package version.

Prefers a hand-written ``docs/releases/v<version>.md``; otherwise extracts the
``# v<version>`` section of ``docs/RELEASE_NOTES.md``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOOTER = (
    "\n\n---\n설치 파일은 코드 서명이 없어 Windows SmartScreen 경고가 표시될 수 있습니다. "
    "`.sha256` 파일로 무결성을 확인하세요.\n"
)


def main(version: str, output: str = "release_notes.md") -> int:
    curated = ROOT / "docs" / "releases" / f"v{version}.md"
    if curated.is_file():
        notes = curated.read_text(encoding="utf-8").strip()
    else:
        text = (ROOT / "docs" / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        match = re.search(rf"^# v{re.escape(version)}\s*$(.*?)(?=^# v|\Z)", text, re.M | re.S)
        if not match:
            print(f"no release notes for v{version}", file=sys.stderr)
            return 1
        notes = match.group(1).strip()
    Path(output).write_text(notes + FOOTER, encoding="utf-8")
    print(notes + FOOTER)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        from r2r_evaluation_report import __version__ as version
    else:
        version = sys.argv[1]
    raise SystemExit(main(version, *sys.argv[2:3]))
