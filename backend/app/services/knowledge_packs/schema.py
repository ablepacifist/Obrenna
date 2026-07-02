"""SQLite schema helpers for Obrenna knowledge packs.

The runtime reads packs as portable SQLite files. This module defines the
tables used by the pack builder and validates the minimal data shape needed by
the retriever.
"""

from __future__ import annotations

PACK_SCHEMA_VERSION = 1
PACK_VECTOR_DIM = 384


def create_pack_schema_sql(vector_dim: int = PACK_VECTOR_DIM) -> str:
    """Return SQL that creates the minimal v1 knowledge-pack tables."""

    return f"""
    CREATE TABLE IF NOT EXISTS pack_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS concepts (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        description TEXT,
        type TEXT NOT NULL,
        confidence REAL DEFAULT 1.0
    );

    CREATE TABLE IF NOT EXISTS facts (
        id TEXT PRIMARY KEY,
        subject_id TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object_text TEXT NOT NULL,
        qualifier TEXT,
        source_id TEXT,
        confidence REAL DEFAULT 1.0
    );

    CREATE TABLE IF NOT EXISTS edges (
        id TEXT PRIMARY KEY,
        from_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        to_id TEXT NOT NULL,
        weight REAL DEFAULT 1.0
    );

    CREATE TABLE IF NOT EXISTS knowledge_cards (
        id TEXT PRIMARY KEY,
        topic TEXT NOT NULL,
        card_type TEXT NOT NULL,
        content TEXT NOT NULL,
        search_text TEXT NOT NULL DEFAULT '',
        source_ids TEXT,
        confidence REAL DEFAULT 1.0
    );

    CREATE TABLE IF NOT EXISTS card_sources (
        card_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        PRIMARY KEY (card_id, source_id),
        FOREIGN KEY(card_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS card_vectors (
        card_id TEXT PRIMARY KEY,
        vector BLOB NOT NULL,
        vector_dim INTEGER NOT NULL DEFAULT {int(vector_dim)},
        FOREIGN KEY(card_id) REFERENCES knowledge_cards(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS pack_edges (
        id TEXT PRIMARY KEY,
        from_id TEXT NOT NULL,
        relation TEXT NOT NULL,
        to_id TEXT NOT NULL,
        weight REAL DEFAULT 1.0
    );

    CREATE TABLE IF NOT EXISTS pack_facts (
        id TEXT PRIMARY KEY,
        subject_id TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object_text TEXT NOT NULL,
        qualifier TEXT,
        source_id TEXT,
        confidence REAL DEFAULT 1.0
    );

    CREATE INDEX IF NOT EXISTS idx_knowledge_cards_topic ON knowledge_cards(topic);
    CREATE INDEX IF NOT EXISTS idx_knowledge_cards_type ON knowledge_cards(card_type);
    CREATE INDEX IF NOT EXISTS idx_card_sources_source_id ON card_sources(source_id);
    CREATE INDEX IF NOT EXISTS idx_pack_edges_from_id ON pack_edges(from_id);
    CREATE INDEX IF NOT EXISTS idx_pack_edges_to_id ON pack_edges(to_id);
    """