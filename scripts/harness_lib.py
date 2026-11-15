"""Shared helpers for the AI Visibility build harness (ported from EvalKit) (graph, catalog, specs).

The build graph lives in docs/graph/graph.md as a markdown table. The capability
ledger lives in docs/graph/catalog.tsv. These helpers parse both and derive node status.
Nothing here touches the network.
"""

from __future__ import annotations

import bz2
import csv
import gzip
import io
import lzma
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH_MD = ROOT / "docs" / "graph" / "graph.md"
CATALOG_TSV = ROOT / "docs" / "graph" / "catalog.tsv"
SPECS_DIR = ROOT / "specs"

STATUSES = ("not-started", "spec", "building", "green")
NODE_RE = re.compile(r"^[WNAMSBD]\d+\.\d+$")
NODE_LIKE_RE = re.compile(r"^[A-Za-z]\d+\.\d+$")  # looks like a node id but may be malformed
CATALOG_FIELDS = ("cap_id", "node", "status", "proof", "note")
PROOF_DIMENSIONS = ("logical", "contract", "golden", "repro", "safety")


@dataclass
class Node:
    id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    verified_by: str = ""
    deliverable: str = ""


@dataclass
class Cap:
    cap_id: str
    node: str
    status: str
    proof: str
    note: str


class HarnessError(Exception):
    """Raised when a harness input file is malformed."""


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_graph(text: str) -> dict[str, Node]:
    """Parse every markdown table row whose first cell is a node id."""
    nodes: dict[str, Node] = {}
    in_fence = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not raw.lstrip().startswith("|"):
            continue
        cells = _cells(raw)
        node_id = cells[0].strip("*` ")
        if not NODE_RE.match(node_id):
            if NODE_LIKE_RE.match(node_id):
                raise HarnessError(f"graph line {lineno}: malformed node id {node_id!r}")
            continue
        if len(cells) < 3:
            raise HarnessError(f"graph line {lineno}: node {node_id} row needs a depends_on cell")
        if node_id in nodes:
            raise HarnessError(f"duplicate node {node_id} in graph")
        deps_cell = cells[2]
        deps: list[str] = []
        if deps_cell not in ("", "—", "-"):
            for part in deps_cell.split(","):
                dep = part.strip().strip("*` ")
                if not NODE_RE.match(dep):
                    raise HarnessError(f"{node_id}: unparseable depends_on entry {part.strip()!r}")
                deps.append(dep)
        nodes[node_id] = Node(
            id=node_id,
            title=cells[1],
            depends_on=deps,
            verified_by=cells[3] if len(cells) > 3 else "",
            deliverable=cells[4] if len(cells) > 4 else "",
        )
    if not nodes:
        raise HarnessError("graph has no node rows")
    return nodes


def load_graph(path: Path = GRAPH_MD) -> dict[str, Node]:
    return parse_graph(path.read_text(encoding="utf-8"))


def parse_catalog(text: str) -> list[Cap]:
    # QUOTE_NONE: proof cells hold literal double quotes and must round-trip unchanged
    rows = list(csv.reader(text.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    if not rows or tuple(c.strip() for c in rows[0]) != CATALOG_FIELDS:
        raise HarnessError("catalog header must be exactly: " + " | ".join(CATALOG_FIELDS))
    caps: list[Cap] = []
    seen: set[str] = set()
    for i, row in enumerate(rows[1:], start=2):
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) != len(CATALOG_FIELDS):
            raise HarnessError(f"catalog line {i}: expected 5 columns, got {len(row)}")
        cap_id, node, status, proof, note = (c.strip() for c in row)
        if not cap_id or not node:
            raise HarnessError(f"catalog line {i}: cap_id and node are required")
        if status not in STATUSES:
            raise HarnessError(f"catalog line {i}: unknown status {status!r}")
        if cap_id in seen:
            raise HarnessError(f"catalog line {i}: duplicate cap {cap_id}")
        seen.add(cap_id)
        caps.append(Cap(cap_id=cap_id, node=node, status=status, proof=proof, note=note))
    return caps


def load_catalog(path: Path = CATALOG_TSV) -> list[Cap]:
    return parse_catalog(path.read_text(encoding="utf-8"))


def write_catalog(caps: list[Cap], path: Path = CATALOG_TSV) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(CATALOG_FIELDS) + "\n")
        for c in caps:
            cells = [c.cap_id, c.node, c.status, c.proof, c.note]
            if any("\t" in x or "\n" in x for x in cells):
                raise HarnessError(f"catalog row {c.cap_id}: a cell contains a tab or newline")
            fh.write("\t".join(cells) + "\n")


def node_status(node_id: str, caps: list[Cap]) -> str:
    """green if every row is green; building if any row is building or green.

    Otherwise spec if any row is spec, else not-started.
    """
    rows = [c for c in caps if c.node == node_id]
    if not rows:
        return "not-started"
    statuses = {c.status for c in rows}
    if statuses == {"green"}:
        return "green"
    if statuses & {"building", "green"}:
        return "building"
    if "spec" in statuses:
        return "spec"
    return "not-started"


def find_cycle(nodes: dict[str, Node]) -> list[str] | None:
    """Return one dependency cycle as a list of node ids, or None."""
    white, grey, black = 0, 1, 2
    color = dict.fromkeys(nodes, white)
    stack: list[str] = []

    def visit(n: str) -> list[str] | None:
        color[n] = grey
        stack.append(n)
        for d in nodes[n].depends_on:
            if d not in nodes:
                continue
            if color[d] == grey:
                return [*stack[stack.index(d) :], d]
            if color[d] == white:
                found = visit(d)
                if found:
                    return found
        stack.pop()
        color[n] = black
        return None

    for n in nodes:
        if color[n] == white:
            found = visit(n)
            if found:
                return found
    return None


def eligibility_problems(
    nodes: dict[str, Node], caps: list[Cap], simulate_start: str | None = None
) -> list[str]:
    """All reasons the graph is not eligible. Empty list means eligible."""
    problems: list[str] = []
    for n in nodes.values():
        for d in n.depends_on:
            if d not in nodes:
                problems.append(f"{n.id} depends on unknown node {d}")
    cycle = find_cycle(nodes)
    if cycle:
        problems.append("dependency cycle: " + " -> ".join(cycle))
    for c in caps:
        if c.node not in nodes:
            problems.append(f"catalog row {c.cap_id} names unknown node {c.node}")
    for n in nodes.values():
        status = node_status(n.id, caps)
        active = status in ("building", "green") or n.id == simulate_start
        if not active:
            continue
        for d in n.depends_on:
            if d in nodes and node_status(d, caps) != "green":
                problems.append(
                    f"{n.id} is {'starting' if n.id == simulate_start else status} "
                    f"but dependency {d} is {node_status(d, caps)}"
                )
    return problems


def spec_dir(node_id: str, specs: Path = SPECS_DIR) -> Path | None:
    matches = sorted(p for p in specs.glob(f"{node_id}-*") if p.is_dir())
    return matches[0] if matches else None


def safe_console() -> None:
    """Never crash printing a non-ASCII path or symbol to a cp1252 Windows console (L-5)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def mentions(text: str, cap_id: str) -> bool:
    """True when cap_id appears as a whole token (HAR-01 is not found inside HAR-010)."""
    return re.search(rf"(?<![A-Za-z0-9-]){re.escape(cap_id)}(?![A-Za-z0-9])", text) is not None


def git_files(root: Path, *paths: str) -> list[Path] | None:
    """Tracked plus untracked-but-not-ignored files, NUL-separated so no name is quoted or
    mangled. None when git cannot list them."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", *paths],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    names = [os.fsdecode(n) for n in out.split(b"\0") if n]
    return sorted({root / n for n in names if (root / n).is_file()})


MAX_UNPACKED = 200 * 1024 * 1024  # stop decompression bombs


def unpack(raw: bytes, depth: int = 0) -> bytes:
    """Decompress gzip, bzip2, xz and zip by their magic bytes (any file name, nested up to
    three layers) so an audit cannot be dodged by renaming or double compressing."""
    if depth >= 3:
        return raw
    try:
        if raw[:2] == b"\x1f\x8b":
            return unpack(gzip.decompress(raw)[:MAX_UNPACKED], depth + 1)
        if raw[:3] == b"BZh":
            return unpack(bz2.decompress(raw)[:MAX_UNPACKED], depth + 1)
        if raw[:6] == b"\xfd7zXZ\x00":
            return unpack(lzma.decompress(raw)[:MAX_UNPACKED], depth + 1)
        if raw[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                parts = [unpack(zf.read(n)[:MAX_UNPACKED], depth + 1) for n in zf.namelist()]
            return b"\n".join(parts)
    except (OSError, EOFError, ValueError, lzma.LZMAError, zipfile.BadZipFile) as exc:
        raise HarnessError(f"cannot decompress: {exc}") from exc
    return raw
