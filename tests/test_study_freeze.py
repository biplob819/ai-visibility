"""RUN-04: the flagship study's run data is committed and frozen (D-2, D-7).

These are the paid runs' records (run 1 and run 2, OWNER D-48). Never edit a hash to make a
test pass: changed run data is a new study run with its own manifest.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "studies" / "uk-health" / "data"
FROZEN = {
    "answers.jsonl": "bb53faccd0208a4e480b856702ecca72b9f42b2a4d38afc5c2276a8cebd50495",
    "citations.jsonl": "c5a1366da1103f755a706e9460ea95a99553cfd8eb4f849980fc6f051a4d0a9a",
    "consulted.jsonl": "734db2ca5419afe57804637138c19b91da2381a0a742827dc71fc5ce65803e76",
    "page_meta.jsonl": "831a53936243790e49abb9ca498625244eca33526385973f70ae8858b106c504",
    "fetch_log.jsonl": "e0a7833048f5e2b77dc9e2d21d0f66146445833cf26dae913eb2b1b80c391a11",
    "spend-ledger.jsonl": "bb4667ca82fb34189f32c9e51671e80b7ec324066fbcb29eadf54d422c930ca4",
    "support_sample.jsonl": "076638d0b5197e82ce16f9623cc915e29547da65be423d3875a9987b00e31fa2",
    "hand_sample.jsonl": "e2d11e9ba5fba113c151fdc3962def501c53db987c3968d69ddea578b15688d6",
    "runs/run-1/manifest.json": "d73bae03ab1443812b6cf60a89d45cc22677215cc0b1cf1fcaa3d2d6a8f6fce5",
    "runs/run-2/manifest.json": "4ae9d9f4a1cc9869b4f7aac65933ceb89e02f3ef82e2b0f7f20ee12d5d3cc33c",
    # the support check's records (M3.2): results depend on them (S3.1 pass 2, L2)
    "support_verdicts.jsonl": "1cda8d1c05804c803a35e44012e01b939eb2ad1e46d61c8c2be6fe47d46c90cf",
    "support_label_key.jsonl": "de1e4c22a6596209e20161c766bd42fb5491e8f818f1c802adcb1f1b74fa7095",
    "support_text_fetches.jsonl": "211fe5e30e05e0326ecb4cac7d1358a38bfe2047527fe0761d58b7b7df50ec9a",
    "support_replacements.jsonl": "31382e684adfb01a3ff7570d411bc3b4824f50c7c38555f27cc4fa6bc2b995e7",
    "support_unjudged.jsonl": "af8a88dff4c1d31d158be237eaa902d30fd0e750e9f092f36e158814ed747331",
}
RAW_ASK_RUNS_1_2 = "4185838436360a46d2949713ff860fb18633606e2d906f04d5be0eaee2f0ae33"


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_run_data_is_frozen(name: str):
    assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == FROZEN[name]


def test_both_study_runs_have_a_complete_manifest():
    for run in (1, 2):
        m = json.loads((DATA / "runs" / f"run-{run}" / "manifest.json").read_text("utf-8"))
        for key in ("config_hash", "git_sha", "started_at", "finished_at"):
            assert m.get(key), (run, key)
        assert m.get("models") or m.get("model_snapshots"), run


def test_the_raw_answer_records_of_both_runs_are_frozen():
    """S3.1 pass 2 L1: the verbatim provider responses behind every answer and cost."""
    h = hashlib.sha256()
    n = 0
    for f in sorted((DATA / "raw" / "ask").glob("*/*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            run = json.load(fh).get("run")
        if run in (1, 2):
            h.update(f.relative_to(DATA).as_posix().encode())
            h.update(f.read_bytes())
            n += 1
    assert n == 400
    assert h.hexdigest() == RAW_ASK_RUNS_1_2
