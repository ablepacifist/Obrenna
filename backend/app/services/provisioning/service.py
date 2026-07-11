from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ...db import SessionLocal
from ...model_runtime.config import RuntimeConfig
from ...models import AppSettings, ModelEndpoint, ProvisionEventLog, ProvisionJob, ProvisionJobItem
from ..hardware_catalog import load_catalog, resolve_ollama_pull_ref
from .adapters import adapter_for, normalize_model_ref


def _now() -> datetime:
    return datetime.now(timezone.utc)


logger = logging.getLogger(__name__)


class ProvisioningManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}

    def start(self, job_id: str) -> None:
        with self._lock:
            existing = self._threads.get(job_id)
            if existing and existing.is_alive():
                return
            self._events.setdefault(job_id, [])
            t = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
            self._threads[job_id] = t
            t.start()

    def emit(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "event": event_type,
            "payload": payload,
            "ts": _now().isoformat(),
        }
        with self._lock:
            self._events.setdefault(job_id, []).append(event)

        # Persist a coarse checkpoint for diagnostics/replay.
        db = SessionLocal()
        try:
            db.add(
                ProvisionEventLog(
                    job_id=job_id,
                    event_type=event_type,
                    payload=payload,
                )
            )
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()

    def events_since(self, job_id: str, cursor: int) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            arr = self._events.get(job_id, [])
            if cursor < 0:
                cursor = 0
            items = arr[cursor:]
            return items, len(arr)

    def _run_job(self, job_id: str) -> None:
        db = SessionLocal()
        started = time.perf_counter()
        try:
            job = db.get(ProvisionJob, job_id)
            if not job:
                return

            logger.info("provisioning job started", extra={"job_id": job_id})

            endpoint = db.get(ModelEndpoint, 1)
            cfg = RuntimeConfig(
                provider=endpoint.provider if endpoint else "openai_compatible",
                base_url=endpoint.base_url if endpoint else "http://localhost:11434/v1",
                api_key=endpoint.api_key if endpoint else "",
                models=endpoint.models if endpoint and endpoint.models else {},
            )
            adapter = adapter_for(cfg)

            job.status = "checking"
            db.commit()
            self.emit(job_id, "job_status", {"status": "checking"})

            items = (
                db.query(ProvisionJobItem)
                .filter(ProvisionJobItem.job_id == job_id)
                .order_by(ProvisionJobItem.created_at.asc())
                .all()
            )
            catalog = load_catalog()
            try:
                installed = adapter.list_installed_models()
            except httpx.ConnectError as exc:
                runtime_name = "Ollama" if cfg.runtime_kind == "ollama" else "the model runtime"
                raise RuntimeError(
                    f"Could not reach {runtime_name} at {cfg.base_url} — "
                    f"is it installed and running?"
                ) from exc

            all_ready = True
            for item in items:
                pull_ref = self._pull_ref(item.model_slug, catalog)
                item_ref_norm = normalize_model_ref(pull_ref)
                if self._is_installed(item_ref_norm, installed):
                    item.status = "ready"
                    item.progress_pct = 100
                    item.bytes_total = max(item.bytes_total, 1)
                    item.bytes_downloaded = item.bytes_total
                    item.error_message = None
                    db.commit()
                    self.emit(
                        job_id,
                        "model_ready",
                        {
                            "item_id": item.id,
                            "role": item.role,
                            "model_slug": item.model_slug,
                            "pull_ref": pull_ref,
                            "status": "ready",
                            "progress_pct": 100,
                        },
                    )
                    continue

                if not cfg.supports_pull:
                    item.status = "failed"
                    item.error_message = f"Runtime does not support pull: {cfg.runtime_kind}"
                    db.commit()
                    self.emit(
                        job_id,
                        "model_failed",
                        {
                            "item_id": item.id,
                            "role": item.role,
                            "model_slug": item.model_slug,
                            "pull_ref": pull_ref,
                            "status": "failed",
                            "error": item.error_message,
                        },
                    )
                    all_ready = False
                    continue

                item.status = "downloading"
                item.progress_pct = 0
                item.error_message = None
                db.commit()
                self.emit(
                    job_id,
                    "model_status",
                    {
                        "item_id": item.id,
                        "role": item.role,
                        "model_slug": item.model_slug,
                        "pull_ref": pull_ref,
                        "status": "downloading",
                        "progress_pct": 0,
                    },
                )

                try:
                    for p in adapter.pull_model(pull_ref):
                        item.status = "verifying" if p.done else "downloading"
                        item.progress_pct = p.percent if not p.done else 100
                        item.bytes_downloaded = p.completed
                        item.bytes_total = p.total
                        if p.error:
                            item.status = "failed"
                            item.error_message = p.error
                        db.commit()
                        self.emit(
                            job_id,
                            "model_progress",
                            {
                                "item_id": item.id,
                                "role": item.role,
                                "model_slug": item.model_slug,
                                "pull_ref": pull_ref,
                                "status": item.status,
                                "progress_pct": item.progress_pct,
                                "bytes_downloaded": item.bytes_downloaded,
                                "bytes_total": item.bytes_total,
                                "error": item.error_message,
                            },
                        )
                        if p.error:
                            break

                    if item.status != "failed":
                        item.status = "ready"
                        item.progress_pct = 100
                        item.error_message = None
                        db.commit()
                        self.emit(
                            job_id,
                            "model_ready",
                            {
                                "item_id": item.id,
                                "role": item.role,
                                "model_slug": item.model_slug,
                                "pull_ref": pull_ref,
                                "status": "ready",
                                "progress_pct": 100,
                            },
                        )
                    else:
                        all_ready = False
                except Exception as exc:  # noqa: BLE001
                    item.status = "failed"
                    item.error_message = str(exc)
                    db.commit()
                    self.emit(
                        job_id,
                        "model_failed",
                        {
                            "item_id": item.id,
                            "role": item.role,
                            "model_slug": item.model_slug,
                            "pull_ref": pull_ref,
                            "status": "failed",
                            "error": item.error_message,
                        },
                    )
                    all_ready = False

            job.completed_at = _now()
            if all_ready:
                job.status = "complete"
                settings = db.get(AppSettings, 1)
                if settings:
                    settings.setup_complete = True
                db.commit()
                self.emit(job_id, "job_status", {"status": "complete"})
                logger.info(
                    "provisioning job complete",
                    extra={"job_id": job_id, "duration_ms": int((time.perf_counter() - started) * 1000)},
                )
            else:
                job.status = "partial_failed"
                db.commit()
                self.emit(job_id, "job_status", {"status": "partial_failed"})
                logger.warning(
                    "provisioning job partial_failed",
                    extra={"job_id": job_id, "duration_ms": int((time.perf_counter() - started) * 1000)},
                )
        except Exception as exc:  # noqa: BLE001
            job = db.get(ProvisionJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = _now()
                db.commit()
            self.emit(job_id, "job_status", {"status": "failed", "error": str(exc)})
            logger.exception("provisioning job failed", extra={"job_id": job_id})
        finally:
            db.close()

    @staticmethod
    def _is_installed(model_ref: str, installed: set[str]) -> bool:
        if model_ref in installed:
            return True
        if ":" not in model_ref:
            prefix = f"{model_ref}:"
            return any(x.startswith(prefix) for x in installed)
        return False

    @staticmethod
    def _pull_ref(model_slug: str, catalog: dict[str, Any]) -> str:
        source_ref = resolve_ollama_pull_ref(catalog, model_slug)
        if source_ref:
            return source_ref
        return model_slug


provisioning_manager = ProvisioningManager()
