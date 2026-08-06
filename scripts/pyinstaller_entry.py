"""Absolute-import launcher used only by the frozen Windows executable."""

from r2r_evaluation_report.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
