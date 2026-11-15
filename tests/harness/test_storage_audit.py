import gzip

import pytest

import storage_audit as sa
from harness_lib import ROOT, load_catalog, parse_catalog

pytestmark = pytest.mark.safety
HDR = "cap_id\tnode\tstatus\tproof\tnote\n"
IDLE = parse_catalog(HDR + "SUP-01\tM3.2\tnot-started\t\t\n")


def test_self_test_covers_every_rule():
    assert sa.self_test() == 0


def test_live_repo_stores_no_page_bodies(tmp_path):
    assert sa.audit(ROOT, tmp_path / "no-cache", load_catalog()) == []


@pytest.mark.parametrize(
    "content",
    [b"<!DOCTYPE html>", b"<html lang='en'>", b"<BODY class=x>", b'{"page_text": "x"}'],
)
def test_markers_are_caught_case_insensitively(tmp_path, content):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "f.jsonl").write_bytes(content)
    assert sa.audit(tmp_path, tmp_path / "none", IDLE)


def test_quoted_spans_and_words_like_bodyweight_pass(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "s.json").write_text(
        '{"quoted_span": "Bodyweight exercises count", "title": "html basics"}', encoding="utf-8"
    )
    assert sa.audit(tmp_path, tmp_path / "none", IDLE) == []


def test_gzipped_jsonl_is_decompressed(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "r.jsonl.gz").write_bytes(gzip.compress(b'{"html": "x"}\n'))
    assert any("r.jsonl.gz" in p for p in sa.audit(tmp_path, tmp_path / "none", IDLE))


def test_ignored_files_are_not_audited(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("data/scratch/\n", encoding="utf-8")
    (tmp_path / "data" / "scratch").mkdir(parents=True)
    (tmp_path / "data" / "scratch" / "p.html").write_text("<html>", encoding="utf-8")
    assert sa.audit(tmp_path, tmp_path / "none", IDLE) == []


def test_body_cache_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("CITEWATCH_BODY_CACHE", str(tmp_path / "c"))
    assert sa.body_cache_dir() == tmp_path / "c"
