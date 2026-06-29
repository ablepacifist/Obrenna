# Hardware Resolver Implementation Plan

## Goal
Implement the managed setup path behind `Set it up for me` so that when the user clicks the hardware-detection flow, GrebGlob:

1. Probes hardware into a stable fingerprint plus live free-resource snapshot.
2. Resolves a deterministic managed plan from a catalog-backed resolver.
3. Persists the selected plan and exposes it through the existing setup API/UI.
4. Routes unsupported hardware to the existing BYO/local-server path.

This first implementation does **not** build a real downloader, runtime launcher, or smoke-test runner. Those remain explicit seams/stubs. The deliverable is exact detection + exact plan resolution + exact UI recommendation/persistence.

## Repo Reality To Preserve
- Backend is FastAPI in `backend/app`.
- Frontend setup flow is React in `frontend/src/setup`.
- Current managed setup is only a recommendation flow with simulated download UI.
- Current local-runtime support is only BYO OpenAI-compatible endpoint config in `backend/app/model_runtime` and `backend/app/routers/settings.py`.
- Current hardware detection is a lightweight display-only implementation in `backend/app/services/hardware.py`.
- Current model recommendation is a static mock catalog in `backend/app/services/model_catalog.py`.

The resolver work should replace the current mock recommendation path, not add a second competing recommendation system.

## Scope In
- Add catalog-backed hardware resolver data and Python service code.
- Expand hardware detection to capture stable facts needed by the resolver, with graceful fallbacks where low-level probing is not yet implemented.
- Add API schema/route support for a resolved managed plan.
- Update setup UI to show the resolved plan instead of the current static “these models fit” list.
- Persist resolved managed plan metadata in app settings or adjacent persisted state.
- Add tests for resolution behavior and exact tier mapping.

## Scope Out
- Real model download.
- Real runtime launch.
- Real llama.cpp/Ollama backend selection and process management.
- Real smoke test against loaded models.
- Automatic BYO endpoint provisioning.
- Adapter-layer implementation for Qwen/Granite/gpt-oss families.

## Required Design Rule
The implementation must preserve the reference rule:

- No model name, VRAM number, core count, RAM threshold, or tier-routing threshold may be hardcoded in resolver logic.
- The resolver must read all thresholds and model selections from `hardware_catalog.json`.
- Tests may use literal fixture values.

## Exact Hardware And Model Tiers To Encode Verbatim
These exact rows must exist in the catalog and must be the values the resolver selects.

### GPU tiers
1. `T6-enthusiast`
- Requires: `gpu_vram_gb >= 32`, `gpu_fp16 = true`
- Orchestrator: `qwen3.6-35b-a3b` `Q4_K_M`
- Summarizer: `granite4.0-h-tiny-7b-a1b` `Q5_K_M`
- Utility: `qwen3.5-0.8b` `Q8_0`
- Runtime priority: `cuda`, `vulkan`

2. `T5-workstation`
- Requires: `gpu_vram_gb >= 24`, `gpu_fp16 = true`
- Orchestrator: `qwen3.5-27b` `Q4_K_M`
- Summarizer: `granite4.0-h-tiny-7b-a1b` `Q5_K_M`
- Utility: `qwen3.5-0.8b` `Q6_K`
- Runtime priority: `cuda`, `rocm`, `vulkan`

3. `T4-high`
- Requires: `gpu_vram_gb >= 16`, `gpu_fp16 = true`
- Default orchestrator: `qwen3.5-9b` `Q8_0`
- Optional power-user orchestrator: `gpt-oss-20b` `Q4_K_M`
- Summarizer: `granite4.0-h-micro-3b` `Q6_K`
- Utility: `qwen3.5-0.8b` `Q6_K`
- Runtime priority: `cuda`, `rocm`, `vulkan`
- Default must remain `qwen3.5-9b`, not `gpt-oss-20b`

4. `T3-plus`
- Requires: `gpu_vram_gb >= 12`, `gpu_fp16 = true`
- Orchestrator: `qwen3.5-9b` `Q6_K`
- Summarizer: `granite4.0-h-micro-3b` `Q5_K_M`
- Utility: `qwen3.5-0.8b` `Q6_K`
- Runtime priority: `cuda`, `rocm`, `vulkan`

5. `T2-standard-fp16`
- Requires: `gpu_vram_gb >= 8`, `gpu_fp16 = true`
- Orchestrator: `qwen3.5-9b` `Q4_K_M`
- Summarizer: `granite4.0-h-micro-3b` `Q5_K_M`
- Utility: `qwen3.5-0.8b` `Q6_K`
- Runtime priority: `cuda`, `rocm`, `vulkan`

6. `T1-floor-fp32`
- Requires: `gpu_vram_gb >= 8`, `gpu_fp16 = false`, backend includes `vulkan`
- Orchestrator: `qwen3.5-4b` `Q5_K_M`
- Summarizer: `granite4.0-h-micro-3b` `Q5_K_M`
- Utility: `qwen3.5-0.8b` `Q6_K`
- Runtime priority: `vulkan`
- Runtime forbidden: `ollama`
- Required launch flags must be preserved in the catalog as data

7. `T0-subfloor`
- Requires: `gpu_vram_gb >= 6`, `gpu_fp16 = false`
- Orchestrator: `qwen3.5-4b` `Q4_K_M`
- Summarizer: `granite4.0-h-micro-3b` `Q5_K_M`
- Utility: `qwen3.5-0.8b` `Q6_K`
- Runtime priority: `vulkan`, `cuda`

8. GPU reject-below rule
- Below `gpu_vram_gb = 6`, do not offer managed GPU stack.
- Route to CPU-only tiers if they qualify, else BYO/cloud-key setup path.

### CPU helper concurrency tiers when GPU orchestrator is present
1. `C0-minimum`: `physical_cores >= 4`, `threads >= 4`, `avx2` -> `peak_concurrent_helpers = 1`
2. `C1-floor`: `physical_cores >= 6`, `avx2` -> `peak_concurrent_helpers = 2`
3. `C2-standard`: `physical_cores >= 6`, `threads >= 12`, `avx2` -> `peak_concurrent_helpers = 3`
4. `C3-strong`: `physical_cores >= 8`, `threads >= 16`, `avx2` -> `peak_concurrent_helpers = 4`
5. `C4-high`: `physical_cores >= 12`, `threads >= 20`, `avx2` -> `peak_concurrent_helpers = 5`
6. `C5-workstation`: `physical_cores >= 16`, `threads >= 24`, `avx2` -> `peak_concurrent_helpers = 6`

### RAM residency tiers when GPU orchestrator is present
1. `R-16gb`: `ram_gb >= 16` -> `residency_ceiling = 3`
2. `R-24gb`: `ram_gb >= 24` -> `residency_ceiling = 4`
3. `R-32gb`: `ram_gb >= 32` -> `residency_ceiling = 6`
4. `R-48gb`: `ram_gb >= 48` -> `residency_ceiling = 8`
5. `R-64gb-plus`: `ram_gb >= 64` -> `residency_ceiling = 99`

Helper count for GPU plans must be:
- `helper_count = min(cpu_peak_concurrent_helpers, ram_residency_ceiling)`

### CPU-only tiers
1. `CL0-lite`
- Requires: `ram_gb >= 16`
- Orchestrator: `qwen3.5-4b` `Q4_K_M`
- Helpers max: `1`
- Expected tok/s: `3-6`

2. `CL1-minimum`
- Requires: `ram_gb >= 32`, `ram_type = ddr5`, `ram_channels >= 2`, `physical_cores >= 6`, `avx2`
- Orchestrator: `qwen3.5-4b` `Q5_K_M`
- Helpers model: `qwen3.5-0.8b` `Q6_K`
- Helpers max: `1`
- This is the GPU-less minimum / true floor for CPU-only path

3. `CL2-good`
- Requires: `ram_gb >= 48`, `ram_type = ddr5`, `ram_channels >= 2`, `physical_cores >= 8`, `avx2`
- Orchestrator: `qwen3.5-4b` `Q6_K`
- Helpers model: `granite4.0-h-micro-3b` `Q5_K_M`
- Helpers max: `2`

4. `CL3-strong`
- Requires: `ram_gb >= 64`, `ram_type = ddr5`, `ram_channels >= 2`, `physical_cores >= 12`, `avx2`
- Orchestrator: `qwen3.6-35b-a3b` `Q4_K_M`
- Helpers model: `granite4.0-h-micro-3b` `Q5_K_M`
- Helpers max: `2`

5. `CL4-workstation`
- Requires: `ram_gb >= 96`, `ram_type = ddr5`, `ram_channels >= 4`, `physical_cores >= 16`, `avx2`
- Orchestrator: `qwen3.6-35b-a3b` `Q5_K_M`
- Helpers model: `granite4.0-h-micro-3b` `Q6_K`
- Helpers max: `3`

6. CPU-only reject-below rule
- Below `ram_gb = 16`, route directly to BYO/cloud-key setup.

### Apple Silicon tiers
1. `A0`: `unified_mem_gb >= 8` -> `qwen3.5-4b` `Q5_K_M`
2. `A1`: `unified_mem_gb >= 16` -> `qwen3.5-9b` `Q4_K_M`
3. `A2`: `unified_mem_gb >= 24` -> `qwen3.5-9b` `Q8_0`
4. `A3`: `unified_mem_gb >= 32` -> `qwen3.5-27b` `Q4_K_M`
5. `A4`: `unified_mem_gb >= 48` -> `qwen3.6-35b-a3b` `Q4_K_M`
6. `A5`: `unified_mem_gb >= 96` -> `qwen3.6-35b-a3b` `Q5_K_M`
- Runtime priority for Apple path: `mlx`, `gguf-metal`

## Architecture Changes

### 1. Add the catalog file
Create `backend/app/services/hardware_catalog.json` or `backend/app/data/hardware_catalog.json` and keep all tier logic there.

Recommendation:
- Put it next to the resolver service under `backend/app/services/` for easy package-relative loading.
- Add a small loader helper so tests can point to a fixture path if needed.

The file should include:
- `model_definitions`
- `_quant_weight_table_gb`
- `_kv_cache_gb_per_1k_tokens`
- `global_constants`
- `runtime_adapter_requirements`
- `gpu_tiers`
- `cpu_helper_concurrency_tiers`
- `ram_residency_tiers_gpu_present`
- `cpu_only_tiers`
- `apple_silicon_tiers`
- `detection_instructions`
- `resolver_algorithm`

Keep the reference notes and comments as JSON string fields where useful; they are valuable implementation guidance and future documentation.

### 2. Replace mock model catalog service with a resolver service
Current `backend/app/services/model_catalog.py` is a static fit-table mock and is no longer the right abstraction.

Refactor into two layers:
- `backend/app/services/hardware_catalog.py`
  - `load_catalog()`
  - data-access helpers for weights, KV cache, constants
- `backend/app/services/hardware_resolver.py`
  - `HardwareFingerprint`
  - `LiveFreeResources`
  - `_satisfies()`
  - `resolve_gpu_tier()`
  - `resolve_cpu_only_tier()`
  - `resolve_apple_tier()`
  - `resolve_top_level()`
  - `resolve_helper_count()`
  - `fit()`
  - `choose_and_validate()`

Keep `choose_and_validate()` smoke validation stubbed for now, but return a structured result matching the selected plan.

### 3. Expand hardware detection service
Current `backend/app/services/hardware.py` only returns display-friendly fields:
- OS
- CPU string
- RAM total
- NVIDIA GPU list
- max VRAM
- coarse `recommended_profile`

It needs to become the source for two outputs:
- UI-facing hardware summary
- Resolver-facing stable/live probe result

Recommended structure:
- Keep `detect_hardware()` as the UI summary function for backward compatibility.
- Add new internal helpers:
  - `probe_stable_facts()`
  - `probe_live_resources()`
  - `build_hardware_summary()`
  - `resolve_managed_plan()`

### 4. Probe data model to add
Stable facts needed by resolver:
- `gpu_vendor`
- `gpu_name`
- `gpu_vram_total_gb`
- `gpu_fp16_support`
- `gpu_backends_available`
- `gpu_is_integrated`
- `cpu_physical_cores`
- `cpu_threads`
- `cpu_isa_flags`
- `ram_total_gb`
- `ram_type`
- `ram_channels`
- `storage_is_ssd`
- `os`
- `driver_version`
- `unified_mem_gb`

Live facts needed by resolver:
- `gpu_vram_free_gb`
- `ram_free_gb`

### 5. Practical detection scope for this repo
Because this repo does not yet ship a native probe layer, first implementation should be explicit about probe confidence.

Implement now with best-effort logic:
- OS: from Python `platform`.
- RAM total/free: `psutil`.
- CPU logical threads: `psutil`.
- CPU physical cores: `psutil.cpu_count(logical=False)` when available.
- NVIDIA GPU name and total VRAM: keep `nvidia-smi` path.
- NVIDIA free VRAM: `nvidia-smi --query-gpu=memory.free`.
- GPU vendor: infer from detected device source only as a temporary probe mechanism, not for tier routing by name.
- Apple unified memory: detect from platform on macOS and total memory fallback.
- Storage SSD: best-effort default `True` if unknown, matching current pragmatic style.

Mark explicit stubs/TODOs:
- Windows WMI/DirectX/Vulkan probe for AMD/Intel GPU detection.
- Vulkan backend availability probe.
- AMD fp16 capability probe.
- Intel integrated/discrete differentiation.
- CPU ISA CPUID probe for `avx2` and `avx512f`.
- RAM type/channel detection via SMBIOS/WMI or Linux `dmidecode`.
- Driver version capture for non-NVIDIA GPUs.

Important implementation choice:
- The resolver service should accept missing probe fields and degrade deterministically.
- Unknown capability must not be auto-upgraded into a higher tier.
- When detection is incomplete, the plan result should include warnings/diagnostics so the UI can say detection was conservative.

## API Changes

### 1. Keep existing `/api/system/hardware`
Extend the response model instead of replacing the route.

Add fields to `HardwareInfo` in `backend/app/schemas/api.py` for setup use, for example:
- `recommended_profile`
- `detection_warnings: list[str]`
- `resolver_path: 'apple' | 'gpu' | 'cpu_only' | 'reject' | 'unknown'`
- `resolved_plan_id: str | null`
- `resolved_plan_summary: ManagedPlanSummary | null`

This lets setup step 1 and step 2 share a single backend call if desired.

### 2. Replace `/api/models/catalog` semantics
Current route returns static `CatalogModel[]`, which does not fit the new design.

Recommended change:
- Keep the route but change it to return a managed setup recommendation object, not a flat list.
- Better name long term: `/api/models/recommendation` or `/api/setup/managed-plan`.

Because the frontend currently expects `CatalogModel[]`, implementation should either:
- Add a new route and migrate the frontend cleanly, or
- Change the existing route and update all frontend call sites.

Recommended answer for this repo: add a new route, preserve `/api/models/catalog` temporarily if other UI still relies on it.

### 3. New response shape
Add schema models such as:
- `ResolvedModelRef`
- `ResolvedPlanSummary`
- `ManagedPlanResponse`

`ManagedPlanResponse` should include:
- `fingerprint_hash`
- `path`: `apple | gpu | cpu_only | reject`
- `plan_id`
- `plan_rank`
- `ctx`
- `helper_count`
- `runtime_priority`
- `runtime_forbidden`
- `required_launch_flags`
- `recommended_setup_mode`: `managed | byo`
- `action`: `proceed_managed | route_to_byo`
- `reason`
- `detection_warnings`
- `orchestrator { model, quant, device }`
- `summarizer { model, quant, device } | null`
- `utility { model, quant, device, count_min, count_max } | null`
- `optional_orchestrator | null`

This is the object the setup flow should use.

## Persistence Changes
Current persisted app settings only store:
- `setup_complete`
- `setup_mode`
- `theme`
- `active_models`

That is not enough for the managed resolver outcome.

Recommended persistence change:
- Add a JSON column to `AppSettings` named `managed_plan`.

Store at minimum:
- `fingerprint_hash`
- `path`
- `plan_id`
- `ctx`
- `helper_count`
- `resolved_at`
- `runtime_priority`
- selected model refs for orchestrator/summarizer/utility
- `detection_warnings`

Also keep `active_models`, but change its meaning in managed mode to be derived from the resolved plan, for example:
- `['qwen3.5-4b', 'granite4.0-h-micro-3b', 'qwen3.5-0.8b']`

Do not store only old symbolic IDs like `reasoner`, `summarizer`, `utility`; store real model IDs from the resolver.

Migration approach:
- Update SQLAlchemy model in `backend/app/models.py`.
- Add startup-time lightweight migration logic in `init_db()` to add the column if absent, or handle absent column defensively if the project has no formal migration tool yet.
- Preserve old rows by defaulting `managed_plan` to `{}` or `None`.

## Frontend Changes

### 1. Setup flow should stop thinking in terms of a generic catalog list
Current managed flow is:
- Step 1: `HardwareStep`
- Step 2: `RecommendStep` with `CatalogModel[]`
- Step 3: `DownloadStep` simulated progress on models with `fit === 'ok'`

New managed flow should be:
- Step 1: detect hardware and resolve managed plan
- Step 2: show exact selected plan and rationale
- Step 3: preserve current “download” step as a stub, but drive it from resolved plan models rather than static catalog rows

### 2. `HardwareStep.tsx`
Update copy and fields to reflect real detection and exact planing:
- Show CPU, RAM, GPU, VRAM as today.
- Add detected route summary once done:
  - `Managed GPU setup`
  - `Managed CPU-only setup`
  - `Apple Silicon setup`
  - `Bring your own local server`
- If detection warnings exist, surface them under the hardware summary.

### 3. `RecommendStep.tsx`
Replace flat fit-list UI with exact plan presentation.

The screen should show:
- Tier badge: exact plan ID such as `T1-floor-fp32`, `T4-high`, `CL1-minimum`, `A3`
- Route: `GPU`, `CPU-only`, `Apple Silicon`, or `BYO required`
- Orchestrator exact model and quant
- Summarizer exact model and quant if present
- Utility exact model and quant if present
- Context chosen by fit stage
- Helper count
- Runtime priority and any forbidden runtime note
- Rejection reason if path is `reject`

Examples the UI should render exactly when those plans resolve:
- RX 580 8GB + i5-7500 + 16GB DDR4 + Vulkan -> `T1-floor-fp32` -> orchestrator `qwen3.5-4b Q5_K_M` -> helper count `1`
- RX 580 8GB + Ryzen 3 3500X + 16GB -> `T1-floor-fp32` -> helper count `2`
- RTX 3060 12GB + Ryzen 7 5800X + 32GB -> `T3-plus` -> orchestrator `qwen3.5-9b Q6_K`
- GPU-less 32GB DDR5 dual-channel 6-core -> `CL1-minimum` -> orchestrator `qwen3.5-4b Q5_K_M`
- 4GB Polaris + 8GB RAM -> reject -> route to BYO path

### 4. `DownloadStep.tsx`
Keep it as a stub for now, but change the wording so it does not falsely claim real local download already exists.

Recommended behavior for this milestone:
- For managed plans, present “Preparing your managed setup” or “Managed runtime setup coming next”.
- If the product still needs the three-step feel, simulate preparation for the selected orchestrator/summarizer/utility models only.
- If the resolved action is `route_to_byo`, do not enter download step; redirect to BYO screen or show a CTA to switch.

### 5. `frontend/src/lib/api.ts`
Add types for the new managed-plan response object.
Replace or supplement `getModelCatalog()` with `getManagedPlanRecommendation()`.

## Resolver Behavior To Implement

### 1. Top-level routing
Implement exactly:
1. If `gpu_vendor == apple`, resolve Apple tiers only.
2. Else resolve discrete GPU tiers first.
3. If no GPU tier matches, resolve CPU-only tiers.
4. If no CPU-only tier matches, return reject/BYO route.

### 2. Deterministic ranking
- GPU tiers: sort by `rank DESC`, return first satisfied plan.
- CPU-only tiers: sort by `rank DESC`, return first satisfied plan.
- Apple tiers: sort by `rank DESC`, return first satisfied plan.
- Helper tiers: find highest satisfied CPU helper tier and highest satisfied RAM residency tier independently, then take `min()`.

### 3. Fit stage
Implement the GPU `fit()` logic from reference:
- Weight size from `_quant_weight_table_gb`
- KV from `_kv_cache_gb_per_1k_tokens`
- Fixed overhead from `global_constants`
- Decrease context in steps of `2048` until within `gpu_usable_fraction_of_free_vram`
- Clamp to `ctx_min`

For first implementation:
- GPU path: fully implement `fit()`.
- CPU-only path: keep simple `ctx = ctx_max` if RAM-fit variant is not yet implemented, but mark this clearly in code comments and response diagnostics.
- Apple path: keep `ctx = ctx_max` initially, also marked clearly.

### 4. Validation stage
Keep `smoke_test_stub()`.
For this repo milestone it should:
- Always return loaded success.
- Return a fake high tok/s.
- Mark response diagnostics as `validation_stubbed = true`.

This avoids pretending real runtime validation exists.

## Handling Incomplete Detection
This is the biggest repo-specific risk because your reference assumes richer probing than the repo has today.

Implement conservative fallback rules:
- Missing `gpu_fp16_support` must not qualify for fp16 tiers.
- Missing `gpu_backend_any` must not qualify for backend-constrained tiers like `T1-floor-fp32` unless the backend is explicitly observed.
- Missing `ram_channels` should fail CL1+ and only allow CL0-lite.
- Missing `ram_type` should fail CL1+ and only allow CL0-lite.
- Missing `avx2` should fail tiers that require `isa: ['avx2']`.
- Unknown Apple unified memory should fall back to total RAM heuristic only on macOS.

Surface the downgrade reason in `detection_warnings`, such as:
- `Could not verify Vulkan support; conservative routing skipped T1-floor-fp32.`
- `Could not verify DDR5 dual-channel memory; conservative routing skipped CL1-minimum and above.`
- `Could not verify AVX2 support; CPU-only managed tiers were not offered.`

## Exact Test Cases To Add
Create resolver-focused tests under `backend/tests/`.

### 1. Reference tier tests
1. RX 580 8GB + i5-7500 + 16GB DDR4 + Vulkan + no fp16
- Path: `gpu`
- Plan: `T1-floor-fp32`
- Helper count: `1`

2. RX 580 8GB + Ryzen 3 3500X 6-core + 16GB DDR4 + Vulkan + no fp16
- Path: `gpu`
- Plan: `T1-floor-fp32`
- Helper count: `2`

3. RTX 3060 12GB + Ryzen 7 5800X + 32GB DDR4 + cuda/vulkan + fp16
- Path: `gpu`
- Plan: `T3-plus`
- Orchestrator: `qwen3.5-9b` `Q6_K`

4. GPU-less laptop + 32GB DDR5 + dual-channel + 6-core + avx2
- Path: `cpu_only`
- Plan: `CL1-minimum`
- Orchestrator: `qwen3.5-4b` `Q5_K_M`

5. 4GB Polaris + 8GB RAM
- Path: `reject`
- Action: BYO route

### 2. Ranking tests
- A 16GB fp16 GPU must resolve `T4-high`, not `T3-plus`.
- An 8GB fp16 GPU must resolve `T2-standard-fp16`, not `T1-floor-fp32`.
- An Apple 48GB machine must resolve `A4`, not a GPU tier.

### 3. Conservative detection tests
- Missing `ram_channels` on 32GB DDR5 machine should fail `CL1-minimum` and route to `CL0-lite` or reject depending on other fields.
- Missing `gpu_backend_any` on 8GB fp32 AMD card should skip `T1-floor-fp32`.
- Missing `avx2` should block CPU-only managed tiers above reject minimum.

### 4. Fit tests
- Verify GPU context shrinks from `ctx_max` toward `ctx_min` when free VRAM is tight.
- Verify `ctx` never drops below `ctx_min`.

## Ordered Implementation Tasks
1. Add `hardware_catalog.json` to the backend with the exact catalog content.
2. Add loader module for catalog access.
3. Implement resolver dataclasses and pure functions in a new `hardware_resolver.py`.
4. Refactor `hardware.py` to separate UI summary, stable-fact probing, and live-resource probing.
5. Add a service entrypoint that returns `ManagedPlanResponse` from current hardware.
6. Extend API schemas in `backend/app/schemas/api.py`.
7. Add a new route for managed plan recommendation, preferably `/api/setup/managed-plan`.
8. Update `/api/system/hardware` to include resolved-plan summary or at least detection warnings and route info.
9. Extend persisted settings model with `managed_plan` JSON.
10. Update `init_db()` to tolerate existing databases and initialize the new field.
11. Update frontend API client types and fetchers.
12. Update `SetupFlow.tsx` to fetch managed plan response instead of static catalog.
13. Rewrite `RecommendStep.tsx` to render exact tier/model/runtime details.
14. Update `HardwareStep.tsx` to show detection diagnostics and route.
15. Update `DownloadStep.tsx` to reflect stubbed managed preparation instead of real download.
16. Add backend tests for the exact reference scenarios and ranking behavior.
17. Update README only if implementation agent chooses to document the new route after code lands.

## Acceptance Criteria
- Clicking `Set it up for me` uses the resolver-backed recommendation path, not the old static fit-table.
- The selected managed plan is deterministic for a given stable fingerprint.
- No tier thresholds or model names are hardcoded in resolver logic.
- The exact tier/model pairings above are encoded in data and surfaced in the UI.
- Reject cases route the user to BYO/local-server setup rather than pretending managed local setup is available.
- The setup UI clearly distinguishes GPU, CPU-only, Apple, and reject/BYO outcomes.
- The backend persists enough plan metadata to re-display the selected plan later.
- Tests cover the exact reference scenarios and conservative fallback behavior.

## Risks And Watchouts
- The current repo cannot yet probe all the hardware facts your design assumes. First implementation must degrade conservatively and explain why.
- The current managed download step is simulated. UI wording must not overclaim real automatic install until launcher/runtime code exists.
- Changing `/api/models/catalog` in place is riskier than adding a new route because current frontend expects `CatalogModel[]`.
- SQLite migration is ad hoc in this repo; changes to `AppSettings` must not break existing local databases.

## Recommended Route Names And Boundaries
- Keep `backend/app/services/hardware.py` focused on probing.
- Put pure catalog resolution in `backend/app/services/hardware_resolver.py`.
- Add `backend/app/routers/setup.py` or extend an existing router with `/api/setup/managed-plan`.
- Leave `backend/app/model_runtime/*` untouched for this milestone except where response wiring or persistence requires it.

## Follow-On Milestones After This Plan
Not part of this implementation, but the code should leave seams for:
1. Real Vulkan/AMD/Intel probing.
2. Real CPU ISA and RAM-channel detection.
3. Real managed downloader.
4. Real runtime selection and process launch.
5. Real smoke test and deterministic downgrade to next lower-rank plan.
6. Runtime adapter layer for Qwen, Granite, and optional gpt-oss.
