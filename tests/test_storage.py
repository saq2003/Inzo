"""Storage backend tests: SQLite KV and document stores (stdlib only)."""

from __future__ import annotations

from storage.sqlite_store import SQLiteDocumentStore, SQLiteKVStore


def test_kv_roundtrip(tmp_path):
    store = SQLiteKVStore(tmp_path / "kv.db")
    assert store.get("missing") is None
    store.put("k", "v1")
    assert store.get("k") == "v1"
    store.put("k", "v2")
    assert store.get("k") == "v2"
    assert store.count() == 1
    assert store.delete("k") is True
    assert store.delete("k") is False
    assert store.count() == 0


def test_document_store_roundtrip_and_search(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "docs.db")
    doc_id = store.add({"text": "inzo likes blueberry pancakes", "kind": "note"})
    fetched = store.get(doc_id)
    assert fetched is not None
    assert fetched["text"] == "inzo likes blueberry pancakes"
    assert fetched["id"] == doc_id

    store.add({"text": "unrelated quantum fact", "kind": "note"})
    hits = store.search("blueberry pancakes")
    assert len(hits) == 1
    assert hits[0]["id"] == doc_id
    assert store.count() == 2
