from pathlib import Path

import fetch_audit
import node_converge as nc
from harness_lib import PROOF_DIMENSIONS, parse_catalog, parse_graph

HDR = "cap_id\tnode\tstatus\tproof\tnote\n"
GRAPH = parse_graph("| **W0.1** | Harness | — |\n| **N1.1** | Schemas | W0.1 |\n")


def ctx(tmp: Path, rows: str, node: str = "W0.1") -> nc.Ctx:
    return nc.Ctx(node, tmp, GRAPH, parse_catalog(HDR + rows), tmp / "specs")


def test_self_test_shows_every_gate_can_fail():
    assert nc.self_test() == 0


def test_twelve_gates_in_documented_order():
    assert [name for name, _ in nc.GATES] == [
        "claims-work",
        "eligibility",
        "proofs",
        "ruff",
        "pyright",
        "pytest",
        "golden",
        "politeness",
        "safety",
        "build",
        "changed-tests",
        "records",
    ]


def test_claims_work(tmp_path):
    assert nc.gate_claims_work(ctx(tmp_path, "H\tW0.1\tnot-started\t\t\n")).status == "FAIL"
    assert nc.gate_claims_work(ctx(tmp_path, "H\tW0.1\tgreen\t\t\n")).status == "PASS"


def test_proof_must_cover_all_five_dimensions(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_a(): pass\n", encoding="utf-8")
    full = "; ".join(f'{d}=tests/t.py›"test_a"' for d in PROOF_DIMENSIONS)
    assert nc.gate_proofs(ctx(tmp_path, f"H\tW0.1\tgreen\t{full}\t\n")).status == "PASS"
    partial = full.rsplit(";", 1)[0]
    r = nc.gate_proofs(ctx(tmp_path, f"H\tW0.1\tgreen\t{partial}\t\n"))
    assert r.status == "FAIL" and "missing safety proof" in r.detail


def test_proof_rejects_unknown_keys_and_bad_format(tmp_path):
    (tmp_path / "t.py").write_text("def test_a(): pass\n", encoding="utf-8")
    full = "; ".join(f'{d}=t.py›"test_a"' for d in PROOF_DIMENSIONS)
    r = nc.gate_proofs(ctx(tmp_path, f"H\tW0.1\tgreen\t{full}; vibes=n/a:looks fine to me\t\n"))
    assert r.status == "FAIL" and "unknown proof keys" in r.detail
    r = nc.gate_proofs(ctx(tmp_path, "H\tW0.1\tgreen\tlogical=t.py test_a\t\n"))
    assert r.status == "FAIL"


def test_pytest_no_tests_is_skip_not_pass(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    assert nc._pytest(tmp_path, "golden", "golden").status == "SKIP"
    assert nc._pytest(tmp_path, "not golden", "unit").status == "PASS"


def test_changed_tests_rule():
    assert nc.changed_tests_problem(["scripts/node_start.py"]) is not None
    assert nc.changed_tests_problem(["docs/decisions.md"]) is None
    assert nc.changed_tests_problem(["src/citewatch/a.py", "tests/test_a.py"]) is None


def test_records_require_changelog_criteria_and_run_state(tmp_path):
    caps = parse_catalog(HDR + "H-1\tW0.1\tgreen\t\t\n")
    problems = nc.records_problems("W0.1", caps, tmp_path, tmp_path / "specs")
    assert "changelog.md has no [W0.1] entry" in problems


def test_a_crashing_gate_counts_as_failure(monkeypatch, capsys):
    def boom(_ctx):
        raise RuntimeError("kaput")

    monkeypatch.setattr(nc, "GATES", [("boom", boom)])
    assert nc.main(["W0.1", "--no-log"]) == 1
    assert "gate crashed" in capsys.readouterr().out


def _proof(test: str, path: str = "tests/test_p.py") -> str:
    return "; ".join(f'{d}={path}›"{test}"' for d in PROOF_DIMENSIONS)


def test_proofs_require_a_real_unskipped_test_function(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_p.py").write_text(
        "import pytest\n# test_comment\nX = 'test_string'\n"
        "def test_abcdef():\n    pass\n"
        "@pytest.mark.skipif(True, reason='x')\ndef test_skipped():\n    pass\n"
        "class TestGroup:\n    def test_method(self):\n        pass\n",
        encoding="utf-8",
    )
    passes = ["test_abcdef", "test_method"]
    fails = ["test_comment", "test_string", "test_abc", "test_skipped"]
    for name in passes:
        assert nc.gate_proofs(ctx(tmp_path, f"H\tW0.1\tgreen\t{_proof(name)}\t\n")).status == "PASS"
    for name in fails:
        r = nc.gate_proofs(ctx(tmp_path, f"H\tW0.1\tgreen\t{_proof(name)}\t\n"))
        assert r.status == "FAIL", name


def test_proofs_must_live_under_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "README.md").write_text("def test_a(): pass\n", encoding="utf-8")
    (tmp_path / "tests" / "test_p.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    for path in ("README.md", "tests/../README.md", "/etc/hosts"):
        r = nc.gate_proofs(ctx(tmp_path, f"H\tW0.1\tgreen\t{_proof('test_a', path)}\t\n"))
        assert r.status == "FAIL", path


def test_logical_proof_cannot_be_na_and_keys_cannot_repeat(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_p.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    na = _proof("test_a").replace(
        'logical=tests/test_p.py›"test_a"', "logical=n/a:no logic here at all"
    )
    assert nc.gate_proofs(ctx(tmp_path, f"H\tW0.1\tgreen\t{na}\t\n")).status == "FAIL"
    dup = _proof("test_a") + '; logical=tests/test_p.py›"test_a"'
    assert nc.gate_proofs(ctx(tmp_path, f"H\tW0.1\tgreen\t{dup}\t\n")).status == "FAIL"


def test_changed_tests_fails_on_unknown_base(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "a",
        ],
        cwd=tmp_path,
        check=True,
    )
    d = tmp_path / "specs" / "W0.1-x"
    d.mkdir(parents=True)
    (d / ".base").write_text("deadbeef\n", encoding="utf-8")
    r = nc.gate_changed_tests(ctx(tmp_path, "H\tW0.1\tbuilding\t\t\n"))
    assert r.status == "FAIL" and "deadbeef" in r.detail


def test_politeness_gate_fails_on_a_rude_fetch_log(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "fetch_log.jsonl").write_text(
        fetch_audit._line() + "\n" + fetch_audit._line(at="2026-11-15T10:00:00.2+00:00") + "\n",
        encoding="utf-8",
    )
    r = nc.gate_politeness(ctx(tmp_path, "H\tW0.1\tbuilding\t\t\n"))
    assert r.status == "FAIL" and "0.200 s apart" in r.detail


def test_politeness_gate_skips_without_logs_or_tests(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    assert nc.gate_politeness(ctx(tmp_path, "H\tW0.1\tbuilding\t\t\n")).status == "SKIP"


def test_safety_gate_fails_on_a_stored_body_and_a_full_cache(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.json").write_text('{"body": "<p>"}', encoding="utf-8")
    r = nc.gate_safety(ctx(tmp_path, "H\tW0.1\tbuilding\t\t\n"), cache=tmp_path / "none")
    assert r.status == "FAIL" and "x.json" in r.detail
    (tmp_path / "data" / "x.json").unlink()
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "p.txt").write_text("text", encoding="utf-8")
    r = nc.gate_safety(ctx(tmp_path, "H\tW0.1\tbuilding\t\t\n"), cache=cache)
    assert r.status == "FAIL" and "body cache" in r.detail


def test_build_smoke_runs_the_citewatch_cli():
    assert (["citewatch", "--version"], 0) in nc.SMOKE_COMMANDS


def test_smoke_commands_run_without_provider_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = nc.keyless_env()
    assert "ANTHROPIC_API_KEY" not in env and "OPENAI_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"
