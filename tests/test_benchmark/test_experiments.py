"""Campaign orchestration stays strict, reproducible, and scorer-independent."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mddatabench import experiments as ex


DATASET = Path("benchmarks/mddatabench")
TASK = "027_complex_1b6c"


def fake_checkout(tmp_path):
    """A minimal stand-in for an MDClaw checkout, which init now freezes."""
    root = tmp_path / "mdclaw"
    (root / "mdclaw").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "md-prepare").mkdir(parents=True, exist_ok=True)
    (root / "bin").mkdir(parents=True, exist_ok=True)
    (root / "mdclaw" / "__init__.py").write_text("VERSION = '0'\n")
    (root / "skills" / "md-prepare" / "SKILL.md").write_text("# md-prepare\n")
    (root / "bin" / "mdclaw").write_text("#!/bin/sh\nexit 0\n")
    (root / "bin" / "mdclaw").chmod(0o755)
    return root


def write_spec(tmp_path, cells, replicates=3):
    fake_checkout(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "experiment_id": "paper-test",
        "replicates": replicates,
        "tasks": [TASK],
        "sif": "/images/mdclaw.sif",
        "runtime_sif": "/images/runtime.sif",
        "mdclaw_cli": "/bin/true",
        "mdclaw_source": str(tmp_path / "mdclaw"),
        "cells": cells,
    }))
    return spec


def cell(condition="cli_skill_sif", harness="pi", model="rikyu/kimi-k3"):
    return {"condition": condition, "harness": harness, "model": model,
            "harness_version": "test", "thinking": "medium"}


def attempts(root):
    return sorted((root / "attempts").glob("**/manifest.json"))


def test_init_builds_three_isolated_replicates_per_cell(tmp_path):
    spec = write_spec(tmp_path, [cell(), cell("cli_sif"), cell("sif_only")])
    root = tmp_path / "experiment"
    result = ex.init_experiment(str(root), str(spec), str(DATASET))
    assert result["attempts"] == 9
    manifests = attempts(root)
    assert len(manifests) == 9
    for path in manifests:
        manifest = json.loads(path.read_text())
        assert manifest["environment"]["agent_timeout_seconds"] == 1200
        assert manifest["environment"]["md_time_limit"] == "00:20:00"
        workspace = Path(manifest["paths"]["workspace"])
        assert (workspace / "task_prompt.md").is_file()
        assert (workspace / "CAPABILITIES.md").is_file()
        agent_prompt = (workspace / "agent_prompt.md").read_text()
        assert "hard 1200 s" in agent_prompt
        assert "hard 00:20:00" in agent_prompt
        assert "do not relax the scientific requirements" in agent_prompt.lower()
        assert "Do not\nshorten the requested minimum production duration" in agent_prompt
        assert not list(workspace.rglob("task.json"))
        assert (workspace / ".mddatabench/bin/sbatch").stat().st_mode & 0o111
        assert str(Path(ex.__file__).resolve().parents[1]) not in (
            workspace / ".mddatabench/bin/sbatch").read_text()
        command = ex.run_attempt_agent(str(path.parent), dry_run=True)["command"]
        if manifest["condition"] == "cli_skill_sif":
            assert "--no-skills" not in command
            assert (workspace / ".agents/skills").is_symlink()
            if manifest["harness"] == "pi":
                assert "--skill" in command
        else:
            assert "--no-skills" in command
            assert not (workspace / ".agents/skills").exists()
        if manifest["condition"] == "sif_only":
            assert (workspace / "PORTABLE_SUBMISSION.md").is_file()
            assert not (workspace / ".mddatabench/bin/mdclaw").exists()
        else:
            wrapper = workspace / ".mddatabench/bin/mdclaw"
            assert wrapper.is_file()
            assert "CLAUDE_PLUGIN_ROOT=" in wrapper.read_text()


def test_sif_only_refuses_the_mdclaw_image_as_its_runtime(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"tasks": [TASK], "replicates": 3,
                                "sif": "/same.sif", "runtime_sif": "/same.sif",
                                "cells": [cell("sif_only")]}))
    with pytest.raises(ValueError, match="must differ"):
        ex.init_experiment(str(tmp_path / "experiment"), str(spec), str(DATASET))


def test_cli_conditions_require_current_mdclaw_source_overlay(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"tasks": [TASK], "replicates": 1,
                                "sif": "/old.sif", "mdclaw_cli": "/bin/true",
                                "cells": [cell()]}))
    with pytest.raises(ValueError, match="mdclaw_source"):
        ex.init_experiment(str(tmp_path / "experiment"), str(spec), str(DATASET))


@pytest.mark.parametrize(("harness", "expected", "forbidden"), [
    ("pi", "--no-skills", None),
    ("claude-code", "--safe-mode", "--bare"),
    ("codex", "--ignore-user-config", "--ask-for-approval"),
])
def test_no_skill_harness_commands_use_installed_isolation_flags(tmp_path, harness,
                                                                 expected, forbidden):
    spec = write_spec(tmp_path, [cell("cli_sif", harness, "test-model")], 1)
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    command = ex.run_attempt_agent(str(attempts(root)[0].parent), dry_run=True)["command"]
    assert expected in command
    if forbidden:
        assert forbidden not in command
    if harness == "codex":
        assert 'model_reasoning_effort="medium"' in command


@pytest.mark.parametrize(("harness", "flag"), [
    ("pi", "--skill"),
    ("claude-code", "--plugin-dir"),
])
def test_skill_condition_loads_the_current_project_skill_explicitly(tmp_path, harness,
                                                                    flag):
    spec = write_spec(tmp_path, [cell("cli_skill_sif", harness, "test-model")], 1)
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    attempt = attempts(root)[0].parent
    command = ex.run_attempt_agent(str(attempt), dry_run=True)["command"]
    assert flag in command
    # The skill comes from the campaign's frozen copy, never the live checkout.
    frozen = root / "frozen-source" / "mdclaw-0"
    assert any(value.startswith(str(frozen)) for value in command)
    assert not any(value.startswith(str(tmp_path / "mdclaw") + "/") for value in command)


def test_init_freezes_the_mdclaw_checkout_and_takes_write_access_away(tmp_path):
    # An agent reaches MDClaw through CLAUDE_PLUGIN_ROOT and PYTHONPATH. Left
    # pointing at the operator's checkout, an attempt could edit the package it
    # was being measured against and every later attempt inherited the edit.
    origin = fake_checkout(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "experiment_id": "freeze-test", "replicates": 1, "tasks": [TASK],
        "sif": "/images/mdclaw.sif",
        "mdclaw_cli": str(origin / "bin" / "mdclaw"),   # inside the checkout
        "mdclaw_source": str(origin), "cells": [cell()],
    }))
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))

    record = json.loads((root / "experiment.json").read_text())["frozen_sources"]
    assert len(record) == 1
    frozen = Path(record[0]["frozen"])
    assert record[0]["origin"] == str(origin)
    assert frozen.is_relative_to(root)

    manifest = json.loads(attempts(root)[0].read_text())
    assert manifest["environment"]["mdclaw_source"] == str(frozen)
    assert manifest["environment"]["mdclaw_cli"] == str(frozen / "bin" / "mdclaw")
    assert manifest["revisions"]["mdclaw_tree_sha256"] == record[0]["tree_sha256"]

    module = frozen / "mdclaw" / "__init__.py"
    assert module.read_text() == (origin / "mdclaw" / "__init__.py").read_text()
    assert (frozen / "bin" / "mdclaw").stat().st_mode & 0o111, "exec bits survive"

    with pytest.raises(PermissionError):
        module.write_text("VERSION = 'tampered'\n")
    with pytest.raises(PermissionError):
        (frozen / "mdclaw" / "added.py").write_text("x")

    # The origin is untouched, so the operator can keep working during a run.
    assert (origin / "mdclaw" / "__init__.py").read_text() == "VERSION = '0'\n"


def test_freeze_leaves_run_output_behind(tmp_path):
    # A checkout is not only source. MDClaw writes study workspaces under
    # `studies/` and run output under `runs/`, both inside the checkout, and
    # neither is importable: an attempt needs the package, `skills/` and
    # `bin/`. Measured 2026-08-27, a checkout holding 37 GB of umbrella
    # sampling was copied whole and then hashed file by file, which took the
    # 1 TB project quota from 81 GB free to 40 GB and paused the driver on its
    # disk floor before one attempt dispatched.
    origin = fake_checkout(tmp_path)
    (origin / "studies" / "t1r" / "jobs").mkdir(parents=True)
    (origin / "studies" / "t1r" / "jobs" / "prod.dcd").write_text("x" * 4096)
    (origin / "runs" / "scratch").mkdir(parents=True)
    (origin / "runs" / "scratch" / "traj.xtc").write_text("y" * 4096)

    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "experiment_id": "freeze-excludes", "replicates": 1, "tasks": [TASK],
        "sif": "/images/mdclaw.sif", "mdclaw_cli": "/bin/true",
        "mdclaw_source": str(origin), "cells": [cell()],
    }))
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))

    frozen = Path(json.loads(
        (root / "experiment.json").read_text())["frozen_sources"][0]["frozen"])
    assert not (frozen / "studies").exists()
    assert not (frozen / "runs").exists()

    # What an attempt imports still followed it in.
    assert (frozen / "mdclaw" / "__init__.py").is_file()
    assert (frozen / "skills" / "md-prepare" / "SKILL.md").is_file()
    assert (frozen / "bin" / "mdclaw").is_file()

    # The excluded trees are data, so they must not reach the digest either --
    # otherwise the hash changes whenever the operator runs an unrelated study.
    assert not any(part in {"studies", "runs"}
                   for path in frozen.rglob("*") for part in path.parts)

    # The origin keeps its output.
    assert (origin / "studies" / "t1r" / "jobs" / "prod.dcd").is_file()


def test_freeze_leaves_a_cli_outside_the_checkout_where_it_is(tmp_path):
    # Only bin/mdclaw living inside the checkout follows it into the freeze; a
    # CLI installed elsewhere is not ours to copy.
    spec = write_spec(tmp_path, [cell()], 1)          # mdclaw_cli is /bin/true
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    manifest = json.loads(attempts(root)[0].read_text())
    assert manifest["environment"]["mdclaw_cli"] == "/bin/true"
    assert manifest["environment"]["mdclaw_source"].startswith(str(root))


def test_partial_prep_or_md_score_is_binary_zero_and_tables_keep_partial_score(tmp_path):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()])), str(DATASET))
    dirs = [path.parent for path in attempts(root)]
    reports = [
        {"passed": 2, "total": 2, "checks": [
            {"check_id": "prep", "category": "prep", "weight": 1, "passed": True},
            {"check_id": "md", "category": "md", "weight": 1, "passed": True}],
         "diagnostics": {"submitted_backbone_connectivity": {
             "schema_version": 1,
             "source": "submitted_openmm_system_force_bearing_bonds",
             "topology_atoms": 2,
             "topology_residues": 2,
             "links": [{"kind": "peptide", "atom_indices": [0, 1],
                        "residue_indices": [0, 1]}],
         }}},
        {"passed": 1, "total": 2, "checks": [
            {"check_id": "prep_bad", "category": "prep", "weight": 1, "passed": False},
            {"check_id": "md", "category": "md", "weight": 1, "passed": True}]},
    ]
    for attempt, report in zip(dirs[:2], reports):
        score = attempt / "score.json"
        score.write_text(json.dumps(report))
        ex.finalize_attempt(str(attempt), str(score))
    ex.finalize_attempt(str(dirs[2]), failure_stage="md", failure_code="md_timeout")

    second = json.loads((dirs[1] / "result.json").read_text())
    assert second["attempt_score"] == 0
    assert second["check_score"] == 0.5
    assert second["failure_stage"] == "prep"
    evidence = json.loads(
        (dirs[0] / "evaluation" / "backbone_connectivity.json").read_text())
    first = json.loads((dirs[0] / "result.json").read_text())
    assert evidence["links"][0]["kind"] == "peptide"
    assert first["artifacts"]["backbone_connectivity"].endswith(
        "evaluation/backbone_connectivity.json")
    summary = ex.collect_experiment(str(root))
    assert summary["success"]
    overall = next(row for row in summary["summary"] if row["axis"] == "all")
    assert overall["success_rate"] == pytest.approx(1 / 3)
    assert overall["successes"] == 1
    assert 0 <= overall["success_rate_ci95_low"] < overall["success_rate"]
    assert overall["success_rate"] < overall["success_rate_ci95_high"] <= 1
    assert overall["mean_check_score"] == pytest.approx(0.5)
    assert overall["any_pass_at_k"] == 1.0
    assert overall["reliability_at_k"] == 0.0
    assert overall["k_min"] == overall["k_max"] == 3


def test_no_sbatch_is_sealed_as_zero(tmp_path):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()], 1)), str(DATASET))
    attempt = attempts(root)[0].parent
    result = ex.submit_attempt_scorer(str(attempt), str(tmp_path), "/image.sif")
    assert result["attempt_score"] == 0
    assert result["failure_code"] == "agent_no_submission"
    assert (attempt / "result.json").is_file()


def test_missing_harness_executable_is_recorded_for_zero_scoring(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()], 1)), str(DATASET))
    attempt = attempts(root)[0].parent
    monkeypatch.setattr(ex.subprocess, "run", lambda *args, **kwargs:
                        (_ for _ in ()).throw(FileNotFoundError("missing harness")))
    result = ex.run_attempt_agent(str(attempt), timeout_seconds=1)
    assert not result["success"]
    assert result["exit_reason"] == "launch_error"
    sealed = ex.submit_attempt_scorer(str(attempt), str(tmp_path), "/image.sif")
    assert sealed["attempt_score"] == 0


def test_agent_and_md_time_limits_are_enforced(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    spec_path = write_spec(tmp_path, [cell("sif_only")], 1)
    spec = json.loads(spec_path.read_text())
    spec.update({"agent_timeout_seconds": 900, "md_time_limit": "00:15:00"})
    spec_path.write_text(json.dumps(spec))
    ex.init_experiment(str(root), str(spec_path), str(DATASET))
    attempt = attempts(root)[0].parent
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=124)

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    result = ex.run_attempt_agent(str(attempt))
    assert result["exit_reason"] == "timeout"
    assert captured["argv"][:4] == ["/usr/bin/timeout", "--signal=TERM",
                                    "--kill-after=10s", "900s"]
    assert captured["argv"][4].endswith("pi")
    assert captured["env"]["MDDATABENCH_MD_TIME_LIMIT"] == "00:15:00"


def test_sif_only_does_not_inherit_user_path_or_pythonpath(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root),
                       str(write_spec(tmp_path, [cell("sif_only")], 1)), str(DATASET))
    attempt = attempts(root)[0].parent
    captured = {}
    monkeypatch.setenv("PATH", "/poison/user-bin:/usr/bin")
    monkeypatch.setenv("PYTHONPATH", "/poison/mdclaw-source")

    def fake_run(*args, **kwargs):
        captured.update(kwargs["env"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    ex.run_attempt_agent(str(attempt), timeout_seconds=1)
    assert "/poison" not in captured["PATH"]
    assert "PYTHONPATH" not in captured
    assert captured["PYTHONNOUSERSITE"] == "1"


def test_codex_no_skill_uses_empty_home_but_preserves_auth_home(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    spec = write_spec(tmp_path, [cell("cli_sif", "codex", "test-model")], 1)
    ex.init_experiment(str(root), str(spec), str(DATASET))
    attempt = attempts(root)[0].parent
    captured = {}
    monkeypatch.setenv("CODEX_HOME", "/secure/codex-auth")

    def fake_run(*args, **kwargs):
        captured.update(kwargs["env"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    ex.run_attempt_agent(str(attempt), timeout_seconds=1)
    assert captured["CODEX_HOME"] == "/secure/codex-auth"
    assert captured["HOME"].endswith("workspace/.mddatabench/home")


def test_standalone_sbatch_shim_overrides_agent_time_limit(tmp_path, monkeypatch,
                                                          capsys):
    from mddatabench import sbatch_shim

    event_log = tmp_path / "events.jsonl"
    captured = {}
    monkeypatch.setenv("MDDATABENCH_EVENT_LOG", str(event_log))
    monkeypatch.setenv("MDDATABENCH_MD_TIME_LIMIT", "01:00:00")

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="Submitted batch job 12345\n",
                               stderr="")

    monkeypatch.setattr(sbatch_shim.subprocess, "run", fake_run)
    assert sbatch_shim.main(["--time=99:00:00", "job.sbatch"]) == 0
    assert captured["argv"] == ["/usr/bin/sbatch", "--time=01:00:00", "job.sbatch"]
    assert json.loads(event_log.read_text())["job_id"] == "12345"
    assert "Submitted batch job 12345" in capsys.readouterr().out


def test_scorer_submission_uses_afterany_and_last_captured_job(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()], 1)), str(DATASET))
    attempt = attempts(root)[0].parent
    ex.record_sbatch(str(attempt), ["run.sbatch"], "Submitted batch job 12345\n", 0)

    def fake_run(argv, **kwargs):
        assert argv[:2] == ["sbatch", "--parsable"]
        return SimpleNamespace(returncode=0, stdout="67890\n", stderr="")

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    result = ex.submit_attempt_scorer(str(attempt), str(tmp_path), "/image.sif")
    assert result["md_job_id"] == "12345"
    assert result["scorer_job_id"] == "67890"
    script = Path(result["script"]).read_text()
    assert "#SBATCH --dependency=afterany:12345" in script
    assert "finalize_attempt" in script


def test_scorer_submit_failure_is_sealed_as_infra_zero(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()], 1)), str(DATASET))
    attempt = attempts(root)[0].parent
    ex.record_sbatch(str(attempt), ["run.sbatch"], "Submitted batch job 12345\n", 0)
    monkeypatch.setattr(ex.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout="", stderr="queue error"))
    result = ex.submit_attempt_scorer(str(attempt), str(tmp_path), "/image.sif")
    assert not result["success"]
    assert result["attempt_score"] == 0
    assert result["failure_stage"] == "infra"
    assert result["failure_code"] == "scorer_submit_failed"


def test_run_experiment_resumes_scorer_handoff_without_rerunning_agent(tmp_path,
                                                                      monkeypatch):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()], 1)), str(DATASET))
    attempt = attempts(root)[0].parent
    ex._append_event(attempt, "agent_end", returncode=0)
    ex.record_sbatch(str(attempt), ["run.sbatch"], "Submitted batch job 12345\n", 0)
    monkeypatch.setattr(ex, "run_attempt_agent", lambda *args, **kwargs:
                        pytest.fail("completed agent must not be rerun"))
    monkeypatch.setattr(ex, "submit_attempt_scorer", lambda *args, **kwargs:
                        {"success": True, "scorer_job_id": "67890"})
    result = ex.run_experiment(str(root), str(tmp_path), "/image.sif")
    assert result["launched"] == 1
    assert result["attempts"][0]["agent"] is None


def test_collect_seals_terminal_scorer_job_that_wrote_no_result(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()], 1)), str(DATASET))
    attempt = attempts(root)[0].parent
    ex._append_event(attempt, "scorer_submitted", returncode=0,
                     scorer_job_id="67890", md_job_id="12345")
    monkeypatch.setattr(ex, "_slurm_job_state", lambda job_id: "OUT_OF_MEMORY")
    summary = ex.collect_experiment(str(root))
    assert summary["success"]
    result = json.loads((attempt / "result.json").read_text())
    assert result["attempt_score"] == 0
    assert result["failure_stage"] == "infra"
    assert result["failure_code"] == "scorer_job_out_of_memory"


def test_collect_leaves_running_scorer_incomplete(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()], 1)), str(DATASET))
    attempt = attempts(root)[0].parent
    ex._append_event(attempt, "scorer_submitted", returncode=0,
                     scorer_job_id="67890", md_job_id="12345")
    monkeypatch.setattr(ex, "_slurm_job_state", lambda job_id: "RUNNING")
    summary = ex.collect_experiment(str(root))
    assert not summary["success"]
    assert summary["incomplete_attempts"]


def test_slurm_accounting_is_converted_to_queue_runtime_and_gpu_seconds(tmp_path):
    path = tmp_path / "sacct.txt"
    path.write_text("1|COMPLETED|2026-08-24T10:00:00|2026-08-24T10:02:00|"
                    "2026-08-24T10:12:00|600|cpu=8,gres/gpu=1,mem=64G\n")
    assert ex._slurm_metrics(path) == {
        "md_queue_seconds": 120.0,
        "md_run_seconds": 600.0,
        "gpu_seconds": 600.0,
        "slurm_metrics_provenance": "sacct",
    }


def test_pi_inventory_records_models_but_not_credentials(tmp_path, monkeypatch):
    config = tmp_path / "pi"
    config.mkdir()
    (config / "settings.json").write_text('{"defaultModel":"kimi-k3"}')
    (config / "models.json").write_text(json.dumps({"providers": {"rikyu": {
        "apiKey": "secret", "models": [{"id": "kimi-k3", "name": "Kimi",
                                           "reasoning": True, "cost": {"input": 0}}]
    }}}))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(config))
    inventory = ex.model_inventory()
    assert inventory["models"][0]["id"] == "rikyu/kimi-k3"
    assert "secret" not in json.dumps(inventory)


def test_portable_missing_submission_becomes_a_full_zero():
    from mddatabench.portable import score_portable

    task = json.loads((DATASET / "tasks" / TASK / "task.json").read_text())
    report = score_portable(Path("/does/not/exist"), Path("/unused"), task)
    assert report["passed"] == 0
    assert report["total"] > 0
    assert report["scores"]["prep"] == 0
    assert report["scores"]["md"] == 0
