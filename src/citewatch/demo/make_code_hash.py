"""Make the passkey registration code's hash for the host's secret store (OWNER D-59).

    uv run python -m citewatch.demo.make_code_hash

Reads the code twice without echoing it, and prints the two secret lines to paste into the
Streamlit Community Cloud secrets box. The code itself is never printed or written anywhere.
"""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable

from citewatch.demo.passkeys import MAX_CODE_DIGITS, MIN_CODE_DIGITS, make_code_hash, valid_code


def _read(prompt: str) -> str:
    """Hidden input on a terminal; plain stdin otherwise (piped input, or a shell with no
    terminal, where getpass fails or, on Windows, waits on the console)."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    sys.stderr.write(prompt)
    line = sys.stdin.readline()
    sys.stderr.write("\n")
    return line


def main(
    read: Callable[[str], str] = _read,
    write: Callable[[str], object] = print,
) -> int:
    code = read(f"Registration code ({MIN_CODE_DIGITS}-{MAX_CODE_DIGITS} digits, not shown): ")
    code = code.strip()
    if not valid_code(code):
        write(f"error: the code must be {MIN_CODE_DIGITS} to {MAX_CODE_DIGITS} digits (0-9).")
        return 2
    if read("Again: ").strip() != code:
        write("error: the two entries differ.")
        return 2
    code_hash, salt = make_code_hash(code)
    write("# Paste into the app's secrets (Streamlit Community Cloud > Settings > Secrets):")
    write(f'CITEWATCH_DEMO_CODE_HASH = "{code_hash}"')
    write(f'CITEWATCH_DEMO_CODE_SALT = "{salt}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
