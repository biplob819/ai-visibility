"""Command-line entry point. N1.3 replaces this skeleton with the full Typer app (Tech Spec §5)."""

from __future__ import annotations

import argparse
import sys

from visibility import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="visibility", description=__doc__)
    parser.add_argument("--version", action="version", version=f"visibility {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
