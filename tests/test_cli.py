import shutil
import subprocess
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


def test_add_normalizes_backslashes(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "src\\main.py"])
    data = _read_scope(in_tmp)
    assert data["working_set"] == ["src/main.py"]


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


def test_status_displays_forward_slashes(in_tmp):
    runner.invoke(app, ["init"])
    data = _read_scope(in_tmp)
    data["working_set"] = ["src\\main.py"]
    with open(in_tmp / ".consurg.yaml", "w") as f:
        yaml.dump(data, f)

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "src/main.py" in result.output
    assert "src\\main.py" not in result.output


def test_status_no_scope(in_tmp):
    result = runner.invoke(app, ["status"])
    assert "No scope defined" in result.output


def test_audit_status_defaults(in_tmp):
    result = runner.invoke(app, ["audit-status"])
    assert result.exit_code == 0
    assert "enabled" in result.output
    assert "false" in result.output
    assert "run_dirs" in result.output


def test_audit_status_with_env_and_runs(in_tmp):
    runs = in_tmp / ".pk-agent" / "runs" / "20260212T010203Z"
    runs.mkdir(parents=True)
    (runs / "trace.json").write_text('{"schema_version":"1.0"}', encoding="ascii")

    result = runner.invoke(
        app,
        ["audit-status"],
        env={
            "CONSURG_AUDIT_PERSIST": "1",
            "CONSURG_AUDIT_MAX_RUNS": "9",
            "CONSURG_AUDIT_MAX_AGE_DAYS": "3",
            "CONSURG_AUDIT_MAX_BYTES": "2048",
        },
    )
    assert result.exit_code == 0
    assert "true" in result.output
    assert "9" in result.output
    assert "3" in result.output
    assert "2048" in result.output
    assert "1" in result.output


def test_off_shows_hint(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["off"])
    assert "Hint: Run consurg clean" in result.output


def test_on_no_scope(in_tmp):
    result = runner.invoke(app, ["on"])
    assert result.exit_code == 1


# CS-011: clean

def test_clean_removes_scope_file(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["clean"])
    assert result.exit_code == 0
    assert not (in_tmp / ".consurg.yaml").exists()


def test_clean_keep_scope(in_tmp):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["clean", "--keep-scope"])
    assert result.exit_code == 0
    assert (in_tmp / ".consurg.yaml").exists()


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


def test_map_scoped_only(in_tmp):
    runner.invoke(app, ["init", "scoped-test"])
    runner.invoke(app, ["add", "a.py"])
    (in_tmp / "a.py").write_text("")
    (in_tmp / "b.py").write_text("")

    result_all = runner.invoke(app, ["map"])
    assert "a.py" in result_all.output

    result_scoped = runner.invoke(app, ["map", "--scoped-only"])
    assert "a.py" in result_scoped.output
    # b.py is T0 blocked so should be hidden
    assert "b.py" not in result_scoped.output


def test_map_depth_limit(in_tmp):
    runner.invoke(app, ["init", "depth-test"])
    runner.invoke(app, ["add", "*.py"])
    (in_tmp / "top.py").write_text("")
    sub = in_tmp / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("")

    result = runner.invoke(app, ["map", "--depth", "1"])
    assert "top.py" in result.output
    assert "deep.py" not in result.output

@pytest.mark.skipif(shutil.which("git") is None, reason="git is required")
def test_map_includes_untracked_and_hides_ignored_files(in_tmp):
    subprocess.run(["git", "init", "-q"], cwd=in_tmp, check=True)
    (in_tmp / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (in_tmp / "tracked.py").write_text("tracked", encoding="utf-8")
    (in_tmp / "untracked.py").write_text("untracked", encoding="utf-8")
    (in_tmp / "ignored.py").write_text("ignored", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "tracked.py"], cwd=in_tmp, check=True
    )
    runner.invoke(app, ["init", "discovery-test"])

    result = runner.invoke(app, ["map"])

    assert result.exit_code == 0
    assert "tracked.py" in result.output
    assert "untracked.py" in result.output
    assert "ignored.py" not in result.output


def test_map_warns_for_large_file_sets(in_tmp, monkeypatch):
    runner.invoke(app, ["init", "large-test"])
    monkeypatch.setattr(
        "consurg.cli._repo_files",
        lambda: [Path(f"file-{index}.py") for index in range(5001)],
    )

    result = runner.invoke(app, ["map", "--scoped-only"])

    assert result.exit_code == 0
    assert "Warning: 5001 files found" in result.output



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


def test_file_context_print_mode_respects_denylist(in_tmp):
    (in_tmp / "allowed.py").write_text("print('allowed')", encoding="utf-8")
    (in_tmp / "blocked.secret").write_text("secret", encoding="utf-8")
    with (in_tmp / ".consurg.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(
            {
                "file_context_ui": {
                    "never_include": ["*.secret"],
                    "max_file_bytes": 2048,
                    "max_total_bytes": 4096,
                    "hide_excluded": False,
                }
            },
            f,
        )

    result = runner.invoke(app, ["file-context", "--print", "allowed.py", "blocked.secret"])
    assert result.exit_code == 0
    assert "allowed.py" in result.output
    assert "blocked.secret" not in result.output


def test_file_context_print_mode_includes_readme(in_tmp):
    (in_tmp / "README.md").write_text("# Project README", encoding="utf-8")

    result = runner.invoke(app, ["file-context", "--print", "README.md"])
    assert result.exit_code == 0
    assert "## FILE: README.md" in result.output
    assert "# Project README" in result.output


# --- prompt command tests ---

def test_prompt_no_scope(in_tmp):
    result = runner.invoke(app, ["prompt"])
    assert result.exit_code == 0
    assert "INACTIVE" in result.output
    assert "T4=0" in result.output
    assert "T3=0" in result.output
    assert "T2=0" in result.output
    assert "T1=0" in result.output


def test_prompt_active_scope(in_tmp):
    runner.invoke(app, ["init", "my-scope"])
    runner.invoke(app, ["add", "src/*.py"])
    runner.invoke(app, ["add", "--read", "docs/*.md"])
    result = runner.invoke(app, ["prompt"])
    assert result.exit_code == 0
    assert "my-scope" in result.output
    assert "ACTIVE" in result.output
    assert "T4=1" in result.output
    assert "T3=1" in result.output


def test_prompt_inactive_scope(in_tmp):
    runner.invoke(app, ["init", "my-scope"])
    runner.invoke(app, ["off"])
    result = runner.invoke(app, ["prompt"])
    assert result.exit_code == 0
    assert "INACTIVE" in result.output


def test_prompt_no_timestamp(in_tmp):
    runner.invoke(app, ["init", "my-scope"])
    result = runner.invoke(app, ["prompt"])
    assert result.exit_code == 0
    assert "last_modified" not in result.output


# --- why command tests ---

def test_why_t4_match(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "src/*.py"])
    result = runner.invoke(app, ["why", "src/main.py"])
    assert result.exit_code == 0
    assert "READ-WRITE" in result.output
    assert "src/*.py" in result.output


def test_why_t3_match(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "--read", "docs/*.md"])
    result = runner.invoke(app, ["why", "docs/readme.md"])
    assert result.exit_code == 0
    assert "READ-ONLY" in result.output
    assert "docs/*.md" in result.output


def test_why_t2_match(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "--sig", "types/*.pyi"])
    result = runner.invoke(app, ["why", "types/core.pyi"])
    assert result.exit_code == 0
    assert "SIGNATURE" in result.output
    assert "types/*.pyi" in result.output


def test_why_blocked(in_tmp):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["add", "src/*.py"])
    result = runner.invoke(app, ["why", "other/file.txt"])
    assert result.exit_code == 1
    assert "BLOCKED" in result.output


def test_why_no_scope(in_tmp):
    result = runner.invoke(app, ["why", "any/file.py"])
    assert "No scope defined" in result.output
