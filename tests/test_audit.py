from datetime import UTC, datetime, timedelta

from consurg.audit import AuditConfig, load_audit_config, persist_trace, prune_runs


def test_load_audit_config_from_file(tmp_path):
    (tmp_path / ".consurg-audit.yaml").write_text(
        "\n".join(
            [
                "enabled: true",
                "storage_path: .pk-agent/runs",
                "max_runs: 5",
                "max_age_days: 2",
                "max_bytes: 1024",
            ]
        ),
        encoding="utf-8",
    )
    cfg = load_audit_config(tmp_path, env={})
    assert cfg.enabled is True
    assert cfg.max_runs == 5
    assert cfg.max_age_days == 2
    assert cfg.max_bytes == 1024
    assert cfg.storage_path == tmp_path / ".pk-agent" / "runs"


def test_env_overrides_file(tmp_path):
    (tmp_path / ".consurg-audit.yaml").write_text("max_runs: 5\n", encoding="utf-8")
    cfg = load_audit_config(tmp_path, env={"CONSURG_AUDIT_MAX_RUNS": "12", "CONSURG_AUDIT_PERSIST": "1"})
    assert cfg.enabled is True
    assert cfg.max_runs == 12


def test_prune_runs_by_max_runs(tmp_path):
    cfg = AuditConfig(enabled=True, storage_path=tmp_path / ".pk-agent" / "runs", max_runs=2, max_age_days=999, max_bytes=99999999)
    now = datetime.now(UTC)
    for i in range(3):
        persist_trace(
            config=cfg,
            run_id=f"run-{i}",
            started_at=now + timedelta(seconds=i),
            tool_calls=[],
        )
    run_dirs = [p for p in cfg.storage_path.iterdir() if p.is_dir()]
    assert len(run_dirs) == 2


def test_redaction_applies_to_sensitive_fields(tmp_path):
    cfg = AuditConfig(enabled=True, storage_path=tmp_path / ".pk-agent" / "runs")
    trace = persist_trace(
        config=cfg,
        run_id="x",
        started_at=datetime.now(UTC),
        tool_calls=[
            {
                "name": "pk-agent",
                "type": "tool",
                "start_time": 0,
                "duration_ms": 1,
                "success": True,
                "input": {"token": "sk-secret-abc123"},
                "output": {"Authorization": "Bearer abc.def.ghi"},
            }
        ],
    )
    payload = trace.read_text(encoding="ascii")
    assert "sk-secret-abc123" not in payload
    assert "abc.def.ghi" not in payload
    assert "[REDACTED]" in payload
