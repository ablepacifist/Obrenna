"""Setup routes for managed hardware detection and plan resolution."""
import json
import time

from fastapi import APIRouter, Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..db import SessionLocal
from ..model_runtime.config import RuntimeConfig
from ..models import AppSettings, ModelEndpoint, ProvisionJob, ProvisionJobItem
from ..schemas.api import ManagedPlanResponse
from ..services.hardware import resolve_managed_plan
from ..services.provisioning import provisioning_manager

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/managed-plan", response_model=ManagedPlanResponse)
def get_managed_plan(db: Session = Depends(get_db)):
    """Detect hardware and resolve a managed plan."""
    endpoint = db.get(ModelEndpoint, 1)
    runtime_base_url = endpoint.base_url if endpoint else None
    plan = resolve_managed_plan(runtime_base_url=runtime_base_url)
    return ManagedPlanResponse(**plan)


@router.post("/managed-plan/confirm")
def confirm_managed_plan(db: Session = Depends(get_db)):
    """Persist the resolved managed plan and create a provisioning job record."""
    endpoint = db.get(ModelEndpoint, 1)
    cfg = RuntimeConfig(
        provider=endpoint.provider if endpoint else "openai_compatible",
        base_url=endpoint.base_url if endpoint else "http://localhost:11434/v1",
        api_key=endpoint.api_key if endpoint else "",
        models=endpoint.models if endpoint and endpoint.models else {},
    )

    plan = resolve_managed_plan(runtime_base_url=cfg.base_url)
    models = _models_from_plan(plan)

    settings = db.get(AppSettings, 1)
    settings.managed_plan = plan
    settings.setup_mode = "managed"
    settings.setup_complete = False
    settings.active_models = [m["model"] for m in models]

    fingerprint_hash = plan.get("fingerprint_hash") or ""
    existing_job = (
        db.query(ProvisionJob)
        .filter(
            ProvisionJob.fingerprint_hash == fingerprint_hash,
            ProvisionJob.status.in_(["queued", "checking", "downloading", "verifying"]),
        )
        .order_by(ProvisionJob.started_at.desc())
        .first()
    )

    if existing_job:
        db.commit()
        return {
            "confirmed": True,
            "plan": plan,
            "job_id": existing_job.id,
            "status": existing_job.status,
            "runtime_kind": existing_job.runtime_kind,
            "supports_pull": cfg.supports_pull,
            "supports_streaming_progress": cfg.supports_streaming_progress,
            "reused": True,
        }

    job = ProvisionJob(
        fingerprint_hash=fingerprint_hash,
        runtime_kind=cfg.runtime_kind,
        status="queued",
    )
    db.add(job)
    db.flush()

    for model in models:
        db.add(
            ProvisionJobItem(
                job_id=job.id,
                role=model["role"],
                model_slug=model["model"],
                quant=model.get("quant") or "",
                status="queued",
            )
        )

    db.commit()
    db.refresh(job)

    provisioning_manager.start(job.id)

    return {
        "confirmed": True,
        "plan": plan,
        "job_id": job.id,
        "status": job.status,
        "runtime_kind": job.runtime_kind,
        "supports_pull": cfg.supports_pull,
        "supports_streaming_progress": cfg.supports_streaming_progress,
        "reused": False,
    }


@router.get("/provisioning/{job_id}")
def get_provisioning_job(job_id: str, db: Session = Depends(get_db)):
    """Return provisioning job snapshot including per-model item states."""
    job = db.get(ProvisionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Provisioning job not found")

    items = (
        db.query(ProvisionJobItem)
        .filter(ProvisionJobItem.job_id == job_id)
        .order_by(ProvisionJobItem.created_at.asc())
        .all()
    )
    return {
        "id": job.id,
        "fingerprint_hash": job.fingerprint_hash,
        "runtime_kind": job.runtime_kind,
        "status": job.status,
        "error_message": job.error_message,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "items": [
            {
                "id": item.id,
                "role": item.role,
                "model_slug": item.model_slug,
                "quant": item.quant,
                "status": item.status,
                "progress_pct": item.progress_pct,
                "bytes_downloaded": item.bytes_downloaded,
                "bytes_total": item.bytes_total,
                "error_message": item.error_message,
                "updated_at": item.updated_at,
            }
            for item in items
        ],
    }


@router.get("/provisioning/{job_id}/events")
def get_provisioning_events(job_id: str, cursor: int = 0, db: Session = Depends(get_db)):
    """SSE stream of provisioning events for a job."""
    job = db.get(ProvisionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Provisioning job not found")

    def event_gen():
        idx = max(cursor, 0)
        heartbeat_at = time.time()
        while True:
            events, idx = provisioning_manager.events_since(job_id, idx)
            for ev in events:
                yield f"event: {ev['event']}\n"
                yield f"data: {json.dumps(ev)}\n\n"

            with SessionLocal() as reader:
                current = reader.get(ProvisionJob, job_id)
            if current is None:
                yield "event: job_status\n"
                yield 'data: {"event":"job_status","payload":{"status":"failed","error":"job_deleted"}}\n\n'
                break

            if current.status in {"complete", "partial_failed", "failed"}:
                terminal, idx = provisioning_manager.events_since(job_id, idx)
                for ev in terminal:
                    yield f"event: {ev['event']}\n"
                    yield f"data: {json.dumps(ev)}\n\n"
                break

            now = time.time()
            if now - heartbeat_at >= 10:
                heartbeat_at = now
                yield ": keepalive\n\n"
            time.sleep(0.4)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/provisioning/{job_id}/retry")
def retry_provisioning(job_id: str, db: Session = Depends(get_db)):
    """Reset failed items and restart background provisioning for this job."""
    job = db.get(ProvisionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Provisioning job not found")

    failed_items = (
        db.query(ProvisionJobItem)
        .filter(ProvisionJobItem.job_id == job_id, ProvisionJobItem.status == "failed")
        .all()
    )
    if not failed_items:
        return {"ok": True, "job_id": job_id, "status": job.status, "retried": 0}

    for item in failed_items:
        item.status = "queued"
        item.error_message = None
        item.progress_pct = 0
        item.bytes_downloaded = 0
        item.bytes_total = 0

    job.status = "queued"
    job.error_message = None
    job.completed_at = None
    db.commit()

    provisioning_manager.emit(job_id, "job_status", {"status": "queued", "reason": "retry"})
    provisioning_manager.start(job_id)
    return {"ok": True, "job_id": job_id, "status": "queued", "retried": len(failed_items)}


def _models_from_plan(plan: dict) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for role in ("orchestrator", "summarizer", "utility"):
        ref = plan.get(role)
        if isinstance(ref, dict) and ref.get("model"):
            out.append(
                {
                    "role": role,
                    "model": str(ref.get("model")),
                    "quant": str(ref.get("quant") or ""),
                }
            )
    return out
