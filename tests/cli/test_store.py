import gzip
import json
import math
import threading

import pytest

from citewatch.store import RawStore, StoreError, canonical_json, stage_key

H = "0123456789abcdef"


def test_keys_are_stable_under_dict_order_and_change_with_the_run():
    a = stage_key("ask", "1", {"run": 1, "question_id": "v-001", "model": "m"}, H, H)
    b = stage_key("ask", "1", {"model": "m", "question_id": "v-001", "run": 1}, H, H)
    c = stage_key("ask", "1", {"run": 2, "question_id": "v-001", "model": "m"}, H, H)
    assert a == b and a != c and len(a) == 64
    assert stage_key("ask", "2", {"run": 1}, H) != stage_key("ask", "1", {"run": 1}, H)
    assert stage_key("ask", "1", {"run": 1}, H, "p1") != stage_key("ask", "1", {"run": 1}, H, "p2")


def test_canonical_json_rejects_nan_and_non_string_keys():
    assert canonical_json({"b": 1, "a": [1.5, "é"]}) == '{"a":[1.5,"é"],"b":1}'.encode()
    with pytest.raises(StoreError):
        canonical_json({"x": math.nan})
    with pytest.raises(StoreError):
        canonical_json({1: "x"})


def test_put_get_round_trip_and_layout(tmp_path):
    store = RawStore(tmp_path)
    key = stage_key("ask", "1", {"run": 1}, H)
    assert store.put("ask", key, {"answer": "x", "n": 2}) is True
    assert store.get("ask", key) == {"answer": "x", "n": 2}
    p = tmp_path / "data" / "raw" / "ask" / key[:2] / f"{key}.json.gz"
    assert p.is_file() and json.loads(gzip.decompress(p.read_bytes())) == {"answer": "x", "n": 2}
    assert list(store.keys("ask")) == [key]
    with pytest.raises(KeyError):
        store.get("ask", "f" * 64)


def test_first_writer_wins_and_bytes_are_deterministic(tmp_path):
    store = RawStore(tmp_path)
    key = "a" * 64
    assert store.put("fetch", key, {"v": 1}) is True
    assert store.put("fetch", key, {"v": 2}) is False
    assert store.get("fetch", key) == {"v": 1}
    other = RawStore(tmp_path / "b")
    other.put("fetch", key, {"v": 1})
    assert store.path("fetch", key).read_bytes() == other.path("fetch", key).read_bytes()


def test_concurrent_writers_leave_one_complete_object(tmp_path):
    store = RawStore(tmp_path)
    key = "b" * 64
    results = []

    def write(i):
        results.append(store.put("ask", key, {"writer": i, "pad": "x" * 10000}))

    threads = [threading.Thread(target=write, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    assert store.get("ask", key)["pad"] == "x" * 10000
    leftovers = list((tmp_path / "data" / "raw" / "ask").rglob(".tmp-*"))
    assert leftovers == []


@pytest.mark.parametrize("stage", ["Ask", "../x", "", "a/b"])
def test_bad_stage_names(tmp_path, stage):
    with pytest.raises(StoreError):
        RawStore(tmp_path).path(stage, "a" * 64)


@pytest.mark.parametrize("key", ["A" * 64, "a" * 63, "../" + "a" * 61])
def test_bad_keys(tmp_path, key):
    with pytest.raises(StoreError):
        RawStore(tmp_path).put("ask", key, {})


@pytest.mark.safety
def test_store_writes_only_under_data_raw(tmp_path):
    store = RawStore(tmp_path)
    store.put("ask", "c" * 64, {"x": 1})
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files and all(p.is_relative_to(tmp_path / "data" / "raw") for p in files)
