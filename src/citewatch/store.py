"""Content-addressed raw store (Tech Spec §3.1, D-1, D-2, STO-01).

Every provider response and fetch record lands once at
`data/raw/<stage>/<key[:2]>/<key>.json.gz`. Writes are atomic and first-writer-wins: a second
writer of the same key loses the race quietly and the stored object stays as first written
(EvalKit L-18). Nothing here ever holds a page body (gate 9 audits `data/`).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

STAGE = re.compile(r"^[a-z][a-z0-9_]*$")
KEY = re.compile(r"^[0-9a-f]{64}$")


class StoreError(ValueError):
    """A bad stage name, key or value."""


def _check_finite(obj: Any) -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise StoreError("NaN and infinity cannot be stored")
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise StoreError(f"object keys must be strings, got {k!r}")
            _check_finite(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            _check_finite(v)


def canonical_json(obj: Any) -> bytes:
    """One byte form per value: sorted keys, no spaces, UTF-8, no NaN."""
    _check_finite(obj)
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def stage_key(
    stage: str, code_version: str, unit: Mapping[str, Any], config_hash: str, prompt_hash: str = ""
) -> str:
    """sha256 over the stage name, its code version, the unit of work, the config hash and the
    prompt hash. For `ask` the unit carries the run number, so run 2 never reuses run 1."""
    if not STAGE.fullmatch(stage):
        raise StoreError(f"bad stage name {stage!r}")
    body = {
        "stage": stage,
        "code_version": code_version,
        "unit": dict(unit),
        "config_hash": config_hash,
        "prompt_hash": prompt_hash,
    }
    return hashlib.sha256(canonical_json(body)).hexdigest()


class RawStore:
    def __init__(self, root: Path) -> None:
        self.base = Path(root) / "data" / "raw"

    def path(self, stage: str, key: str) -> Path:
        if not STAGE.fullmatch(stage):
            raise StoreError(f"bad stage name {stage!r}")
        if not KEY.fullmatch(key):
            raise StoreError(f"bad key {key!r} (64 lower-case hex characters)")
        return self.base / stage / key[:2] / f"{key}.json.gz"

    def has(self, stage: str, key: str) -> bool:
        return self.path(stage, key).is_file()

    def put(self, stage: str, key: str, obj: Any) -> bool:
        """Store obj under key. True if this call wrote it, False if it was already there."""
        final = self.path(stage, key)
        if final.is_file():
            return False
        payload = gzip.compress(canonical_json(obj), mtime=0)  # same bytes every time
        final.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=final.parent, prefix=".tmp-", suffix=".gz")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.link(tmp, final)  # atomic and refuses to overwrite: first writer wins
            except FileExistsError:
                return False
            except OSError:
                # no hard links here (exFAT, FAT, some network or VM shares): fall back to an
                # atomic rename. Still never a partial object; a lost race can overwrite with an
                # answer to the same key, which loses nothing that was paid for (D-37)
                if final.exists():
                    return False
                os.replace(tmp, final)
                return True
            return True
        finally:
            Path(tmp).unlink(missing_ok=True)

    def get(self, stage: str, key: str) -> Any:
        p = self.path(stage, key)
        try:
            return json.loads(gzip.decompress(p.read_bytes()).decode("utf-8"))
        except FileNotFoundError:
            raise KeyError(f"{stage}/{key} is not in the store") from None

    def keys(self, stage: str) -> Iterator[str]:
        d = self.base / stage
        if not STAGE.fullmatch(stage):
            raise StoreError(f"bad stage name {stage!r}")
        if not d.is_dir():
            return
        for p in sorted(d.glob("??/*.json.gz")):
            k = p.name.removesuffix(".json.gz")
            if KEY.fullmatch(k):
                yield k
