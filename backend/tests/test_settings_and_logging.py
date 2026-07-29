import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.settings import AppSettings, DEFAULT_FRONTEND_ORIGIN, load_app_settings


def test_settings_load_frontend_origin_before_app_construction(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        (
            "FRONTEND_ORIGIN=https://frontend.example.com/\n"
            "LOG_LEVEL=DEBUG\n"
            f"PLAN_STORAGE_PATH={tmp_path / 'configured-plans.db'}\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("PLAN_STORAGE_PATH", raising=False)

    settings = load_app_settings(env_file)

    assert settings.allowed_origins == [
        DEFAULT_FRONTEND_ORIGIN,
        "https://frontend.example.com",
    ]
    assert settings.log_level == 10
    assert settings.plan_storage_path == tmp_path / "configured-plans.db"


def test_structured_info_log_is_emitted_in_a_plain_process() -> None:
    command = (
        "from backend.observability import configure_logging, log_workflow_event;"
        "configure_logging();"
        "log_workflow_event(workflow_name='startup',step_name='check',status='success')"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=os.fspath(Path(__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["workflow_name"] == "startup"
    assert payload["step_name"] == "check"
    assert payload["status"] == "success"


def test_production_data_configuration_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///unsafe.db")
    monkeypatch.setenv("DATABASE_AUTO_MIGRATE", "false")
    monkeypatch.delenv("AUDIT_SIGNING_KEYS_JSON", raising=False)
    monkeypatch.delenv("AUDIT_ACTIVE_KEY_ID", raising=False)
    monkeypatch.delenv("AUDIT_SINK_URL", raising=False)

    with pytest.raises(ValueError, match="PostgreSQL"):
        AppSettings.from_env()

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://agent:secret@db.example.com/agent",
    )
    with pytest.raises(ValueError, match="audit signing key"):
        AppSettings.from_env()

    monkeypatch.setenv(
        "AUDIT_SIGNING_KEYS_JSON",
        json.dumps({"2026-q3": "x" * 32}),
    )
    monkeypatch.setenv("AUDIT_ACTIVE_KEY_ID", "2026-q3")
    with pytest.raises(ValueError, match="AUDIT_SINK_URL"):
        AppSettings.from_env()

    monkeypatch.setenv("AUDIT_SINK_URL", "https://audit.example.com/events")
    settings = AppSettings.from_env()

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.audit_active_key_id == "2026-q3"
    assert settings.audit_sink_required is True
    assert settings.model_job_worker_required is True
    rendered = repr(settings)
    assert "secret@db.example.com" not in rendered
    assert "x" * 32 not in rendered
