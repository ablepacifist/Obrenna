from __future__ import annotations

import json
from pathlib import Path

from app.services.knowledge_packs.builder import build_pack
from app.services.knowledge_packs import registry as pack_registry


def _sample_spec() -> dict:
    return {
        "manifest": {
            "schema_version": 1,
            "pack_id": "obrenna.core.registry-test",
            "name": "Registry Test Pack",
            "version": "1.0.0",
            "publisher": "Obrenna",
            "description": "Registry test pack.",
            "category": "core",
            "content_types": ["workflows"],
            "spdx_license_id": "MIT",
            "embedding_model": "BAAI/bge-small-en-v1.5",
            "language": "en",
        },
        "cards": [
            {
                "id": "card-registry",
                "topic": "Registry test",
                "card_type": "workflow",
                "content": "Test local install and uninstall.",
                "text_for_embedding": "registry test workflow install uninstall",
            }
        ],
    }


def test_install_and_uninstall_pack(tmp_path):
    data_root = tmp_path / "data"
    packs_dir = data_root / "packs"
    installed_dir = packs_dir / "installed"
    registry_path = packs_dir / "registry.json"
    pack_registry.DATA_DIR = data_root
    pack_registry.PACKS_DIR = packs_dir
    pack_registry.INSTALLED_DIR = installed_dir
    pack_registry.REGISTRY_PATH = registry_path

    spec_path = tmp_path / "spec.json"
    pack_path = tmp_path / "pack.sqlite"
    spec_path.write_text(json.dumps(_sample_spec()), encoding="utf-8")

    build_pack(spec_path, pack_path)
    entry = pack_registry.install_pack(pack_path)
    assert entry.pack_id == "obrenna.core.registry-test"

    registry = pack_registry.list_installed_packs()
    assert any(row["pack_id"] == "obrenna.core.registry-test" for row in registry)
    assert any(path.exists() for path in pack_registry.installed_pack_paths())

    removed = pack_registry.uninstall_pack("obrenna.core.registry-test")
    assert removed is True
    assert not any(row["pack_id"] == "obrenna.core.registry-test" for row in pack_registry.list_installed_packs())