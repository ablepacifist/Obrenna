from __future__ import annotations

import sqlite3
import struct

from app.services.knowledge_packs import KnowledgePackRetriever, RetrievalEvalCase, create_pack_schema_sql, run_retrieval_eval
from app.services.memory import MemoryContext
from app.services.knowledge_packs.retriever import pack_card_vector_blob


def _seed_pack(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(create_pack_schema_sql())
        conn.execute(
            "INSERT INTO knowledge_cards (id, topic, card_type, content, search_text, source_ids, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "card-dashboard",
                "CSV to dashboard workflow",
                "workflow",
                "Profile columns, detect numeric fields, and choose a chart layout.",
                "csv dashboard workflow chart numeric fields",
                '["source-1"]',
                0.95,
            ),
        )
        conn.execute(
            "INSERT INTO knowledge_cards (id, topic, card_type, content, search_text, source_ids, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "card-lease",
                "Revenue follow-up template",
                "template",
                "Summarize revenue, margin, and growth follow-up actions.",
                "revenue summary margin growth follow up",
                '["source-2"]',
                0.75,
            ),
        )
        conn.execute(
            "INSERT INTO card_sources (card_id, source_id) VALUES (?, ?)",
            ("card-dashboard", "concept-revenue"),
        )
        conn.execute(
            "INSERT INTO card_sources (card_id, source_id) VALUES (?, ?)",
            ("card-lease", "concept-profit"),
        )
        conn.execute(
            "INSERT INTO pack_edges (id, from_id, relation, to_id, weight) VALUES (?, ?, ?, ?, ?)",
            ("edge-1", "concept-revenue", "related_to", "concept-profit", 1.0),
        )
        conn.execute(
            "INSERT INTO card_vectors (card_id, vector, vector_dim) VALUES (?, ?, ?)",
            ("card-dashboard", pack_card_vector_blob([1.0] + [0.0] * 383), 384),
        )
        conn.execute(
            "INSERT INTO card_vectors (card_id, vector, vector_dim) VALUES (?, ?, ?)",
            ("card-lease", pack_card_vector_blob([0.0, 1.0] + [0.0] * 382), 384),
        )


def test_pack_schema_creates_expected_tables(tmp_path):
    db_path = tmp_path / "pack.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(create_pack_schema_sql())
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

    assert "knowledge_cards" in tables
    assert "card_vectors" in tables
    assert "pack_metadata" in tables


def test_retriever_prefers_vector_and_keyword_matches(tmp_path):
    db_path = tmp_path / "pack.sqlite"
    _seed_pack(str(db_path))

    retriever = KnowledgePackRetriever([db_path], embedder=lambda _: [1.0] + [0.0] * 383)
    context = retriever.search("build a csv dashboard", max_cards=2)

    assert len(context.cards) == 1
    assert context.cards[0].id == "card-dashboard"
    assert "CSV to dashboard workflow" in context.to_prompt_block()
    assert context.cards[0].source_ids == ["source-1"]


def test_retriever_expands_one_hop_edges(tmp_path):
    db_path = tmp_path / "pack.sqlite"
    _seed_pack(str(db_path))

    retriever = KnowledgePackRetriever([db_path], embedder=lambda _: [1.0] + [0.0] * 383)
    context = retriever.search("revenue analysis", max_cards=4)

    returned_ids = [card.id for card in context.cards]
    assert "card-dashboard" in returned_ids
    assert "card-lease" in returned_ids
    assert context.graph_hints


def test_pack_vector_blob_roundtrip():
    blob = pack_card_vector_blob([0.25] * 384)
    values = struct.unpack("<384f", blob)
    assert len(values) == 384
    assert abs(values[0] - 0.25) < 1e-6


def test_memory_context_includes_knowledge_cards():
    ctx = MemoryContext(
        knowledge_cards=[
            {
                "card_type": "workflow",
                "topic": "CSV to dashboard workflow",
                "content": "Profile columns, detect numeric fields, and choose a chart layout.",
            }
        ]
    )

    messages = ctx.to_messages()
    assert len(messages) == 1
    assert "Retrieved knowledge packs" in messages[0]["content"]
    assert "CSV to dashboard workflow" in messages[0]["content"]


def test_retrieval_eval_harness_reports_metrics(tmp_path):
    db_path = tmp_path / "pack.sqlite"
    _seed_pack(str(db_path))

    retriever = KnowledgePackRetriever([db_path], embedder=lambda _: [1.0] + [0.0] * 383)
    result = run_retrieval_eval(
        retriever,
        [
            RetrievalEvalCase(
                query="revenue analysis",
                expected_card_ids=["card-dashboard", "card-lease"],
                required_terms=["chart", "layout"],
            )
        ],
        top_k=4,
    )

    assert result.cases == 1
    assert result.recall_at_k > 0
    assert result.avg_latency_ms >= 0