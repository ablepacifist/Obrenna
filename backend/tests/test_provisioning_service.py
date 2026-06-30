from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import AppSettings, ModelEndpoint, ProvisionJob, ProvisionJobItem
from app.services.provisioning.service import ProvisioningManager


class _FakeAdapterInstalledOnly:
    def list_installed_models(self):
        return {
            'radenadri/qwen3.5-0.8b-claude-4.6-opus-reasoning-distilled-gguf',
            'jewelzufo/unsloth_granite-4.0-h-350m-gguf',
        }

    def pull_model(self, _model_ref):
        yield from []


class _FakePullProgress:
    def __init__(self, *, status: str, completed: int = 0, total: int = 0, percent: int = 0, done: bool = False, error: str | None = None):
        self.status = status
        self.completed = completed
        self.total = total
        self.percent = percent
        self.done = done
        self.error = error


class _FakeAdapterPulling:
    def list_installed_models(self):
        return set()

    def pull_model(self, _model_ref):
        yield _FakePullProgress(status='downloading', completed=50, total=100, percent=50)
        yield _FakePullProgress(status='success', completed=100, total=100, percent=100, done=True)


class _FakeAdapterFailOne:
    def __init__(self):
        self._count = 0

    def list_installed_models(self):
        return set()

    def pull_model(self, _model_ref):
        self._count += 1
        if self._count == 1:
            yield _FakePullProgress(status='failed', error='bad model', done=True)
        else:
            yield _FakePullProgress(status='success', completed=100, total=100, percent=100, done=True)


def _seed_db(Session):
    with Session() as db:
        db.add(AppSettings(id=1, setup_complete=False, setup_mode='managed', theme='light', active_models=[], managed_plan={}))
        db.add(ModelEndpoint(id=1, provider='openai_compatible', base_url='http://localhost:11434/v1', api_key='', models={}))
        db.add(ProvisionJob(id='job-1', fingerprint_hash='fp', runtime_kind='ollama', status='queued'))
        db.add(ProvisionJobItem(job_id='job-1', role='orchestrator', model_slug='qwen3.5-0.8b-claude-opus-reasoning-distilled', quant='Q4_K_M', status='queued'))
        db.add(ProvisionJobItem(job_id='job-1', role='summarizer', model_slug='granite-4.0-h-350m', quant='Q4_K_M', status='queued'))
        db.commit()


def test_service_marks_ready_when_models_already_installed(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    _seed_db(Session)

    monkeypatch.setattr('app.services.provisioning.service.SessionLocal', Session)
    monkeypatch.setattr('app.services.provisioning.service.adapter_for', lambda _cfg: _FakeAdapterInstalledOnly())

    manager = ProvisioningManager()
    manager._run_job('job-1')

    with Session() as db:
        job = db.get(ProvisionJob, 'job-1')
        assert job is not None
        assert job.status == 'complete'
        items = db.query(ProvisionJobItem).filter(ProvisionJobItem.job_id == 'job-1').all()
        assert all(i.status == 'ready' for i in items)


def test_service_downloads_missing_models(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    _seed_db(Session)

    monkeypatch.setattr('app.services.provisioning.service.SessionLocal', Session)
    monkeypatch.setattr('app.services.provisioning.service.adapter_for', lambda _cfg: _FakeAdapterPulling())

    manager = ProvisioningManager()
    manager._run_job('job-1')

    with Session() as db:
        job = db.get(ProvisionJob, 'job-1')
        assert job is not None
        assert job.status == 'complete'


def test_service_partial_failed_when_one_model_fails(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    _seed_db(Session)

    monkeypatch.setattr('app.services.provisioning.service.SessionLocal', Session)
    monkeypatch.setattr('app.services.provisioning.service.adapter_for', lambda _cfg: _FakeAdapterFailOne())

    manager = ProvisioningManager()
    manager._run_job('job-1')

    with Session() as db:
        job = db.get(ProvisionJob, 'job-1')
        assert job is not None
        assert job.status == 'partial_failed'
        items = db.query(ProvisionJobItem).filter(ProvisionJobItem.job_id == 'job-1').all()
        assert any(i.status == 'failed' for i in items)
