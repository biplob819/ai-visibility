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


# ---- W0.1 verifier pass 3: mutants that survived every test ----


def test_eligibility_rules_that_had_no_test():
    from harness_lib import HarnessError, eligibility_problems, parse_graph

    graph = parse_graph("| **W0.1** | A | — |\n| **N1.1** | B | W0.1 |\n")
    caps = parse_catalog(HDR + "H\tW0.1\tbuilding\t\t\nS\tN1.1\tgreen\t\t\n")
    assert any("N1.1" in p and "W0.1" in p for p in eligibility_problems(graph, caps))
    with pytest.raises(HarnessError):
        parse_graph("| **W0.1** | A | — |\n| **W0.1** | again | — |\n")
    with pytest.raises(HarnessError):
        parse_graph("| **W0.1** | A | — |\n| **N1.1** | B | W0.1x |\n")
    with pytest.raises(HarnessError):
        parse_catalog(HDR + "H\tW0.1\tgreen\t\t\nH\tW0.1\tgreen\t\t\n")


@pytest.mark.safety
def test_unpack_handles_xz_nested_zip_and_a_shared_zip_budget(monkeypatch):
    import io
    import lzma
    import zipfile

    import harness_lib
    from harness_lib import HarnessError, unpack

    filler = b"compressible filler " * 500
    assert unpack(lzma.compress(filler + b"MARK")).endswith(b"MARK")
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inner.txt", filler + b"DEEP")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inner.zip", inner.getvalue())
    assert b"DEEP" in unpack(outer.getvalue())
    two = io.BytesIO()
    with zipfile.ZipFile(two, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", b"a" * 6000)
        zf.writestr("b.txt", b"b" * 6000)
    monkeypatch.setattr(harness_lib, "MAX_UNPACKED", 10_000)
    monkeypatch.setattr(harness_lib, "CHUNK", 1000)
    with pytest.raises(HarnessError):
        unpack(two.getvalue(), budget=10_000)  # 12,000 bytes across members > 10,000


@pytest.mark.polite
def test_fetch_audit_field_types_and_unreadable_logs(tmp_path):
    assert any("url must be" in p for p in fa.audit([fa._line(url=42)]))
    assert any("attempt must be" in p for p in fa.audit([fa._line(attempt=True)]))
    assert any("user_agent must be" in p for p in fa.audit([fa._line(user_agent="")]))
    bad = tmp_path / "fetch_log.jsonl"
    bad.write_bytes(b"\xff\xfe\x00 not utf-8")
    assert any("cannot read" in p for p in fa.audit_paths([bad]))
    assert any(
        "requested 4 times" in p
        for p in fa.audit([fa._line(at=f"2026-11-15T10:00:0{i}+00:00") for i in range(0, 8, 2)])
    )
    assert fa.audit([fa._line(host="www.nhs.uk:443")]) == []


@pytest.mark.safety
def test_secret_scan_reports_unreadable_archives_and_ignores_slugs(tmp_path):
    (tmp_path / "x.gz").write_bytes(b"\x1f\x8b broken")
    (tmp_path / "c.jsonl").write_text(
        '{"url": "https://x.org/what-is-sk-ii-facial-treatment-essence-and-how-to-use-it"}\n',
        encoding="utf-8",
    )
    hits = secret_scan.scan([tmp_path / "x.gz", tmp_path / "c.jsonl"])
    assert len(hits) == 1 and "cannot unpack" in hits[0]


@pytest.mark.safety
@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("labels.csv", b"citation_ref,verdict,page_text\nv-1,supported,x\n"),
        ("notes.yaml", b"url: https://x.org\nbody: x\n"),
        ("double.json", b'{"rec": "{\\"html\\": 1}"}'),
    ],
)
def test_storage_audit_catches_csv_yaml_and_double_encoded_keys(tmp_path, name, content):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / name).write_bytes(content)
    assert any(name in p for p in sa.audit(tmp_path, tmp_path / "none", IDLE))


# ---- W0.1 verifier pass 4: pin every non-equivalent surviving mutant ----


def _git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)

    def commit(msg="c"):
        subprocess.run(["git", "add", "-A"], cwd=path, check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg],
            cwd=path,
            check=True,
        )

    return commit


@pytest.mark.safety
def test_tracked_files_are_scanned_and_audited(tmp_path):
    from harness_lib import git_files

    commit = _git_repo(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "k.py").write_text("K = 'sk-ant-" + "Q" * 40 + "'\n", encoding="utf-8")
    (tmp_path / "data" / "p.html").write_text("<html>", encoding="utf-8")
    commit()
    files = git_files(tmp_path)
    assert files is not None and tmp_path / "k.py" in files  # tracked, not only untracked
    assert secret_scan.scan(secret_scan.candidate_files(tmp_path))
    assert any("p.html" in p for p in sa.audit(tmp_path, tmp_path / "none", IDLE))


@pytest.mark.safety
def test_cli_exit_codes_that_ci_and_pre_commit_rely_on(tmp_path, monkeypatch, capsys):
    import node_start
    import verify_graph_eligibility as vge

    leak = tmp_path / "leak.py"
    leak.write_text("K = 'sk-ant-" + "Q" * 40 + "'\n", encoding="utf-8")
    assert secret_scan.main([str(leak)]) == 1

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "p.html").write_text("<html>", encoding="utf-8")
    cat = tmp_path / "catalog.tsv"
    cat.write_text(HDR + "SUP-01\tM3.2\tnot-started\t\t\n", encoding="utf-8")
    monkeypatch.setattr(sa, "ROOT", tmp_path)
    monkeypatch.setattr(sa, "CATALOG_TSV", cat)
    monkeypatch.setenv("CITEWATCH_BODY_CACHE", str(tmp_path / "none"))
    assert sa.main([]) == 1

    assert vge.main(["--graph", str(tmp_path / "missing.md")]) == 1

    graph = tmp_path / "graph.md"
    graph.write_text("| **W0.1** | A | — |\n| **N1.1** | B | W0.1 |\n", encoding="utf-8")
    cat2 = tmp_path / "cat2.tsv"
    cat2.write_text(HDR + "H\tW0.1\tbuilding\t\t\nS\tN1.1\tspec\t\t\n", encoding="utf-8")
    before = cat2.read_bytes()
    rc = node_start.start(
        "N1.1",
        graph_path=graph,
        catalog_path=cat2,
        specs=tmp_path / "specs",
        root=tmp_path,
        mark_building=True,
    )
    assert rc == 1 and cat2.read_bytes() == before  # refused, and nothing flipped

    monkeypatch.setattr(nc, "ROOT", tmp_path)
    monkeypatch.setattr(nc, "load_graph", lambda: {"W0.1": None})
    monkeypatch.setattr(nc, "load_catalog", lambda: [])
    monkeypatch.setattr(nc, "GATES", [("x", lambda _c: nc.Result("FAIL", "planted"))])
    assert nc.main(["W0.1"]) == 1  # the default (logging) path
    assert list((tmp_path / ".harness" / "W0.1").glob("converge-*.txt"))


def test_node_start_flips_only_this_nodes_unstarted_rows(tmp_path):
    import node_start

    graph = tmp_path / "graph.md"
    graph.write_text("| **W0.1** | A | — |\n| **N1.1** | B | W0.1 |\n", encoding="utf-8")
    cat = tmp_path / "cat.tsv"
    cat.write_text(
        HDR + "H\tW0.1\tgreen\t\t\nS1\tN1.1\tspec\t\t\nS2\tN1.1\tgreen\t\t\n", encoding="utf-8"
    )
    specs = tmp_path / "specs" / "N1.1-x"
    specs.mkdir(parents=True)
    for f in ("criteria.md", "tasks.md"):
        (specs / f).write_text("S1 S2\n", encoding="utf-8")
    assert node_start.check_start(
        "N1.1", node_start.load_graph(graph), load_catalog(cat), tmp_path / "specs"
    ) == ["missing specs/N1.1-x/spec.md"]
    (specs / "spec.md").write_text("spec\n", encoding="utf-8")
    _git_repo(tmp_path)
    assert (
        node_start.start(
            "N1.1",
            graph_path=graph,
            catalog_path=cat,
            specs=tmp_path / "specs",
            root=tmp_path,
            mark_building=True,
        )
        == 0
    )
    status = {c.cap_id: c.status for c in load_catalog(cat)}
    assert status == {"H": "green", "S1": "building", "S2": "green"}


def test_changed_tests_rules_for_base_none_non_git_and_fixtures(tmp_path):
    commit = _git_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    commit()
    ctx = nc.Ctx("W0.1", tmp_path, {}, [], tmp_path / "specs")
    assert nc.gate_changed_tests(ctx).status == "PASS"  # base none: every file counts
    assert nc.changed_tests_problem(["src/a.py", "tests/fixtures/x.json"], tmp_path)
    assert nc.changed_tests_problem(["src/a.py", "tests/conftest.py"]) is None
    other = tmp_path.parent / f"{tmp_path.name}-nogit"
    other.mkdir()
    assert nc.gate_changed_tests(nc.Ctx("W0.1", other, {}, [], other)).status == "SKIP"


def test_graph_and_marker_edge_cases():
    from harness_lib import HarnessError, parse_graph

    with pytest.raises(HarnessError):
        parse_graph("| **W0.1x** | bad id | — |\n")
    with pytest.raises(HarnessError, match="no node rows"):
        parse_graph("nothing here\n")
    assert not mentions("har-01", "HAR-01")
    assert sa.HTML_MARKERS.search(b"<html/>") and sa.HTML_MARKERS.search(b"ends <body")


def test_catalog_keeps_cells_that_start_with_a_quote(tmp_path):
    caps = [Cap("HAR-01", "W0.1", "green", '"quoted" start', "note")]
    write_catalog(caps, tmp_path / "c.tsv")
    assert load_catalog(tmp_path / "c.tsv")[0].proof == '"quoted" start'
    with pytest.raises(Exception, match="tab"):
        write_catalog([Cap("HAR-01", "W0.1", "green", "a\tb", "n")], tmp_path / "d.tsv")


def test_proofs_gate_rejects_skips_that_pytest_honours(tmp_path):
    files = {
        "test_mod_skip.py": "import pytest\npytest.importorskip('nope')\n\n"
        "def test_a():\n    pass\n",
        "test_mod_skip2.py": "import pytest\npytest.skip('x', allow_module_level=True)\n\n"
        "def test_a():\n    pass\n",
        "test_misc.py": "import pytest\nimport unittest\nfrom unittest import skip as uskip\n"
        "from pytest import mark as mk\nfrom _pytest.outcomes import skip as oskip\n"
        "later = pytest.mark.skip\n\n"
        "@uskip('x')\ndef test_u():\n    pass\n\n"
        "@mk.skip\ndef test_mk():\n    pass\n\n"
        "@later\ndef test_later():\n    pass\n\n"
        "def test_raise():\n    raise unittest.SkipTest('x')\n\n"
        "def test_raise2():\n    raise pytest.skip.Exception('x')\n\n"
        "def test_outcomes():\n    oskip('x')\n\n"
        "class TestSelf(unittest.TestCase):\n    def test_s(self):\n        self.skipTest('x')\n\n"
        "class TestOff:\n    __test__ = False\n    def test_off(self):\n        pass\n\n"
        "class TestInit:\n    def __init__(self):\n        pass\n    def test_init(self):\n"
        "        pass\n\n"
        "def helper():\n    pass\n\n"
        "def test_real():\n    pass\n",
    }
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    assert nc._test_functions(tmp_path / "test_mod_skip.py") == {"test_a": True}
    assert nc._test_functions(tmp_path / "test_mod_skip2.py") == {"test_a": True}
    found = nc._test_functions(tmp_path / "test_misc.py")
    assert found == {
        "test_u": True,
        "test_mk": True,
        "test_later": True,
        "test_raise": True,
        "test_raise2": True,
        "test_outcomes": True,
        "test_s": True,
        "test_off": True,
        "test_real": False,
    }  # helper() and TestInit's methods are not collected by pytest


def test_proof_entries_need_a_py_file_and_a_well_formed_value(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_p.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests" / "notes.txt").write_text("def test_a():\n    pass\n", encoding="utf-8")
    good = "; ".join(f'{d}=tests/test_p.py›"test_a"' for d in nc.PROOF_DIMENSIONS)
    ctx = lambda proof: nc.Ctx(  # noqa: E731
        "W0.1", tmp_path, {}, parse_catalog(HDR + f"H\tW0.1\tgreen\t{proof}\t\n"), tmp_path
    )
    assert nc.gate_proofs(ctx(good)).status == "PASS"
    assert nc.gate_proofs(ctx(good.replace("test_p.py", "notes.txt", 1))).status == "FAIL"
    assert nc.gate_proofs(ctx(good.replace('›"test_a"', " test_a", 1))).status == "FAIL"


# ---- W0.1 verifier pass 5 ----


@pytest.mark.safety
def test_prose_in_stored_answers_never_trips_the_header_rule(tmp_path):
    (tmp_path / "data" / "raw" / "ask" / "ab").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "ask" / "ab" / "abcd.json.gz").write_bytes(
        gzip.compress(b'{"answer_text": "Good for your mind, body, and mood."}')
    )
    (tmp_path / "data" / "labels.csv").write_text(
        "citation_ref,where_found\nv-1,body\n", encoding="utf-8"
    )
    assert sa.audit(tmp_path, tmp_path / "none", IDLE) == []
    (tmp_path / "data" / "sheet.tsv.gz").write_bytes(gzip.compress(b"ref\tpage_text\nv-1\tx\n"))
    assert any("sheet.tsv.gz" in p for p in sa.audit(tmp_path, tmp_path / "none", IDLE))


def test_pass_five_survivors_are_pinned(tmp_path, monkeypatch):
    import io
    import zipfile

    from harness_lib import unpack

    monkeypatch.setenv("SOME_SECRET", "x")
    assert "SOME_SECRET" not in nc.keyless_env()
    upper = "CITEWATCH/0.1.0 (+https://example.org; study@example.org)"
    lines = [fa._line(), fa._line(host="a.com", url="https://a.com/", user_agent=upper)]
    assert any("different user agents" in p for p in fa.audit(lines))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", b"clean " * 100)
        zf.writestr("b.txt", b"x <html> y " * 10)
    assert b"<html>" in unpack(buf.getvalue())
    f = tmp_path / "doc.md"
    key = "sk-ant-" + "Q" * 40
    f.write_text(f"example {key}  # secret-scan: allow\nreal = '{key}'\n", encoding="utf-8")
    hits = secret_scan.scan([f])
    assert len(hits) == 1 and ":2:" in hits[0]


@pytest.mark.safety
def test_pipe_separated_headers_count_and_txt_prose_does_not(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "notes.txt").write_text("Mind, body, and soul\n", encoding="utf-8")
    assert sa.audit(tmp_path, tmp_path / "none", IDLE) == []
    (tmp_path / "data" / "t.psv").write_text("ref|body\nv-1|x\n", encoding="utf-8")
    assert any("t.psv" in p for p in sa.audit(tmp_path, tmp_path / "none", IDLE))
