"""CIT-04, CIT-05: canonical URLs and publishers."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from citewatch.extract import UrlError, canonical_url, publisher_of
from citewatch.schemas._base import canonical_problems


@pytest.mark.parametrize(
    ("raw", "canon"),
    [
        ("HTTPS://WWW.NHS.UK/Conditions/Flu/", "https://www.nhs.uk/Conditions/Flu/"),
        ("https://www.nhs.uk/a?utm_source=openai", "https://www.nhs.uk/a"),
        ("https://a.example:443/p#frag", "https://a.example/p"),
        ("http://a.example:80/", "http://a.example/"),
        ("http://a.example:8080/x", "http://a.example:8080/x"),
        ("https://a.example/p?b=2&gclid=x&a=1&utm_medium=y", "https://a.example/p?b=2&a=1"),
        ("https://a.example/p?FBCLID=1&q=", "https://a.example/p?q="),
        ("https://a.example", "https://a.example/"),
        ("https://u:pw@a.example/p", "https://a.example/p"),
        ("https://bücher.example/a b".replace(" ", "%20"), "https://xn--bcher-kva.example/a%20b"),
        ("https://a.example/%7Euser", "https://a.example/~user"),
        ("https://a.example./p", "https://a.example/p"),
        ("https://a.example/%2541?v=%2541", "https://a.example/%2541?v=%2541"),
        ("https://a.example/p?v=a+b&w=%2B", "https://a.example/p?v=a%20b&w=%2B"),
    ],
)
def test_canonical_url(raw, canon):
    assert canonical_url(raw) == canon
    assert canonical_problems(canonical_url(raw)) == []


@pytest.mark.parametrize(
    "bad",
    ["mailto:a@b.c", "ftp://a.example/x", "https:///p", "https://a .example/", "javascript:x"],
)
def test_non_web_urls_are_refused(bad):
    with pytest.raises(UrlError):
        canonical_url(bad)


_seg = st.text(
    alphabet=st.characters(codec="utf-8", exclude_categories=("Cs", "Cc", "Zs", "Zl", "Zp")),
    max_size=8,
)


@settings(max_examples=300, deadline=None)
@given(
    scheme=st.sampled_from(["http", "https", "HTTP", "Https"]),
    host=st.from_regex(
        r"[a-zA-Z][a-zA-Z0-9-]{0,10}\.(com|org|nhs\.uk|co\.uk|example)", fullmatch=True
    ),
    port=st.sampled_from(["", ":80", ":443", ":8443"]),
    path=st.lists(_seg, max_size=4),
    query=st.lists(st.tuples(st.sampled_from(["a", "utm_x", "gclid", "q", "B"]), _seg), max_size=4),
    frag=st.sampled_from(["", "#x", "#"]),
)
def test_canonical_url_is_idempotent(scheme, host, port, path, query, frag):
    from urllib.parse import quote

    url = f"{scheme}://{host}{port}/" + "/".join(quote(p, safe="") for p in path)
    if query:
        url += "?" + "&".join(f"{k}={quote(v, safe='')}" for k, v in query)
    url += frag
    once = canonical_url(url)
    assert canonical_url(once) == once and canonical_problems(once) == []
    from urllib.parse import parse_qsl, urlsplit

    keys = [k.lower() for k, _ in parse_qsl(urlsplit(once).query, keep_blank_values=True)]
    assert not any(k.startswith("utm_") or k == "gclid" for k in keys) and "#" not in once


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.nhs.uk/conditions/flu/", ("nhs.uk", None)),
        ("https://nhs.uk/", ("nhs.uk", None)),
        ("https://www.guysandstthomas.nhs.uk/x", ("guysandstthomas.nhs.uk", "nhs.uk")),
        ("https://www.nhsbsa.nhs.uk/help", ("nhsbsa.nhs.uk", "nhs.uk")),
        ("https://www.gov.uk/guidance", ("gov.uk", None)),
        ("https://www.bbc.co.uk/news", ("bbc.co.uk", None)),
        ("https://www.ucl.ac.uk/research", ("ucl.ac.uk", "ac.uk")),
        ("https://my.clevelandclinic.org/health", ("clevelandclinic.org", None)),
        ("example.com", ("example.com", None)),
        ("https://www.met.police.uk/", ("met.police.uk", "police.uk")),
        ("https://127.0.0.1/x", ("127.0.0.1", None)),
    ],
)
def test_publisher_of_follows_d4(url, expected):
    assert publisher_of(url) == expected


@settings(max_examples=200, deadline=None)
@given(
    host=st.from_regex(
        r"([a-z0-9]{1,8}\.){0,3}(nhs\.uk|gov\.uk|ac\.uk|co\.uk|com|org)", fullmatch=True
    )
)
def test_publisher_of_is_stable_and_a_parent_of_the_host(host):
    pub, group = publisher_of(host)
    assert publisher_of(pub if group is None else host) == (pub, group) or group is not None
    assert host == pub or host.endswith("." + pub) or host == "www." + pub
    assert publisher_of(f"https://{host}/x?y=1") == (pub, group)


def test_publisher_needs_no_network(monkeypatch):
    import socket

    def no_net(*a, **k):
        raise AssertionError("publisher_of tried the network")

    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(socket, "getaddrinfo", no_net)
    from citewatch.extract import urls

    urls._extractor.cache_clear()
    assert publisher_of("https://www.bbc.co.uk/") == ("bbc.co.uk", None)
