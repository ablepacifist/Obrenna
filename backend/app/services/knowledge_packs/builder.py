"""Pack builder and validator for Obrenna knowledge packs.

This module compiles a declarative JSON pack spec into a portable SQLite pack
file, then validates its shape and writes a checksum sidecar for distribution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..embeddings import embed_text
from .retriever import pack_card_vector_blob
from .schema import PACK_SCHEMA_VERSION, PACK_VECTOR_DIM, create_pack_schema_sql

logger = logging.getLogger(__name__)

REQUIRED_MANIFEST_KEYS = (
    "schema_version",
    "pack_id",
    "name",
    "version",
    "publisher",
    "description",
    "category",
    "content_types",
    "spdx_license_id",
    "embedding_model",
    "language",
)


@dataclass(frozen=True)
class PackValidationIssue:
    level: str
    message: str


def load_pack_spec(spec_path: str | Path) -> dict[str, Any]:
    path = Path(spec_path)
    return json.loads(path.read_text(encoding="utf-8"))


def validate_pack_spec(spec: dict[str, Any]) -> list[PackValidationIssue]:
    issues: list[PackValidationIssue] = []
    manifest = spec.get("manifest")
    if not isinstance(manifest, dict):
        return [PackValidationIssue("error", "manifest must be an object")]

    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            issues.append(PackValidationIssue("error", f"manifest missing required key: {key}"))

    if manifest.get("schema_version") not in {str(PACK_SCHEMA_VERSION), PACK_SCHEMA_VERSION}:
        issues.append(
            PackValidationIssue(
                "error",
                f"unsupported schema_version: {manifest.get('schema_version')} (expected {PACK_SCHEMA_VERSION})",
            )
        )

    cards = spec.get("cards", [])
    if not isinstance(cards, list):
        issues.append(PackValidationIssue("error", "cards must be a list"))
        return issues

    ids: set[str] = set()
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            issues.append(PackValidationIssue("error", f"cards[{index}] must be an object"))
            continue
        for key in ("id", "topic", "card_type", "content"):
            if key not in card:
                issues.append(PackValidationIssue("error", f"cards[{index}] missing required key: {key}"))
        card_id = str(card.get("id", "")).strip()
        if card_id:
            if card_id in ids:
                issues.append(PackValidationIssue("error", f"duplicate card id: {card_id}"))
            ids.add(card_id)
        if "text_for_embedding" in card and not isinstance(card["text_for_embedding"], str):
            issues.append(PackValidationIssue("error", f"cards[{index}].text_for_embedding must be a string"))

    return issues


def _normalize_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_checksum(pack_path: Path) -> Path:
    digest = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    checksum_path = pack_path.with_suffix(pack_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {pack_path.name}\n", encoding="utf-8")
    return checksum_path


def build_pack(spec_path: str | Path, output_path: str | Path, *, overwrite: bool = False) -> Path:
    """Compile a JSON pack spec into a SQLite pack file."""

    spec = load_pack_spec(spec_path)
    issues = validate_pack_spec(spec)
    errors = [issue.message for issue in issues if issue.level == "error"]
    if errors:
        raise ValueError("Invalid pack spec:\n- " + "\n- ".join(errors))

    output = Path(output_path)
    if output.exists():
        if not overwrite:
            raise FileExistsError(f"Pack already exists: {output}")
        output.unlink()
    _ensure_parent(output)

    manifest = spec["manifest"]
    cards = spec.get("cards", [])
    concepts = spec.get("concepts", [])
    facts = spec.get("facts", [])
    edges = spec.get("edges", [])

    with sqlite3.connect(output) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(create_pack_schema_sql())
        fts_enabled = True
        try:
            conn.execute("DROP TABLE IF EXISTS knowledge_cards_fts")
            conn.execute(
                "CREATE VIRTUAL TABLE knowledge_cards_fts USING fts5("
                "card_id UNINDEXED, topic, card_type, content, search_text)"
            )
        except sqlite3.OperationalError:
            fts_enabled = False
            conn.execute("DROP TABLE IF EXISTS knowledge_cards_fts")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_cards_fts ("
                "card_id TEXT PRIMARY KEY, topic TEXT, card_type TEXT, content TEXT, search_text TEXT)"
            )

        for key, value in manifest.items():
            conn.execute(
                "INSERT OR REPLACE INTO pack_metadata (key, value) VALUES (?, ?)",
                (str(key), _normalize_json(value) if isinstance(value, (dict, list)) else str(value)),
            )

        for row in concepts:
            conn.execute(
                "INSERT INTO concepts (id, label, description, type, confidence) VALUES (?, ?, ?, ?, ?)",
                (
                    str(row["id"]),
                    str(row["label"]),
                    row.get("description"),
                    str(row["type"]),
                    float(row.get("confidence", 1.0)),
                ),
            )

        for row in facts:
            conn.execute(
                "INSERT INTO facts (id, subject_id, predicate, object_text, qualifier, source_id, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(row["id"]),
                    str(row["subject_id"]),
                    str(row["predicate"]),
                    str(row["object_text"]),
                    row.get("qualifier"),
                    row.get("source_id"),
                    float(row.get("confidence", 1.0)),
                ),
            )

        for row in edges:
            conn.execute(
                "INSERT INTO pack_edges (id, from_id, relation, to_id, weight) VALUES (?, ?, ?, ?, ?)",
                (
                    str(row["id"]),
                    str(row["from_id"]),
                    str(row["relation"]),
                    str(row["to_id"]),
                    float(row.get("weight", 1.0)),
                ),
            )

        for row in cards:
            card_id = str(row["id"])
            content_value = row["content"]
            content_text = content_value if isinstance(content_value, str) else _normalize_json(content_value)
            search_text = str(row.get("search_text") or row.get("text_for_embedding") or content_text)
            source_ids = row.get("source_ids")
            source_ids_text = _normalize_json(source_ids) if isinstance(source_ids, (list, dict)) else (
                "" if source_ids is None else str(source_ids)
            )
            confidence = float(row.get("confidence", 1.0))

            conn.execute(
                "INSERT INTO knowledge_cards (id, topic, card_type, content, search_text, source_ids, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    card_id,
                    str(row["topic"]),
                    str(row["card_type"]),
                    content_text,
                    search_text,
                    source_ids_text,
                    confidence,
                ),
            )

            if fts_enabled:
                conn.execute(
                    "INSERT INTO knowledge_cards_fts (card_id, topic, card_type, content, search_text) VALUES (?, ?, ?, ?, ?)",
                    (card_id, str(row["topic"]), str(row["card_type"]), content_text, search_text),
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO knowledge_cards_fts (card_id, topic, card_type, content, search_text) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (card_id, str(row["topic"]), str(row["card_type"]), content_text, search_text),
                )

            for source_id in _as_list(source_ids):
                conn.execute(
                    "INSERT OR REPLACE INTO card_sources (card_id, source_id) VALUES (?, ?)",
                    (card_id, source_id),
                )

            embedding_text = str(row.get("text_for_embedding") or search_text)
            embedding = embed_text(embedding_text)
            if embedding is not None:
                conn.execute(
                    "INSERT INTO card_vectors (card_id, vector, vector_dim) VALUES (?, ?, ?)",
                    (card_id, pack_card_vector_blob(embedding), PACK_VECTOR_DIM),
                )

        conn.commit()

    _write_checksum(output)
    return output


def _as_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item)]
    if isinstance(raw, dict):
        return [str(value) for value in raw.values() if str(value)]
    try:
        parsed = json.loads(str(raw))
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item)]
    except Exception:
        pass
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def validate_pack_file(pack_path: str | Path) -> list[PackValidationIssue]:
    """Validate a compiled pack SQLite file."""

    path = Path(pack_path)
    issues: list[PackValidationIssue] = []
    if not path.exists():
        return [PackValidationIssue("error", f"pack file not found: {path}")]

    try:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            required_tables = {"pack_metadata", "knowledge_cards", "card_vectors", "concepts", "facts", "pack_edges", "card_sources"}
            found_tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            missing_tables = sorted(required_tables - found_tables)
            for table in missing_tables:
                issues.append(PackValidationIssue("error", f"missing required table: {table}"))

            meta_rows = conn.execute("SELECT key, value FROM pack_metadata").fetchall()
            manifest = {row["key"]: row["value"] for row in meta_rows}
            for key in REQUIRED_MANIFEST_KEYS:
                if key not in manifest:
                    issues.append(PackValidationIssue("error", f"missing manifest key in pack: {key}"))

            card_rows = conn.execute("SELECT id, topic, card_type, content FROM knowledge_cards").fetchall()
            if not card_rows:
                issues.append(PackValidationIssue("warning", "pack contains no knowledge cards"))

            for row in conn.execute("SELECT card_id, vector, vector_dim FROM card_vectors").fetchall():
                blob = row["vector"]
                vector_dim = int(row["vector_dim"] or 0)
                if vector_dim != PACK_VECTOR_DIM:
                    issues.append(
                        PackValidationIssue(
                            "error",
                            f"vector_dim mismatch for {row['card_id']}: {vector_dim} != {PACK_VECTOR_DIM}",
                        )
                    )
                if len(blob) != PACK_VECTOR_DIM * 4:
                    issues.append(
                        PackValidationIssue(
                            "error",
                            f"vector blob length mismatch for {row['card_id']}: {len(blob)}",
                        )
                    )

            fts_present = any(row[0] == "knowledge_cards_fts" for row in conn.execute("SELECT name FROM sqlite_master WHERE name='knowledge_cards_fts'").fetchall())
            if not fts_present:
                issues.append(PackValidationIssue("warning", "FTS5 index not present; runtime will fall back to pure Python keyword scoring"))
    except sqlite3.Error as exc:
        issues.append(PackValidationIssue("error", f"failed to read pack SQLite file: {exc}"))

    return issues


def checksum_matches(pack_path: str | Path) -> bool:
    path = Path(pack_path)
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    if not path.exists() or not checksum_path.exists():
        return False
    expected = checksum_path.read_text(encoding="utf-8").split()[0].strip()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    return expected == actual


def _build_cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="obrenna-pack", description="Build and validate Obrenna knowledge packs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Compile a JSON pack spec into SQLite")
    build_parser.add_argument("spec", type=Path)
    build_parser.add_argument("output", type=Path)
    build_parser.add_argument("--overwrite", action="store_true")

    validate_parser = subparsers.add_parser("validate", help="Validate a compiled pack SQLite file")
    validate_parser.add_argument("pack", type=Path)
    validate_parser.add_argument("--require-checksum", action="store_true")

    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "build":
        output = build_pack(args.spec, args.output, overwrite=args.overwrite)
        print(str(output))
        return 0

    if args.command == "validate":
        issues = validate_pack_file(args.pack)
        if args.require_checksum and not checksum_matches(args.pack):
            issues.append(PackValidationIssue("error", "checksum sidecar missing or invalid"))

        errors = [issue for issue in issues if issue.level == "error"]
        warnings = [issue for issue in issues if issue.level == "warning"]
        for issue in warnings:
            print(f"warning: {issue.message}")
        for issue in errors:
            print(f"error: {issue.message}")
        if errors:
            return 1
        print("ok")
        return 0

    return 2


def main(argv: Sequence[str] | None = None) -> int:
    return _build_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
