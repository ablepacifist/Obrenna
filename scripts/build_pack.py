#!/usr/bin/env python
"""Build or validate Obrenna knowledge packs.

Usage:
  python scripts/build_pack.py build spec.json pack.sqlite
  python scripts/build_pack.py validate pack.sqlite --require-checksum
"""

from __future__ import annotations

import sys

from backend.app.services.knowledge_packs.builder import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
