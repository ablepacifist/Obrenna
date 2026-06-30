"""Model display name formatter.

Strips distillation/quantization suffixes from model slugs so the UI
shows short readable names: 'qwen3.5-9b-claude-opus-reasoning-distilled' → 'Qwen3.5 9B'.
"""
from __future__ import annotations

import re


def format_display_name(slug: str) -> str:
    """Return a short human-readable name from a model slug.

    Keeps model family + version + parameter count, strips everything after.
    """
    # Strip any HF/Ollama owner prefix ('radenadri/Qwen3.5-...' → 'Qwen3.5-...')
    if '/' in slug:
        slug = slug.rsplit('/', 1)[-1]
    # Drop a trailing quant/format tag like '-GGUF' that adds no value
    slug = re.sub(r'[-_](gguf|mlx|q\d\w*|f16|bf16)$', '', slug, flags=re.IGNORECASE)
    # Drop a leading packager prefix like 'unsloth_' or 'unsloth-'
    slug = re.sub(r'^(unsloth|bartowski|lmstudio-community|thebloke)[-_]', '', slug, flags=re.IGNORECASE)

    # Find first param-count token: digits + optional decimal + size suffix
    m = re.search(r'\d+\.?\d*[bBmMkK]', slug)
    if m:
        prefix = slug[: m.end()]
    else:
        prefix = slug

    words = re.split(r'[-_\s]+', prefix)
    result = []
    for w in words:
        if not w:
            continue
        if re.match(r'^\d+\.?\d*[bBmMkK]$', w):
            result.append(w.upper())
        else:
            result.append(w.capitalize())
    return ' '.join(result)
