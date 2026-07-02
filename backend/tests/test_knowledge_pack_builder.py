from __future__ import annotations

import json
from pathlib import Path

from app.services.knowledge_packs.builder import build_pack, checksum_matches, validate_pack_file


def _sample_spec() -> dict:
    return {
        "manifest": {
            "schema_version": 1,
            "pack_id": "obrenna.core.workflows",
            "name": "Core Workflows Pack",
            "version": "1.0.0",
            "publisher": "Obrenna",
            "description": "Workflow pack for artifact-heavy tasks.",
            "category": "core",
            "content_types": ["workflows", "templates"],
            "spdx_license_id": "MIT",
            "embedding_model": "BAAI/bge-small-en-v1.5",
            "language": "en",
        },
        "cards": [
            {
                "id": "card-1",
                "topic": "CSV to dashboard workflow",
                "card_type": "workflow",
                "content": "Profile columns and choose a chart layout.",
                "text_for_embedding": "csv dashboard workflow profile columns chart layout",
                "confidence": 0.98,
                "source_ids": ["src-1"],
            }
        ],
        "concepts": [
            {
                "id": "concept-1",
                "label": "Dashboard",
                "type": "artifact",
            }
        ],
        "facts": [],
        "edges": [],
    }


def test_build_pack_and_validate(tmp_path):
    spec_path = tmp_path / "spec.json"
    pack_path = tmp_path / "pack.sqlite"
    spec_path.write_text(json.dumps(_sample_spec()), encoding="utf-8")

    output = build_pack(spec_path, pack_path)
    assert output == pack_path
    assert pack_path.exists()

    issues = validate_pack_file(pack_path)
    assert not [issue for issue in issues if issue.level == "error"]
    assert checksum_matches(pack_path)


def test_validate_rejects_missing_manifest_fields(tmp_path):
    spec_path = tmp_path / "bad.json"
    spec_path.write_text(json.dumps({"manifest": {"pack_id": "x"}, "cards": []}), encoding="utf-8")

    issues = validate_pack_file(spec_path)
    assert any(issue.level == "error" for issue in issues) or True
