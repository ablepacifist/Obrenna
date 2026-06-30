# Hardware Catalog Migration Plan

Replace stock Qwen orchestrator models with Claude-Opus-distilled variants, remove gpt-oss, and update tier assignments across all hardware tiers.

## Changes Summary

| File | Type | Scope |
|------|------|-------|
| `hardware_catalog.json` | Replace | Complete — matches user's JSON spec |
| `hardware_resolver.py` | Edit | Remove gpt-oss/optional_orchestrator handling, update response for new model names |
| `test_hardware_resolver.py` | Edit | Update 7 assertion references to new model names |
| `hardware.py` | Edit | Add detection warning for Ollama runtime at T1 |

## Affected Model IDs

- **Removed:** `qwen3.5-4b` (stock), `qwen3.5-9b` (stock), `gpt-oss-20b`
- **New:** `qwen3.5-4b-claude-opus-reasoning-distilled-v2`, `qwen3.5-9b-claude-opus-reasoning-distilled`
- **Unchanged:** all Granite models, `qwen3.5-0.8b`, `qwen3.5-27b`, `qwen3.6-35b-a3b`

## Task List

### 1. Replace `hardware_catalog.json` with new spec

Complete replacement — every section changes. Key updates:

- **model_definitions:** Remove `qwen3.5-4b`, `qwen3.5-9b`, `gpt-oss-20b`. Add new distilled model entries with their quant weights and KV cache figures. Update `_quant_weight_table_gb` for all distilled variants. Update `_kv_cache_gb_per_1k_tokens` table (remove gpt-oss-20b, add distilled entries).
- **gpu_tiers:** Update orchestrator models at T0-T4 to distilled variants. Remove `optional_orchestrator` from T4. Update T1 `runtime_forbidden: [ollama]` and add `required_launch_flags`. Update T5/T6 notes.
- **cpu_only_tiers:** Update CL0-CL2 orchestrator to distilled 4B variant. Update CL1 helpers section with summarizer serial execution config.
- **apple_silicon_tiers:** Update A0→distilled-4b-Q5, A1→distilled-9b-Q4, A2→distilled-9b-Q8. Add notes to A3/A4/A5 about stock model exceptions.
- **runtime_adapter_requirements:** Remove gpt-oss family block. Update description to 2-family (Qwen + Granite). Update thinking_mode to specify CoT handling for distilled variants.
- **detection_instructions:** Add AVX-512 detection runtime caveat note.
- **resolver_algorithm:** Update pseudocode to remove gpt-oss references.

### 2. Update `hardware_resolver.py`

- Remove `optional_orchestrator` from `choose_and_validate()` response building (lines 338-339) — this field no longer exists in the catalog.
- Update the `_get_kv_cache_gb_per_1k` default from `0.15` — no change needed since it's a fallback, but verify no distilled model entry is missing.
- The `build_fingerprint` function is unchanged — fingerprint fields match the new catalog.

### 3. Update `test_hardware_resolver.py`

Update model name assertions (7 locations):

| Line | Old | New |
|------|-----|-----|
| 47 | `qwen3.5-4b` | `qwen3.5-4b-claude-opus-reasoning-distilled-v2` |
| 98 | `qwen3.5-9b` | `qwen3.5-9b-claude-opus-reasoning-distilled` |
| 124 | `qwen3.5-4b` | `qwen3.5-4b-claude-opus-reasoning-distilled-v2` |
| 176 | `qwen3.5-9b` | `qwen3.5-9b-claude-opus-reasoning-distilled` |
| 200 | `qwen3.5-9b` | `qwen3.5-9b-claude-opus-reasoning-distilled` |
| 494 (fit test plan) | `qwen3.5-9b` | `qwen3.5-9b-claude-opus-reasoning-distilled` |
| 517 (fit test plan) | `qwen3.5-9b` | `qwen3.5-9b-claude-opus-reasoning-distilled` |

Additionally:
- Remove `optional_orchestrator` assertion if any test checks it (none found in current tests).
- Update test `test_rtx3060_32gb_t3_plus` — T3 orchestrator is now distilled-9b (same model name change as above).
- Update test `test_16gb_fp16_gpu_gets_t4_high` — T4 orchestrator is now distilled-9b (same name change).

### 4. Update `hardware.py`

Add detection warning when T1-floor plan is selected with Ollama in runtime_priority (since T1 explicitly forbids Ollama). The `probe_all()` flow uses `resolve_managed_plan` → `choose_and_validate` → response includes `runtime_forbidden` — add a warning if the user's configured runtime conflicts.

## Validation

- Run existing test suite: `python -m pytest backend/tests/test_hardware_resolver.py -v`
- All 30 tests should pass after model name updates.
- No new tests needed — the model name changes are drop-in replacements with identical tier behavior (same quant, same ctx range, same VRAM requirements per the new weight table).

## Risks

1. **Quant weight differences:** Distilled models have different file sizes than stock. The new weight table in the catalog accounts for this, but the `fit()` function will compute different VRAM usage. All tiers were pre-validated to fit — no code-level fit changes needed.
2. **Thinking CoT handling:** Distilled models produce `</think>` blocks that the adapter layer must parse. This is documented in the catalog's `runtime_adapter_requirements` but may require follow-up changes in the actual inference adapter (not in scope of this resolver migration).
3. **gpt-oss removal:** If any BYO/cloud path references gpt-oss model names, those must be updated separately. The `model_catalog.py` legacy file uses generic names and is unaffected.
