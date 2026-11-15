import pytest

import fetch_audit as fa

pytestmark = pytest.mark.polite


def test_self_test_covers_every_rule():
    assert fa.self_test() == 0


def test_robots_request_and_page_one_second_apart_pass():
    lines = [
        fa._line(url="https://www.nhs.uk/robots.txt"),
        fa._line(at="2026-11-15T10:00:01+00:00"),
    ]
    assert fa.audit(lines) == []


def test_robots_txt_requests_count_toward_the_rate():
    lines = [
        fa._line(url="https://www.nhs.uk/robots.txt"),
        fa._line(at="2026-11-15T10:00:00.300000+00:00"),
    ]
    assert any("0.300 s apart" in p for p in fa.audit(lines))


def test_a_skipped_disallowed_url_is_not_a_request():
    lines = [
        fa._line(),
        fa._line(
            url="https://www.nhs.uk/private/",
            at="2026-11-15T10:00:00.100000+00:00",
            robots="disallowed",
            outcome="robots_disallowed",
            status=None,
        ),
    ]
    assert fa.audit(lines) == []


def test_hosts_are_rated_independently():
    lines = [
        fa._line(),
        fa._line(url="https://www.bbc.co.uk/", host="www.bbc.co.uk"),
    ]
    assert fa.audit(lines) == []


def test_retry_after_451_fails():
    lines = [
        fa._line(status=451, outcome="blocked"),
        fa._line(at="2026-11-15T10:01:00+00:00", attempt=2),
    ]
    assert any("after it was blocked" in p for p in fa.audit(lines))


def test_main_skips_without_logs(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fa, "ROOT", tmp_path)
    assert fa.main([]) == 0
    assert "SKIP" in capsys.readouterr().out


def test_main_fails_on_a_bad_log(tmp_path, capsys):
    log = tmp_path / "fetch_log.jsonl"
    log.write_text(fa._line(robots="disallowed") + "\n", encoding="utf-8")
    assert fa.main([str(log)]) == 1
    assert "FAIL" in capsys.readouterr().out
