"""Campaign orchestration stays strict, reproducible, and scorer-independent."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mddatabench import experiments as ex


DATASET = Path("benchmarks/mddatabench")
TASK = "027_complex_1b6c"


FAKE_RUNTIME = {"python": "3.12.14",
                "packages": {"openmm": "8.5.1", "pdbfixer": "1.11", "mdtraj": "1.10.3"},
                "executables": ["tleap", "pdb4amber", "packmol"]}


@pytest.fixture(autouse=True)
def fake_runtime_probe(monkeypatch):
    """sif_only cells probe their runtime image at init; tests use a stub image."""
    def probe(runtime_sif, sha256=None):
        return {"runtime_sif": str(runtime_sif), "sha256": sha256 or "runtimedigest",
                **FAKE_RUNTIME}
    monkeypatch.setattr(ex, "_probe_runtime", probe)


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
        assert "under `$TMPDIR`" in agent_prompt
        assert "fixed\n`/tmp/<name>`" in agent_prompt
        assert not list(workspace.rglob("task.json"))
        assert (workspace / ".mddatabench/bin/sbatch").stat().st_mode & 0o111
        assert str(Path(ex.__file__).resolve().parents[1]) + "/" not in (
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
            assert manifest["environment"]["source_overlay_required"] is False
            assert not (workspace / ".mdclaw_cluster.json").exists()
            assert (workspace / "PORTABLE_SUBMISSION.md").is_file()
            assert not (workspace / ".mddatabench/bin/mdclaw").exists()
        else:
            assert manifest["environment"]["source_overlay_required"] is True
            config = json.loads((workspace / ".mdclaw_cluster.json").read_text())
            assert config["container"] == {"image": manifest["environment"]["sif"],
                                            "source_mode": "overlay", "extra_flags": "--nv"}
            assert "MDDATABENCH_MANIFEST=" in (workspace / ".mddatabench/bin/sbatch").read_text()
            assert (workspace / ".mddatabench/bin/source_overlay.py").is_file()
            wrapper = workspace / ".mddatabench/bin/mdclaw"
            assert wrapper.is_file()
            assert "CLAUDE_PLUGIN_ROOT=" in wrapper.read_text()


def test_init_refuses_an_experiment_inside_the_mddatabench_checkout():
    source_tree = Path(ex.__file__).resolve().parents[1]
    experiment = source_tree / "tests" / "__experiment_must_be_external__"

    with pytest.raises(ValueError, match="outside the MDDataBench source checkout"):
        ex.init_experiment(str(experiment), "unused-spec.json", str(DATASET))

    assert not experiment.exists()


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


def test_pi_user_skill_condition_keeps_normal_user_wide_discovery(tmp_path):
    user_cell = {**cell(), "skill_source": "user"}
    spec = write_spec(tmp_path, [user_cell], 1)
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    manifest_path = attempts(root)[0]
    manifest = json.loads(manifest_path.read_text())
    command = ex.run_attempt_agent(str(manifest_path.parent), dry_run=True)["command"]

    assert manifest["skill_source"] == "user"
    assert "--skill" not in command
    assert "--no-skills" not in command
    assert not (Path(manifest["paths"]["workspace"]) / ".agents/skills").exists()


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
    (origin / "benchmark_runs" / "old-attempt").mkdir(parents=True)
    (origin / "benchmark_runs" / "old-attempt" / "traj.xtc").write_text("z" * 4096)
    (origin / "outputs" / "old-attempt").mkdir(parents=True)
    (origin / "outputs" / "old-attempt" / "traj.xtc").write_text("o" * 4096)
    (origin / "mdclaw.sif").write_text("image dependency, not source")
    (origin / "mdclaw.sif.bak").write_text("old image dependency, not source")

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
    assert not (frozen / "benchmark_runs").exists()
    assert not (frozen / "outputs").exists()
    assert not (frozen / "mdclaw.sif").exists()
    assert not (frozen / "mdclaw.sif.bak").exists()

    # What an attempt imports still followed it in.
    assert (frozen / "mdclaw" / "__init__.py").is_file()
    assert (frozen / "skills" / "md-prepare" / "SKILL.md").is_file()
    assert (frozen / "bin" / "mdclaw").is_file()

    # The excluded trees are data, so they must not reach the digest either --
    # otherwise the hash changes whenever the operator runs an unrelated study.
    assert not any(part in {"studies", "runs", "outputs", "benchmark_runs"}
                   for path in frozen.rglob("*") for part in path.parts)

    # The origin keeps its output.
    assert (origin / "studies" / "t1r" / "jobs" / "prod.dcd").is_file()
    assert (origin / "benchmark_runs" / "old-attempt" / "traj.xtc").is_file()
    assert (origin / "outputs" / "old-attempt" / "traj.xtc").is_file()
    assert (origin / "mdclaw.sif").is_file()
    assert (origin / "mdclaw.sif.bak").is_file()


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
    assert second["failure_stage"] == "unknown"  # no execution evidence in this fixture
    assert second["scoring_failures"][0]["check_id"] == "prep_bad"
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


def test_each_attempt_launch_gets_its_own_existing_tmpdir(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()], 2)), str(DATASET))
    launched = []

    def fake_run(*args, **kwargs):
        launched.append(kwargs["env"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    for manifest in attempts(root):
        ex.run_attempt_agent(str(manifest.parent), timeout_seconds=1)

    temp_dirs = []
    for environment in launched:
        assert environment["TMP"] == environment["TEMP"] == environment["TMPDIR"]
        temporary = Path(environment["TMPDIR"])
        assert temporary.is_dir()
        assert temporary.parts[-3:] == ("workspace", ".mddatabench", "tmp")
        temp_dirs.append(temporary)
    assert len(set(temp_dirs)) == 2


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


def test_standalone_sbatch_shim_pins_operator_partition_and_node(monkeypatch):
    from mddatabench import sbatch_shim

    captured = {}
    monkeypatch.setenv("MDDATABENCH_MD_PARTITION", "all")
    monkeypatch.setenv("MDDATABENCH_MD_NODELIST", "n4")

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="Submitted batch job 12345\n",
                               stderr="")

    monkeypatch.setattr(sbatch_shim.subprocess, "run", fake_run)
    arguments = ["--partition", "gpu", "--nodelist=other", "--gpus", "1", "job.sbatch"]
    assert sbatch_shim.main(arguments) == 0
    assert captured["argv"] == [
        "/usr/bin/sbatch", "--time=00:20:00", "--partition=all", "--nodelist=n4",
        "--gpus", "1", "job.sbatch",
    ]


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


def test_scorer_accounts_for_the_complete_md_job_chain(tmp_path, monkeypatch):
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(write_spec(tmp_path, [cell()], 1)), str(DATASET))
    attempt = attempts(root)[0].parent
    for job_id in ("111", "222", "333"):
        ex.record_sbatch(str(attempt), [f"{job_id}.sbatch"],
                         f"Submitted batch job {job_id}\n", 0)
    ex._append_event(attempt, "sbatch", job_id="999", returncode=1)

    monkeypatch.setattr(
        ex.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout="444\n", stderr=""),
    )
    submitted = ex.submit_attempt_scorer(str(attempt), str(tmp_path), "/image.sif")
    script = Path(submitted["script"]).read_text()
    assert "#SBATCH --dependency=afterany:333" in script
    assert "sacct -X -n -P -j 111,222,333 --format=" in script
    assert "999" not in script

    (attempt / "md_sacct.txt").write_text(
        "111|COMPLETED|2026-08-24T10:00:00|2026-08-24T10:01:00|"
        "2026-08-24T10:03:00|120|cpu=8,gres/gpu=1,mem=64G\n"
        "222|FAILED|2026-08-24T10:00:00|2026-08-24T10:02:00|"
        "2026-08-24T10:02:30|30|cpu=8,gres/gpu=1,mem=64G\n"
        "333|CANCELLED by 42|2026-08-24T10:00:00|2026-08-24T10:03:00|"
        "2026-08-24T10:03:10|10|cpu=8,gres/gpu=1,mem=64G\n"
    )
    score = attempt / "score.json"
    score.write_text(json.dumps({"passed": 1, "total": 1, "checks": []}))
    result = ex.finalize_attempt(str(attempt), str(score))
    metrics = result["metrics"]
    assert [job["job_id"] for job in metrics["md_jobs"]] == ["111", "222", "333"]
    assert [job["state"] for job in metrics["md_jobs"]] == [
        "COMPLETED", "FAILED", "CANCELLED",
    ]
    assert metrics["md_queue_seconds"] == 360.0
    assert metrics["md_run_seconds"] == metrics["gpu_seconds"] == 160.0


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
        "gpu_seconds_known": 600.0,
        "gpu_observed_count": 1,
        "gpu_expected_count": 1,
        "gpu_coverage": 1.0,
        "md_jobs": [{
            "job_id": "1",
            "state": "COMPLETED",
            "submitted_at": "2026-08-24T10:00:00",
            "started_at": "2026-08-24T10:02:00",
            "ended_at": "2026-08-24T10:12:00",
            "queue_seconds": 120.0,
            "run_seconds": 600.0,
            "gpus": 1,
            "gpu_seconds": 600.0,
        }],
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


def test_lab_deepseek_example_uses_the_configured_non_reasoning_model():
    spec = json.loads(Path("examples/experiment-lab-deepseek.json").read_text())
    assert spec["cells"] == [{
        "condition": "cli_skill_sif",
        "harness": "pi",
        "model": "deepseek-cloudflare/deepseek-v4-flash",
        "skill_source": "user",
    }]
    assert spec["mdclaw_cli"] == "/home/yasu/tmp/mdclaw/mdclaw/bin/mdclaw"
    assert spec["mdclaw_source"] == "/home/yasu/tmp/mdclaw/mdclaw"
    assert spec["sif"] == "/home/yasu/tmp/mdclaw/mdclaw/mdclaw.sif"


def test_portable_missing_submission_becomes_a_full_zero():
    from mddatabench.portable import score_portable

    task = json.loads((DATASET / "tasks" / TASK / "task.json").read_text())
    report = score_portable(Path("/does/not/exist"), Path("/unused"), task)
    assert report["passed"] == 0
    assert report["total"] > 0
    assert report["scores"]["prep"] == 0
    assert report["scores"]["md"] == 0


# ---- image mode: skills + SIF, no MDClaw source ------------------------------

def image_spec(tmp_path, cells, **extra):
    sif = tmp_path / "mdclaw.sif"
    sif.write_text("stub image")
    spec = tmp_path / "image-spec.json"
    spec.write_text(json.dumps({
        "experiment_id": "image-test", "replicates": 1, "tasks": [TASK],
        "sif": str(sif), "source_mode": "image",
        "container_binds": ["/usr/bin/sbatch", "/etc/slurm", "/host/passwd:/etc/passwd"],
        "cells": cells, **extra}))
    return spec, sif


def fake_probe(monkeypatch):
    seen = []

    def probe(sif, sha256=None):
        seen.append(str(sif))
        return {"sif": str(sif), "sha256": sha256 or "imagedigest",
                "mdclaw_module": "/opt/mdclaw/lib/python3.12/site-packages/mdclaw/__init__.py",
                "mdclaw_version": "0.6.8"}

    monkeypatch.setattr(ex, "_probe_image", probe)
    return seen


def test_image_mode_needs_only_skills_and_the_sif(tmp_path, monkeypatch):
    probed = fake_probe(monkeypatch)
    user_cell = {**cell(), "skill_source": "user"}
    spec, sif = image_spec(tmp_path, [user_cell, cell("cli_sif")])
    root = tmp_path / "experiment"
    result = ex.init_experiment(str(root), str(spec), str(DATASET))

    assert result["attempts"] == 2
    assert probed == [str(sif)]
    assert not (root / "frozen-source").exists()
    experiment = json.loads((root / "experiment.json").read_text())
    assert experiment["frozen_sources"] == []
    assert experiment["images"][0]["mdclaw_version"] == "0.6.8"
    for path in attempts(root):
        manifest = json.loads(path.read_text())
        environment = manifest["environment"]
        workspace = Path(manifest["paths"]["workspace"])
        assert environment["source_mode"] == "image"
        assert environment["mdclaw_source"] is None
        assert environment["mdclaw_cli"] is None
        assert environment["source_overlay_required"] is False
        assert environment["image_mdclaw_module"].endswith("site-packages/mdclaw/__init__.py")
        assert environment["container_binds"] == ["/usr/bin/sbatch", "/etc/slurm",
                                                  "/host/passwd:/etc/passwd"]
        assert manifest["hashes"]["sif"] == "imagedigest"
        assert manifest["revisions"]["mdclaw_image_sha256"] == "imagedigest"
        assert manifest["revisions"]["mdclaw_tree_sha256"] is None
        assert "mdclaw_cli" not in manifest["exposed"]
        # No wrapper, no checkout: the agent is told to exec the image itself.
        assert not (workspace / ".mddatabench/bin/mdclaw").exists()
        capabilities = (workspace / "CAPABILITIES.md").read_text()
        assert f"singularity exec --env PYTHONPATH= --env PYTHONHOME= {sif} mdclaw" in capabilities
        assert "source overlay" in capabilities and "No MDClaw checkout" in capabilities
        # The no-skill cell must not inherit sif_only's "no CLI" lines.
        assert "not available" not in capabilities and "Runtime SIF" not in capabilities
        config = json.loads((workspace / ".mdclaw_cluster.json").read_text())
        assert config["container"]["source_mode"] == "image"
        launcher = (workspace / ".mddatabench/bin/sbatch").read_text()
        assert "command -v python3" in launcher and "MDDATABENCH_MANIFEST=" in launcher

        dry = ex.run_attempt_agent(str(path.parent), dry_run=True)
        binds = dry["environment"]["APPTAINER_BIND"].split(",")
        assert binds[0] == str(path.parent)
        assert binds[1:] == environment["container_binds"]
        assert dry["environment"]["SINGULARITY_BIND"] == dry["environment"]["APPTAINER_BIND"]
        assert dry["environment"]["APPTAINERENV_MDCLAW_SLURM_PATH"] == dry["environment"]["PATH"]
        assert dry["environment"]["PATH"].startswith(str(workspace / ".mddatabench/bin"))
        assert "MDCLAW_SOURCE" not in dry["environment"]
        assert "CLAUDE_PLUGIN_ROOT" not in dry["environment"]
        if manifest["condition"] == "cli_skill_sif":
            assert "--skill" not in dry["command"] and "--no-skills" not in dry["command"]
        else:
            assert "--no-skills" in dry["command"]


def test_image_mode_can_load_a_named_skills_directory(tmp_path, monkeypatch):
    fake_probe(monkeypatch)
    skills = tmp_path / "package" / "skills"
    (skills / "md-prepare").mkdir(parents=True)
    (skills / "md-prepare" / "SKILL.md").write_text("# md-prepare\n")
    spec, _ = image_spec(tmp_path, [cell()], skills_dir=str(skills))
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    path = attempts(root)[0]
    workspace = Path(json.loads(path.read_text())["paths"]["workspace"])
    assert (workspace / ".agents/skills").resolve() == skills.resolve()
    command = ex.run_attempt_agent(str(path.parent), dry_run=True)["command"]
    assert "--skill" in command and str(skills) in command
    assert f"MDClaw skills: {skills}" in (workspace / "CAPABILITIES.md").read_text()


@pytest.mark.parametrize(("fault", "message"), [
    ({"cells": [{**cell(), "mdclaw_source": "/live/checkout"}]}, "remove mdclaw_source"),
    ({"cells": [{**cell(), "mdclaw_cli": "/live/bin/mdclaw"}]}, "remove mdclaw_source"),
    ({"cells": [cell()]}, "skill_source=user"),
    ({"cells": [cell()], "source_mode": "bind"}, "source_mode must be"),
])
def test_image_mode_rejects_source_fields_and_unlocatable_skills(tmp_path, monkeypatch,
                                                                fault, message):
    fake_probe(monkeypatch)
    spec, _ = image_spec(tmp_path, fault.pop("cells"), **fault)
    with pytest.raises(ValueError, match=message):
        ex.init_experiment(str(tmp_path / "experiment"), str(spec), str(DATASET))


def test_image_mode_discovers_host_binds_when_the_spec_names_none(tmp_path, monkeypatch):
    fake_probe(monkeypatch)
    monkeypatch.setattr(ex, "discover_slurm_binds",
                        lambda out_dir: [f"{out_dir}/passwd:/etc/passwd", "/usr/bin/sbatch"])
    sif = tmp_path / "mdclaw.sif"
    sif.write_text("stub image")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"tasks": [TASK], "replicates": 1, "sif": str(sif),
                                "source_mode": "image",
                                "cells": [{**cell(), "skill_source": "user"}]}))
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    experiment = json.loads((root / "experiment.json").read_text())
    assert experiment["container_binds"] == [f"{root}/host-binds/passwd:/etc/passwd",
                                             "/usr/bin/sbatch"]


def test_image_mode_audits_the_transcript_for_source_overlays(tmp_path, monkeypatch):
    fake_probe(monkeypatch)
    spec, _ = image_spec(tmp_path, [{**cell(), "skill_source": "user"}])
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    attempt = attempts(root)[0].parent

    def fake_run(*args, **kwargs):
        # pi transcript shapes: the agent's own bash call is audited, the tool
        # result echoing a skill page that mentions bin/mdclaw is not.
        call = {"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "toolCall", "id": "bash:0", "name": "bash", "arguments": {
                "command": "export PYTHONPATH=/home/me/mdclaw; /home/me/mdclaw/bin/mdclaw --list"}}]}}
        repeated = {**call, "type": "message_start"}   # pi streams the same call thrice
        bare = {"type": "message_end", "message": {"role": "assistant", "content": [
            {"type": "toolCall", "id": "bash:1", "name": "bash", "arguments": {
                "command": "which mdclaw; mdclaw --version; singularity exec x.sif mdclaw --list"}}]}}
        result = {"type": "message_end", "message": {"role": "toolResult", "content": [
            {"type": "text", "text": "A checkout deployment may use its bin/mdclaw; "
                                     "PYTHONPATH=/frozen --bind /src/mdclaw"}]}}
        for row in (repeated, call, bare, result):
            kwargs["stdout"].write(json.dumps(row) + "\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    ex.run_attempt_agent(str(attempt), timeout_seconds=1)
    end = [json.loads(line) for line in (attempt / "events.jsonl").read_text().splitlines()
           if '"agent_end"' in line][-1]
    assert end["source_audit"] == {"launcher_mentions": 1, "pythonpath_mentions": 1,
                                   "source_bind_mentions": 0, "bare_cli_mentions": 1}


def test_image_mode_records_reachable_host_launchers(tmp_path, monkeypatch):
    fake_probe(monkeypatch)
    spec, _ = image_spec(tmp_path, [{**cell(), "skill_source": "user"}])
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    attempt = attempts(root)[0].parent
    home = tmp_path / "home"
    launcher = home / ".pi" / "agent" / "bin" / "mdclaw"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexec singularity exec old.sif mdclaw \"$@\"\n")
    launcher.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(ex.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0))
    ex.run_attempt_agent(str(attempt), timeout_seconds=1)
    events = [json.loads(line) for line in (attempt / "events.jsonl").read_text().splitlines()]
    preflight = [row for row in events if row["event"] == "image_mode_preflight"]
    # The test interpreter's own PATH may carry an mdclaw (it does inside the
    # SIF); the pi launcher must be reported regardless.
    assert preflight and str(launcher) in preflight[0]["host_launchers"]


def test_overlay_attempts_record_no_image_audit(tmp_path, monkeypatch):
    spec = write_spec(tmp_path, [cell("cli_sif")], 1)
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    attempt = attempts(root)[0].parent
    monkeypatch.setattr(ex.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=0))
    ex.run_attempt_agent(str(attempt), timeout_seconds=1)
    end = [json.loads(line) for line in (attempt / "events.jsonl").read_text().splitlines()
           if '"agent_end"' in line][-1]
    assert end["source_audit"] is None
    manifest = json.loads(attempts(root)[0].read_text())
    assert manifest["environment"]["source_mode"] == "overlay"


def test_shim_hands_the_worker_a_host_environment_from_inside_a_sif(monkeypatch):
    from mddatabench import sbatch_shim

    inside = {"APPTAINER_CONTAINER": "/images/mdclaw.sif", "SINGULARITY_NAME": "mdclaw.sif",
              "APPTAINERENV_X": "1", "LD_PRELOAD": "/opt/mdclaw/lib/libmdclaw_fusefix.so",
              "LD_LIBRARY_PATH": "/usr/local/cuda/lib64", "PYTHONPATH": "",
              "PATH": "/opt/mdclaw/bin:/usr/bin",
              "MDCLAW_SLURM_PATH": "/work/.mddatabench/bin:/shared/apptainer/bin:/usr/bin",
              "SBATCH_ACCOUNT": "project", "HOME": "/home/me"}
    worker = sbatch_shim._worker_environment(inside)
    assert worker == {"PATH": "/work/.mddatabench/bin:/shared/apptainer/bin:/usr/bin",
                      "MDCLAW_SLURM_PATH": inside["MDCLAW_SLURM_PATH"],
                      "SBATCH_ACCOUNT": "project", "HOME": "/home/me"}
    outside = {"PATH": "/usr/bin", "LD_PRELOAD": "/host/lib.so", "SINGULARITY_BIND": "/a:/a"}
    assert sbatch_shim._worker_environment(outside) == outside


# ---- sif_only runtime inventory ----------------------------------------------

def test_sif_only_gets_a_generated_runtime_inventory(tmp_path):
    spec = write_spec(tmp_path, [cell("sif_only")], 1)
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    experiment = json.loads((root / "experiment.json").read_text())
    assert experiment["runtime_images"][0]["packages"]["openmm"] == "8.5.1"
    manifest_path = attempts(root)[0]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["environment"]["runtime_inventory"] == FAKE_RUNTIME
    assert manifest["hashes"]["runtime_sif"] == "runtimedigest"
    capabilities = (Path(manifest["paths"]["workspace"]) / "CAPABILITIES.md").read_text()
    assert "Runtime SIF: /images/runtime.sif (sha256 runtimedigest)" in capabilities
    assert "openmm 8.5.1, pdbfixer 1.11, mdtraj 1.10.3" in capabilities
    assert "tleap, pdb4amber, packmol" in capabilities
    assert "not as a recommendation" in capabilities
    assert "singularity exec --env PYTHONPATH= --env PYTHONHOME= /images/runtime.sif python" in capabilities
    assert "MDClaw CLI and MDClaw skills are not available." in capabilities
    # Never leaks into the CLI conditions.
    assert "mdclaw" not in capabilities.split("MDClaw CLI and MDClaw skills")[0].lower()


def test_runtime_inventory_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "_probe_runtime",
                        lambda *args, **kwargs: pytest.fail("probe must not run"))
    fake_checkout(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"tasks": [TASK], "replicates": 1, "runtime_inventory": False,
                                "sif": "/images/mdclaw.sif", "runtime_sif": "/images/runtime.sif",
                                "cells": [cell("sif_only")]}))
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    manifest = json.loads(attempts(root)[0].read_text())
    assert manifest["environment"]["runtime_inventory"] is None
    capabilities = (Path(manifest["paths"]["workspace"]) / "CAPABILITIES.md").read_text()
    assert "Runtime SIF: /images/runtime.sif\n" in capabilities
    assert "probed" not in capabilities


@pytest.mark.parametrize("present", [False, True])
def test_runtime_probe_refuses_an_image_that_carries_mdclaw(tmp_path, monkeypatch, present):
    monkeypatch.undo()   # use the real _probe_runtime with a fake container runtime
    runtime_sif = tmp_path / "runtime.sif"
    runtime_sif.write_text("stub")
    monkeypatch.setattr(ex.shutil, "which", lambda name: "/usr/bin/singularity")
    payload = json.dumps({"python": "3.12.1", "packages": {"openmm": "8.5.1"},
                          "executables": ["tleap"], "mdclaw_present": present})
    monkeypatch.setattr(ex.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="noise\n" + payload + "\n", stderr=""))
    if present:
        with pytest.raises(ValueError, match="must not contain MDClaw"):
            ex._probe_runtime(runtime_sif, "abc")
    else:
        record = ex._probe_runtime(runtime_sif, "abc")
        assert record == {"runtime_sif": str(runtime_sif), "sha256": "abc", "python": "3.12.1",
                          "packages": {"openmm": "8.5.1"}, "executables": ["tleap"]}


# ---- transcript metrics at sealing and collection ------------------------------

def test_seal_records_tokens_error_codes_and_recovery_and_collect_tabulates_them(tmp_path):
    from tests.test_benchmark.test_transcript import write_pi_transcript

    spec = write_spec(tmp_path, [cell("cli_sif")], 2)
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    dirs = [path.parent for path in attempts(root)]
    write_pi_transcript(dirs[0] / "agent.stdout.jsonl")
    write_pi_transcript(dirs[1] / "agent.stdout.jsonl", timeout=True)
    for attempt, reason in zip(dirs, ("completed", "timeout")):
        ex._append_event(attempt, "agent_end", exit_reason=reason, wall_seconds=42.0,
                         usage={"provenance": "unavailable"})
    score = dirs[0] / "score.json"
    score.write_text(json.dumps({"passed": 1, "total": 1, "checks": [
        {"check_id": "md", "category": "md", "weight": 1, "passed": True}]}))
    ex.finalize_attempt(str(dirs[0]), str(score))
    ex.finalize_attempt(str(dirs[1]), failure_stage="agent", failure_code="agent_timeout")

    first = json.loads((dirs[0] / "result.json").read_text())
    assert first["schema_version"] == 3
    usage = first["metrics"]["token_usage"]
    assert usage["prompt_total"] == 4250 and usage["cache_read"] == 4000 and usage["calls"] == 6
    assert first["metrics"]["skill_reads"]["reads"] == 1
    assert first["execution_diagnostics"]["mdclaw_error_codes"] == {"unknown_forcefield": 1}
    assert first["execution_diagnostics"]["agent_exit_reason"] == "completed"
    assert first["recovery"]["counts"]["recovered"] == 1
    assert first["metrics"]["phases"]["prep"]["calls"] == 2
    assert Path(first["artifacts"]["timeline"]).is_file()
    second = json.loads((dirs[1] / "result.json").read_text())
    assert second["recovery"]["episodes"][0]["outcome"] == "recovered"   # prep recovered before the timeout

    summary = ex.collect_experiment(str(root))
    overall = next(row for row in summary["summary"] if row["axis"] == "all")
    # The timed-out transcript lacks the final message (10 + 1000 prompt, 60 output).
    assert overall["mean_prompt_total"] == pytest.approx((4250 + 3240) / 2)
    assert overall["cache_hit_ratio"] == pytest.approx((4000 + 3000) / (4250 + 3240))
    assert overall["recovery_episodes"] == 2 and overall["recovery_rate"] == 1.0
    assert overall["failure_free_rate"] == 0.0
    assert overall["tokens_per_success"] == pytest.approx(4250 + 3240 + 210 + 150)
    recovery_rows = summary["recovery"]
    assert recovery_rows[0]["stage"] == "prep" and recovery_rows[0]["episodes"] == 2
    assert recovery_rows[0]["diagnostic_tool_share"] == 1.0
    assert summary["error_codes"] == [{"condition": "cli_sif", "harness": "pi", "model": "rikyu/kimi-k3",
                                       "code": "unknown_forcefield", "count": 2}]
    out = root / "summary"
    assert (out / "recovery.csv").is_file() and (out / "error_codes.csv").is_file()
    digest = (out / "failure_digest" / f"{ex._slug(second['attempt_id'])}.md").read_text()
    assert "agent_timeout" in digest and "unknown_forcefield" in digest and "Last tool calls" in digest
    assert not (out / "failure_digest" / f"{ex._slug(first['attempt_id'])}.md").exists()


def test_collect_derives_transcript_metrics_for_older_seals_without_rewriting_them(tmp_path):
    from tests.test_benchmark.test_transcript import write_pi_transcript

    spec = write_spec(tmp_path, [cell("cli_sif")], 1)
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    attempt = attempts(root)[0].parent
    write_pi_transcript(attempt / "agent.stdout.jsonl")
    ex._append_event(attempt, "agent_end", exit_reason="completed", wall_seconds=1.0, usage={})
    ex.finalize_attempt(str(attempt), failure_stage="agent", failure_code="agent_no_submission")
    result = json.loads((attempt / "result.json").read_text())
    legacy = {**result, "schema_version": 2,
              "metrics": {**result["metrics"], "token_usage": {"provenance": "unavailable"}}}
    legacy.pop("recovery")
    (attempt / "result.json").write_text(json.dumps(legacy))
    summary = ex.collect_experiment(str(root))
    row = json.loads((root / "summary" / "attempts.jsonl").read_text().splitlines()[0])
    assert row["metrics"]["token_usage"]["prompt_total"] == 4250
    assert row["recovery"]["provenance"] == "collect_time"
    assert json.loads((attempt / "result.json").read_text())["schema_version"] == 2
    assert summary["summary"][0]["recovery_episodes"] == 1


def test_shim_recognises_parsable_job_ids_and_keeps_sbatch_output(tmp_path, monkeypatch):
    from mddatabench import sbatch_shim

    assert sbatch_shim.job_id_from_stdout("Submitted batch job 92488\n") == "92488"
    assert sbatch_shim.job_id_from_stdout("92488;rikyu\n") == "92488"
    assert sbatch_shim.job_id_from_stdout("92488\n") == "92488"
    assert sbatch_shim.job_id_from_stdout("sbatch: error: gres\n") is None
    event_log = tmp_path / "events.jsonl"
    monkeypatch.setenv("MDDATABENCH_EVENT_LOG", str(event_log))
    monkeypatch.setattr(sbatch_shim.subprocess, "run", lambda argv, **kwargs: SimpleNamespace(
        returncode=1, stdout="", stderr="sbatch: error: Invalid generic resource (gres) specification\n"))
    assert sbatch_shim.main(["--parsable", "job.sh"]) == 1
    row = json.loads(event_log.read_text())
    assert row["job_id"] is None and "gres" in row["stderr"]


def test_sif_only_failed_checks_are_an_evaluation_failure():
    from mddatabench.attempt_diagnostics import diagnose

    report = {"total": 20, "passed": 0, "checks": [
        {"check_id": "monomer_count_matches_reference", "weight": 1, "passed": False}]}
    diagnosis = diagnose("/nonexistent/submission", report, False, portable=True)
    assert diagnosis["failure_stage"] == "evaluation"
    assert diagnosis["failure_code"] == "checks_failed"
    assert diagnosis["execution_diagnostics"]["status"] == "completed"
    # A DAG condition with no nodes stays "unknown": the report alone is not execution evidence.
    assert diagnose("/nonexistent/job", report, False)["failure_stage"] == "unknown"
    failed_job = [{"job_id": "1", "job_name": "stage1", "state": "FAILED"}]
    scheduler = diagnose("/nonexistent/submission", report, False, failed_job, portable=True)
    assert (scheduler["failure_stage"], scheduler["failure_code"]) == ("execution", "scheduler_failure_observed")


def test_slurm_notes_reach_every_condition_and_are_recorded(tmp_path):
    fake_checkout(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "tasks": [TASK], "replicates": 1, "sif": "/images/mdclaw.sif",
        "runtime_sif": "/images/runtime.sif", "mdclaw_cli": "/bin/true",
        "mdclaw_source": str(tmp_path / "mdclaw"),
        "slurm_notes": ["Request GPUs with --gpus=N; --gres=gpu:N is rejected on this site.",
                        "The Slurm account is preset; do not pass --account."],
        "cells": [cell(), cell("cli_sif"), cell("sif_only")]}))
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    for path in attempts(root):
        manifest = json.loads(path.read_text())
        assert len(manifest["environment"]["slurm_notes"]) == 2
        capabilities = (Path(manifest["paths"]["workspace"]) / "CAPABILITIES.md").read_text()
        assert "Slurm note: Request GPUs with --gpus=N" in capabilities
        assert "Slurm note: The Slurm account is preset" in capabilities


def test_slurm_notes_must_be_strings(tmp_path):
    fake_checkout(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"tasks": [TASK], "replicates": 1, "sif": "/images/mdclaw.sif",
                                "mdclaw_cli": "/bin/true", "mdclaw_source": str(tmp_path / "mdclaw"),
                                "slurm_notes": "use --gpus", "cells": [cell()]}))
    with pytest.raises(ValueError, match="slurm_notes"):
        ex.init_experiment(str(tmp_path / "experiment"), str(spec), str(DATASET))
