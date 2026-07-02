"""Tests for the long-lived knowledge-pack retriever + SQLite pool (Fix #7)."""
from __future__ import annotations

import sqlite3

import pytest

from app.services.knowledge_packs.retriever import KnowledgePackRetriever
from app.services.memory import (
    get_knowledge_retriever,
    reset_knowledge_retriever,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_knowledge_retriever()
    yield
    reset_knowledge_retriever()


def _empty_pack(tmp_path, name: str = "empty.pack.sqlite") -> str:
    """A pack file with no card tables — search() handles this gracefully."""
    p = tmp_path / name
    sqlite3.connect(str(p)).close()
    return str(p)


class TestRetrieverSingleton:
    def test_same_pack_set_returns_same_instance(self, tmp_path):
        p = _empty_pack(tmp_path)
        r1 = get_knowledge_retriever([p])
        r2 = get_knowledge_retriever([p])
        assert r1 is r2

    def test_changed_pack_set_rebuilds_and_closes_old(self, tmp_path):
        p1 = _empty_pack(tmp_path, "pack1.sqlite")
        p2 = _empty_pack(tmp_path, "pack2.sqlite")
        r1 = get_knowledge_retriever([p1])
        # populate r1's pool so we can confirm it's torn down on rebuild
        conn1, _ = r1._get_conn(p1)
        assert r1._conn_cache  # has a pooled connection
        r2 = get_knowledge_retriever([p2])
        assert r2 is not r1, "a changed pack set must rebuild the retriever"
        # The old retriever's connections were closed on rebuild.
        assert r1._conn_cache == {}


class TestSqliteConnectionPool:
    def test_get_conn_reuses_one_connection_per_pack(self, tmp_path):
        p = _empty_pack(tmp_path)
        retriever = KnowledgePackRetriever([p])
        conn_a, lock_a = retriever._get_conn(p)
        conn_b, lock_b = retriever._get_conn(p)
        assert conn_a is conn_b, "a pack must pool a single connection, not reopen per call"
        assert lock_a is lock_b
        assert len(retriever._conn_cache) == 1

    def test_search_does_not_open_a_new_connection_each_call(self, tmp_path):
        p = _empty_pack(tmp_path)
        retriever = KnowledgePackRetriever([p])
        retriever.search("anything", max_cards=4)
        retriever.search("anything", max_cards=4)
        # Two searches on one pack → exactly one pooled connection.
        assert len(retriever._conn_cache) == 1

    def test_close_drops_all_pooled_connections(self, tmp_path):
        p = _empty_pack(tmp_path)
        retriever = KnowledgePackRetriever([p])
        retriever._get_conn(p)
        assert retriever._conn_cache
        retriever.close()
        assert retriever._conn_cache == {}
        assert retriever._conn_locks == {}