"""Regression tests for the W0.1 verifier's findings (RUN-STATE.md, pass 1)."""

import gzip
import subprocess

import pytest

import fetch_audit as fa
import node_converge as nc
import secret_scan
import storage_audit as sa
from harness_lib import Cap, load_catalog, mentions, parse_catalog, spec_dir, write_catalog

HDR = "cap_id\tnode\tstatus\tproof\tnote\n"
IDLE = parse_catalog(HDR + "SUP-01\tM3.2\tnot-started\t\t\n")


def test_proof_cells_with_quotes_round_trip_unchanged(tmp_path):
    proof = 'logical=tests/x.py›"test_a"; repro=n/a:pure function, nothing generated'
    caps = [Cap("HAR-01", "W0.1", "green", proof, "note [D-1]")]
    out = tmp_path / "catalog.tsv"
    write_catalog(caps, out)
    assert f"\t{proof}\t" in out.read_text(encoding="utf-8")
    assert load_catalog(out)[0].proof == proof
    write_catalog(load_catalog(out), tmp_path / "again.tsv")
    assert (tmp_path / "again.tsv").read_bytes() == out.read_bytes()


def test_spec_dir_ignores_files_and_mentions_needs_whole_tokens(tmp_path):
    (tmp_path / "W0.1-a-file.md").write_text("x", encoding="utf-8")
    (tmp_path / "W0.1-harness").mkdir()
    assert spec_dir("W0.1", tmp_path) == tmp_path / "W0.1-harness"
    assert mentions("**HAR-01** text", "HAR-01")
    assert not mentions("HAR-010 only", "HAR-01")
    assert not mentions("XHAR-01", "HAR-01")


def test_secret_scan_reads_names_git_would_quote_and_gz(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    key = "sk-ant-" + "Q" * 40
    (tmp_path / "notes café ü.md").write_text(f"K = {key}\n", encoding="utf-8")
    (tmp_path / "dump.JSON.GZ").write_bytes(gzip.compress(f"K = {key}\n".encode()))
    hits = secret_scan.scan(secret_scan.candidate_files(tmp_path))
    assert len(hits) == 2


@pytest.mark.polite
@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"robots": "DISALLOWED"}, "robots must be"),
        ({"robots": None}, "robots must be"),
        ({"status": "403"}, "status must be"),
        ({"status": [403]}, "status must be"),
        ({"status": True}, "status must be"),
        ({"bytes": -1}, "bytes must be"),
        ({"attempt": 0}, "attempt must be"),
        ({"outcome": "robots_disallowed", "robots": "disallowed"}, "status and bytes must be null"),
    ],
)
def test_fetch_audit_rejects_bad_field_values(over, needle):
    assert any(needle in p for p in fa.audit([fa._line(**over)]))


@pytest.mark.polite
def test_fetch_audit_retry_rule_normalises_the_url():
    for retry in (
        "https://WWW.NHS.UK/conditions/flu/",
        "https://www.nhs.uk:443/conditions/flu/",
        "https://www.nhs.uk/conditions/flu/#top",
    ):
        lines = [
            fa._line(status=403, outcome="blocked"),
            fa._line(url=retry, host="www.nhs.uk", at="2026-11-15T10:00:30+00:00"),
        ]
        assert any("after it was blocked" in p for p in fa.audit(lines)), retry


@pytest.mark.polite
def test_fetch_audit_applies_rules_across_files(tmp_path):
    a, b = tmp_path / "fetch_log_a.jsonl", tmp_path / "fetch_log_b.jsonl"
    a.write_text(fa._line() + "\n", encoding="utf-8")
    b.write_text(
        fa._line(at="2026-11-15T10:00:00.1+00:00", user_agent="Other/1") + "\n", encoding="utf-8"
    )
    problems = fa.audit_paths([a, b])
    assert any("0.100 s apart" in p for p in problems)
    assert any("different user agents" in p for p in problems)


@pytest.mark.polite
def test_fetch_audit_exempts_robots_txt_and_reports_sub_second_gaps_precisely():
    assert fa.audit([fa._line(url="https://www.nhs.uk/robots.txt", robots="disallowed")]) == []
    r = fa.audit([fa._line(), fa._line(at="2026-11-15T10:00:00.999999+00:00")])
    assert any("1.000 s apart" in p for p in r)  # 0.999999 s rounds up, and still fails


@pytest.mark.safety
@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("upper.JSON.GZ", gzip.compress(b'{"body": "x"}')),
        ("no_suffix", gzip.compress(b"<HTML>")),
        ("double.gz", gzip.compress(gzip.compress(b"<body>"))),
        ("escaped.json", b'{"a": "\\u003cbody class=x>"}'),
        ("keys.json", b'{"Page_Text": "x"}'),
    ],
)
def test_storage_audit_catches_disguised_bodies(tmp_path, name, content):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / name).write_bytes(content)
    assert any(name in p for p in sa.audit(tmp_path, tmp_path / "none", IDLE))


@pytest.mark.safety
def test_body_cache_follows_node_status_rules(tmp_path):
    cache = tmp_path / "c"
    cache.mkdir()
    (cache / "p.txt").write_text("x", encoding="utf-8")
    mixed = parse_catalog(HDR + "SUP-01\tM3.2\tgreen\t\t\nSUP-02\tM3.2\tspec\t\t\n")
    assert sa.cache_problem(cache, mixed) is None  # node_status calls this building
    assert sa.cache_problem(cache, IDLE) is not None


def test_proofs_gate_rejects_every_kind_of_skipped_test(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_s.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.skip\nclass TestC:\n    def test_cls(self):\n        pass\n\n"
        "class TestM:\n    pytestmark = pytest.mark.skip\n"
        "    def test_inner(self):\n        pass\n\n"
        "def test_rt():\n    pytest.skip('later')\n\n"
        "@pytest.mark.xfail(run=False)\ndef test_xf():\n    pass\n\n"
        "def test_real():\n    assert True\n",
        encoding="utf-8",
    )
    funcs = nc._test_functions(tmp_path / "tests" / "test_s.py")
    assert funcs == {
        "test_cls": True,
        "test_inner": True,
        "test_rt": True,
        "test_xf": True,
        "test_real": False,
    }


# ---- W0.1 verifier pass 2 ----


def test_skip_detection_has_no_false_positives_or_negatives(tmp_path):
    (tmp_path / "test_m.py").write_text(
        "import pytest\nfrom pytest import skip\n\n"
        '@pytest.mark.parametrize("mode", ["skip_header", "xfail_mode"])\n'
        "def test_param(mode):\n    assert mode\n\n"
        "def test_fail_branch():\n    if 1 + 1 != 2:\n        pytest.fail('maths broke')\n\n"
        "def test_bare_skip():\n    skip('later')\n\n"
        "class TestOuter:\n    class TestInner:\n"
        "        def test_nested(self):\n            pass\n",
        encoding="utf-8",
    )
    assert nc._test_functions(tmp_path / "test_m.py") == {
        "test_param": False,
        "test_fail_branch": False,
        "test_bare_skip": True,
        "test_nested": False,
    }


@pytest.mark.parametrize("bad", ["a\rb", "a\x0cb", "a\x85b", "a b", " lead", "trail "])
def test_catalog_writer_refuses_cells_it_could_not_read_back(tmp_path, bad):
    from harness_lib import HarnessError

    with pytest.raises(HarnessError):
        write_catalog([Cap("HAR-01", "W0.1", "green", bad, "n")], tmp_path / "c.tsv")


@pytest.mark.polite
def test_fetch_audit_pass_two_rules():
    skipped = {
        "robots": "disallowed",
        "outcome": "robots_disallowed",
        "status": None,
        "bytes": None,
    }
    later = "2026-11-15T10:00:05+00:00"
    assert any("robots refused" in p for p in fa.audit([fa._line(**skipped), fa._line(at=later)]))
    assert any("more than 2 retries" in p for p in fa.audit([fa._line(attempt=4)]))
    blocked = fa._line(status=401, outcome="blocked")
    assert any("after it was blocked" in p for p in fa.audit([blocked, fa._line(at=later)]))
    ipv6 = fa._line(url="https://[2001:db8::1]:8443/a", host="[2001:db8::1]")
    assert fa.audit([ipv6]) == []
    assert any("malformed url" in p for p in fa.audit([fa._line(url="https://[::1/x")]))


@pytest.mark.safety
def test_unpack_fails_closed_on_bombs_depth_and_encryption():
    import io
    import zipfile

    from harness_lib import MAX_UNPACKED, HarnessError, unpack

    with pytest.raises(HarnessError, match="MiB"):
        unpack(gzip.compress(b" " * (MAX_UNPACKED + 1)))
    deep = b"x"
    for _ in range(4):
        deep = gzip.compress(deep)
    with pytest.raises(HarnessError, match="nested"):
        unpack(deep)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", b"<html>")
    raw = bytearray(buf.getvalue())
    raw[6] |= 0x1  # mark the local header encrypted
    cd = raw.rfind(b"PK\x01\x02")
    raw[cd + 8] |= 0x1  # and the central directory entry
    with pytest.raises(HarnessError):
        unpack(bytes(raw))
    assert unpack(b"BZh is plain text") == b"BZh is plain text"


def test_gate_golden_never_passes_without_the_minimum_python(tmp_path, monkeypatch):
    (tmp_path / "test_g.py").write_text(
        "import pytest\n\n@pytest.mark.golden\ndef test_g():\n    pass\n", encoding="utf-8"
    )
    monkeypatch.setattr(nc.shutil, "which", lambda _name: None)
    r = nc.gate_golden(nc.Ctx("W0.1", tmp_path, {}, [], tmp_path))
    assert r.status == "FAIL" and "uv not found" in r.detail
