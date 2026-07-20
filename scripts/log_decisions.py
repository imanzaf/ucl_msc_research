"""Forward cached hook commands to the organized decision-logging module."""

import runpy
from pathlib import Path


def main() -> None:
    """Execute the organized hook while preserving arguments and standard input."""
    runpy.run_path(str(Path(__file__).parent / "hooks" / "log_decisions.py"), run_name="__main__")


if __name__ == "__main__":
    main()
