from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ModelEndpoint
from ..model_runtime.client import list_models
from ..model_runtime.config import RuntimeConfig
from ..schemas.api import CatalogModel
from ..services.plan_models import resolve_plan_models
from ..services.hardware_catalog import load_catalog, resolve_ollama_pull_ref
from ..services.provisioning.adapters import normalize_model_ref

router = APIRouter(prefix="/api/models")


def _ref_matches_available(pull_ref: str, available_lower: list[str]) -> bool:
    """Match a catalog model against a runtime's available-model list.

    The runtime reports fully-qualified ids (e.g. an Ollama id like
    ``radenadri/qwen3.5-...-gguf:latest``), while the catalog stores a pull ref
    that may omit the ``:tag``. Compare the way provisioning's installed-check
    does: tag-insensitive, treating a tag-less ref as a prefix match.
    """
    ref = normalize_model_ref(pull_ref)
    if not ref:
        return False
    for avail in available_lower:
        if avail == ref:
            return True
        # Tag-less ref ("owner/name") matches "owner/name:tag".
        if ":" not in ref and avail.split(":", 1)[0] == ref:
            return True
    return False


@router.get("/catalog", response_model=list[CatalogModel])
def get_catalog(db: Session = Depends(get_db)):
    """Models assigned to this machine's hardware tier (from the managed plan).

    Returned in CatalogModel shape for the setup download step. These are the
    real tier-assigned models — there is no fictional/static catalog.
    """
    ep = db.get(ModelEndpoint, 1)
    runtime_base_url = ep.base_url if ep else None
    return [
        CatalogModel(
            id=m["role"],
            name=m["display_name"],
            role=m["label"],
            size=m["size"] or "—",
            size_gb=m["size_gb"],
            fit="ok",
            note="Assigned to your hardware tier",
        )
        for m in resolve_plan_models(runtime_base_url=runtime_base_url)
    ]


def _role_state(installed: bool, loaded: bool) -> str:
    """Map installed/loaded booleans to a tri-state.

    - "loaded":    in memory and serving → the model is really working.
    - "installed": on disk but not started → can chat after on-demand load.
    - "missing":   not on this machine → must be downloaded first.
    """
    if loaded:
        return "loaded"
    if installed:
        return "installed"
    return "missing"


@router.get("/status")
async def get_model_status(db: Session = Depends(get_db)):
    """Live status of the models assigned to this machine's hardware tier.

    The model list comes from the resolved managed plan (hardware_catalog.json),
    NOT from stored endpoint config. For each role we report a tri-state:
      - missing:   not installed on this machine (download required)  → red
      - installed: on disk but not currently loaded into memory       → yellow
      - loaded:    resident in memory and serving (verified working)  → green

    The orchestrator role is the model the user actually chats to, so
    ``chat_ready`` reflects that role being loaded and the runtime reachable.
    """
    ep = db.get(ModelEndpoint, 1)
    runtime_base_url = ep.base_url if ep else None
    plan_models = resolve_plan_models(runtime_base_url=runtime_base_url)

    roles_base = [
        {
            "role": m["role"],
            "label": m["label"],
            "display_name": m["display_name"],
            "model": m["model"],
        }
        for m in plan_models
    ]

    def _shape(roles, *, connected, all_ready, chat_ready, error):
        return {
            "connected": connected,
            "all_ready": all_ready,
            "chat_ready": chat_ready,
            "roles": roles,
            "error": error,
        }

    if not ep or not ep.base_url:
        return _shape(
            [{**r, "available": False, "state": "missing"} for r in roles_base],
            connected=False, all_ready=False, chat_ready=False,
            error="No model endpoint configured",
        )

    config = RuntimeConfig(
        provider=ep.provider or "openai",
        base_url=ep.base_url,
        api_key=ep.api_key or "",
        models=ep.models or {},
    )

    try:
        installed_models = await list_models(config, timeout=5.0)
    except Exception as exc:
        return _shape(
            [{**r, "available": False, "state": "missing"} for r in roles_base],
            connected=False, all_ready=False, chat_ready=False, error=str(exc),
        )

    installed_lower = [a.lower() for a in installed_models]

    # Which models are actually resident in memory (Ollama /api/ps). Best-effort:
    # runtimes that can't report this return an empty set → roles show as
    # "installed" (yellow) rather than falsely "loaded".
    from ..services.provisioning.adapters import adapter_for
    try:
        loaded_lower = list(adapter_for(config).list_loaded_models())
    except Exception:
        loaded_lower = []

    catalog = load_catalog()

    roles = []
    for r in roles_base:
        # Resolve the same Ollama pull ref provisioning uses, then match the
        # runtime's reported ids tag-insensitively. Comparing the bare catalog
        # slug here would miss namespaced refs (e.g. "owner/name:latest") and
        # report an installed model as "Not loaded".
        pull_ref = resolve_ollama_pull_ref(catalog, r["model"])
        is_installed = _ref_matches_available(pull_ref, installed_lower)
        is_loaded = _ref_matches_available(pull_ref, loaded_lower)
        state = _role_state(is_installed, is_loaded)
        roles.append({
            "role": r["role"],
            "label": r["label"],
            "display_name": r["display_name"],
            "available": is_installed,  # back-compat: "available" == on disk
            "state": state,
        })

    all_ready = bool(roles) and all(r["available"] for r in roles)
    orch = next((r for r in roles if r["role"] == "orchestrator"), None)
    chat_ready = bool(orch and orch["state"] == "loaded")
    return _shape(roles, connected=True, all_ready=all_ready, chat_ready=chat_ready, error=None)
