"""The fetcher against a real HTTP server on 127.0.0.1: real sockets, the real 1 s limiter on
wall-clock time, streamed bodies and a decompression bomb (FET-02, FET-06, FET-08)."""

import gzip
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from citewatch.fetch import FetchLog, PoliteClient, fetch_key, fetch_pages
from citewatch.store import RawStore

from .web import UA, audit

pytestmark = pytest.mark.polite

BOMB = gzip.compress(b"<html>" + b" " * 3_000_000)
SEEN: list[tuple[str, str]] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # quiet
        pass

    def do_GET(self):
        SEEN.append((self.path, self.headers.get("User-Agent", "")))
        if self.path == "/robots.txt":
            body, ctype, extra = b"User-agent: *\nDisallow: /private\n", "text/plain", {}
        elif self.path == "/bomb":
            body, ctype, extra = BOMB, "text/html", {"Content-Encoding": "gzip"}
        elif self.path == "/moved":
            self.send_response(301)
            self.send_header("Location", "/ok")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        else:
            body, ctype, extra = b"<html><body><p>fine</p></body></html>", "text/html", {}
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        for k, v in extra.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    SEEN.clear()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_a_real_server_is_fetched_politely(tmp_path, server):
    store = RawStore(tmp_path)
    log = FetchLog(tmp_path / "data" / "fetch_log.jsonl")
    client = PoliteClient(UA, log, store=store, max_page_bytes=1_000_000)
    urls = [f"{server}/moved", f"{server}/private/x", f"{server}/bomb"]
    try:
        res = fetch_pages(urls, client=client, store=store)
    finally:
        client.close()
    outs = {u: store.get("fetch", fetch_key(u))["outcome"] for u in urls}
    assert outs == {
        f"{server}/moved": "ok",
        f"{server}/private/x": "robots_disallowed",
        f"{server}/bomb": "too_large",  # decoded size counts, not the 3 KB on the wire
    }
    assert res.fetched == 3
    assert [p for p, _ in SEEN] == ["/robots.txt", "/moved", "/ok", "/bomb"]  # never /private/x
    assert {ua for _, ua in SEEN} == {UA}
    assert audit(log) == []  # real wall-clock times, at least 1.0 s apart
