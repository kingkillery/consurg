import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from consurg.cli import app
from consurg.pk_agents import SCOPE_SELECTOR_AGENT

runner = CliRunner()


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _read_scope(tmp_path: Path) -> dict:
    return yaml.safe_load((tmp_path / ".consurg.yaml").read_text())


# CS-004: init and add

def test_init_creates_valid_yaml(in_tmp):
    result = runner.invoke(app, ["init", "my-scope"])
    assert result.exit_code == 0
    data = _read_scope(in_tmp)
    assert data["version"] == 1
    assert data["scope"] == "my-scope"
    assert data["active"] is True
    assert data["working_set"] == []


def test_init_default_name(in_tmp):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    data = _read_scope(in_tmp)
    assert data["scope"] == in_tmp.name


def test_add_to_working_set(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "src/*.py", "main.py"])
    assert result.exit_code == 0
    data = _read_scope(in_tmp)
    assert data["working_set"] == ["src/*.py", "main.py"]


def test_add_to_reference(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "--read", "docs/*.md"])
    assert result.exit_code == 0
    data = _read_scope(in_tmp)
    assert data["reference"] == ["docs/*.md"]


def test_add_to_signatures(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["add", "--sig", "types/*.pyi"])
    assert result.exit_code == 0
    data = _read_scope(in_tmp)
    assert data["signatures"] == ["types/*.pyi"]


def test_add_no_duplicates(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "src/*.py"])
    runner.invoke(app, ["add", "src/*.py"])
    data = _read_scope(in_tmp)
    assert data["working_set"] == ["src/*.py"]


def test_add_without_init(in_tmp):
    result = runner.invoke(app, ["add", "file.py"])
    assert result.exit_code == 1


# CS-005: on, off, status

def test_on_activates(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["off"])
    result = runner.invoke(app, ["on"])
    assert result.exit_code == 0
    data = _read_scope(in_tmp)
    assert data["active"] is True


def test_off_deactivates(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["off"])
    assert result.exit_code == 0
    data = _read_scope(in_tmp)
    assert data["active"] is False


def test_status_shows_info(in_tmp):
    runner.invoke(app, ["init", "test-scope"])
    runner.invoke(app, ["add", "src/*.py"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "test-scope" in result.output


def test_status_no_scope(in_tmp):
    result = runner.invoke(app, ["status"])
    assert "No scope defined" in result.output


def test_on_no_scope(in_tmp):
    result = runner.invoke(app, ["on"])
    assert result.exit_code == 1


# CS-006: remove

def test_remove_from_working_set(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "a.py", "b.py"])
    result = runner.invoke(app, ["remove", "a.py"])
    assert result.exit_code == 0
    data = _read_scope(in_tmp)
    assert data["working_set"] == ["b.py"]


def test_remove_warns_missing(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["remove", "nonexistent.py"])
    assert "not found" in result.output


# CS-007: map

def test_map_runs(in_tmp):
    runner.invoke(app, ["init", "map-test"])
    (in_tmp / "src").mkdir()
    (in_tmp / "src" / "main.py").write_text("print('hello')")
    (in_tmp / "readme.md").write_text("# readme")
    runner.invoke(app, ["add", "src/*.py"])
    runner.invoke(app, ["add", "--read", "*.md"])
    result = runner.invoke(app, ["map"])
    assert result.exit_code == 0


def test_map_no_scope(in_tmp):
    result = runner.invoke(app, ["map"])
    assert "No scope defined" in result.output


# CS-010: drift detection

def test_drift_warning_at_2x(in_tmp):
    runner.invoke(app, ["init"])
    # Set original count manually
    data = _read_scope(in_tmp)
    data["metadata"] = {"original_count": 2}
    data["working_set"] = ["a.py", "b.py"]
    with open(in_tmp / ".consurg.yaml", "w") as f:
        yaml.dump(data, f)

    result = runner.invoke(app, ["add", "c.py", "d.py"])
    assert "drift" in result.output.lower() or "Drift" in result.output


def test_no_drift_below_2x(in_tmp):
    runner.invoke(app, ["init"])
    data = _read_scope(in_tmp)
    data["metadata"] = {"original_count": 5}
    data["working_set"] = ["a.py"]
    with open(in_tmp / ".consurg.yaml", "w") as f:
        yaml.dump(data, f)

    result = runner.invoke(app, ["add", "b.py"])
    assert "drift" not in result.output.lower()


# CS-011: pin and unpin

def test_pin_refuses_existing(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["pin"])
    assert result.exit_code == 1


def test_unpin_removes_file(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["unpin"])
    assert result.exit_code == 0
    assert not (in_tmp / ".consurg.yaml").exists()


def test_unpin_no_file(in_tmp):
    result = runner.invoke(app, ["unpin"])
    assert "No scope file" in result.output


def test_scaffold_pk_agents_creates_expected_files(in_tmp):
    result = runner.invoke(app, ["scaffold-pk-agents"])
    assert result.exit_code == 0

    selector = in_tmp / ".agents" / "pk-agents" / "consurg-scope-selector.pk-agent"
    summarizer = in_tmp / ".agents" / "pk-agents" / "consurg-excluded-summarizer.pk-agent"
    runbook = in_tmp / ".agents" / "pk-agents" / "README.md"

    assert selector.exists()
    assert summarizer.exists()
    assert runbook.exists()

    assert "include_context" in selector.read_text(encoding="utf-8")
    assert "excluded-context.md" in summarizer.read_text(encoding="utf-8")


def test_scaffold_pk_agents_no_overwrite_without_force(in_tmp):
    runner.invoke(app, ["scaffold-pk-agents"])
    selector = in_tmp / ".agents" / "pk-agents" / "consurg-scope-selector.pk-agent"
    selector.write_text("custom", encoding="utf-8")

    result = runner.invoke(app, ["scaffold-pk-agents"])
    assert result.exit_code == 0
    assert "already exists" in result.output.lower()
    assert selector.read_text(encoding="utf-8") == "custom"


def test_scaffold_pk_agents_force_overwrites(in_tmp):
    runner.invoke(app, ["scaffold-pk-agents"])
    selector = in_tmp / ".agents" / "pk-agents" / "consurg-scope-selector.pk-agent"
    selector.write_text("custom", encoding="utf-8")

    result = runner.invoke(app, ["scaffold-pk-agents", "--force"])
    assert result.exit_code == 0
    assert "custom" not in selector.read_text(encoding="utf-8")


def test_apply_proposal_preview_and_apply(in_tmp):
    proposal_dir = in_tmp / ".consurg" / "recommendations"
    proposal_dir.mkdir(parents=True)
    proposal = {
        "task": "auth bugfix",
        "include_context": ["src/auth/login.py"],
        "read_only": ["src/core/db.py"],
        "exclude": ["docs/**"],
        "rationale": [],
        "risks": [],
    }
    with open(proposal_dir / "scope-proposal.yaml", "w", encoding="utf-8") as f:
        yaml.dump(proposal, f)

    preview = runner.invoke(app, ["apply-proposal"])
    assert preview.exit_code == 0
    assert "Preview only" in preview.output
    assert not (in_tmp / ".consurg.yaml").exists()

    applied = runner.invoke(app, ["apply-proposal", "--apply"])
    assert applied.exit_code == 0
    data = _read_scope(in_tmp)
    assert data["working_set"] == ["src/auth/login.py"]
    assert data["reference"] == ["src/core/db.py"]
    assert data["reason"] == "auth bugfix"


def test_apply_proposal_rejects_missing_keys(in_tmp):
    proposal_dir = in_tmp / ".consurg" / "recommendations"
    proposal_dir.mkdir(parents=True)
    with open(proposal_dir / "scope-proposal.yaml", "w", encoding="utf-8") as f:
        yaml.dump({"include_context": []}, f)

    result = runner.invoke(app, ["apply-proposal", "--apply"])
    assert result.exit_code == 1
    assert "missing keys" in result.output


def test_scope_selector_agent_prompt_has_required_output_keys():
    assert "`include_context`" in SCOPE_SELECTOR_AGENT
    assert "`read_only`" in SCOPE_SELECTOR_AGENT
    assert "`exclude`" in SCOPE_SELECTOR_AGENT
