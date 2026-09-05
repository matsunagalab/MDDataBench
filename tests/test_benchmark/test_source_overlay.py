"""Campaign source enforcement covers generated jobs and the runtime import."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mddatabench import sbatch_shim
from mddatabench.source_overlay import RUNTIME_CHECK, guard_script, prepare_submission


def command(source, image="/images/mdclaw.sif"):
    return shlex.join(["singularity", "exec", "--nv", "--bind", str(source),
                       "--env", f"PYTHONPATH={source}", str(image), "mdclaw", "--version"])


def manifest(tmp_path, condition="cli_sif"):
    source = tmp_path / "frozen source"
    (source / "mdclaw").mkdir(parents=True)
    (source / "bin").mkdir()
    (source / "mdclaw/__init__.py").write_text("")
    (source / "bin/mdclaw").write_text("")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "condition": condition,
        "environment": {"mdclaw_source": str(source), "sif": "/images/mdclaw.sif"},
        "revisions": {"mdclaw_tree_sha256": "recorded-frozen-tree"},
    }))
    return path, source


@pytest.mark.parametrize("fault", ["image_mode", "live_source", "missing_bind", "different_image",
                                   "pythonpath_suffix", "shadow_bind", "env_override", "custom_shell",
                                   "bare_mdclaw", "nested_script", "expansion"])
def test_invalid_source_jobs_never_reach_sbatch(tmp_path, monkeypatch, capsys, fault):
    path, source = manifest(tmp_path)
    line = command(source)
    if fault == "image_mode":
        line = shlex.join(["singularity", "exec", "--nv", "/images/mdclaw.sif", "mdclaw", "--version"])
    elif fault == "live_source":
        line = command(tmp_path / "live")
    elif fault == "missing_bind":
        tokens = shlex.split(line)
        del tokens[3:5]
        line = shlex.join(tokens)
    elif fault == "different_image":
        line = command(source, "/images/other.sif")
    elif fault == "pythonpath_suffix":
        line = line.replace(f"PYTHONPATH={source}", f"PYTHONPATH={source}:/live")
    elif fault == "shadow_bind":
        line = line.replace(" exec ", f" exec --bind /other:{shlex.quote(str(source))} ")
    elif fault == "env_override":
        line = line.replace(" exec ", " exec --env PYTHONPATH=/live ")
    elif fault == "custom_shell":
        line += "\necho done"
    elif fault == "bare_mdclaw":
        line = "mdclaw --version"
    elif fault == "nested_script":
        line = line.replace("mdclaw --version", "bash run.sh")
    else:
        line += " $(echo --help)"
    script = tmp_path / "job.sbatch"
    script.write_text("#!/bin/bash\n" + line + "\n")
    monkeypatch.setenv("MDDATABENCH_MANIFEST", str(path))
    monkeypatch.setenv("MDDATABENCH_EVENT_LOG", str(tmp_path / "events.jsonl"))
    def forbidden(*args, **kwargs):
        pytest.fail("invalid job reached sbatch")
    monkeypatch.setattr(sbatch_shim.subprocess, "run", forbidden)
    assert sbatch_shim.main([str(script)]) == 2
    assert "mddatabench_source_overlay_invalid" in capsys.readouterr().err
    assert not (tmp_path / "slurm/source-checked").exists()


def test_valid_submission_retains_checked_bytes_and_provenance(tmp_path, monkeypatch):
    path, source = manifest(tmp_path)
    script = tmp_path / "job.sbatch"
    original = "#!/bin/bash\n#SBATCH --dependency=afterok:123\n" + command(source) + "\n"
    script.write_text(original)
    event_log = tmp_path / "events.jsonl"
    monkeypatch.setenv("MDDATABENCH_MANIFEST", str(path))
    monkeypatch.setenv("MDDATABENCH_EVENT_LOG", str(event_log))
    captured = []
    def fake_run(argv, **kwargs):
        captured.append(argv)
        return SimpleNamespace(returncode=0, stdout="Submitted batch job 456\n", stderr="")
    monkeypatch.setattr(sbatch_shim.subprocess, "run", fake_run)
    assert sbatch_shim.main([str(script)]) == 0
    snapshot = Path(captured[0][-1])
    assert snapshot != script
    assert "#SBATCH --dependency=afterok:123" in snapshot.read_text()
    assert "mddatabench_source_mismatch" in snapshot.read_text()
    assert not snapshot.stat().st_mode & 0o222
    assert script.read_text() == original
    event = json.loads(event_log.read_text())
    assert event["job_id"] == "456"
    assert event["source_overlay"]["source"] == str(source)
    assert event["source_overlay"]["mdclaw_tree_sha256"] == "recorded-frozen-tree"
    assert event["source_overlay"]["submitted_script"] == str(snapshot)


def test_sif_only_does_not_require_mdclaw_jobs(tmp_path):
    path, _ = manifest(tmp_path, "sif_only")
    args = ["--wrap=python custom_simulation.py"]
    assert prepare_submission(args, str(path)) == (args, None)


@pytest.mark.parametrize("same_source", [True, False])
def test_runtime_check_executes_only_the_expected_package(tmp_path, same_source):
    _, expected = manifest(tmp_path)
    actual = expected if same_source else tmp_path / "other"
    (actual / "mdclaw").mkdir(parents=True, exist_ok=True)
    (actual / "mdclaw/__init__.py").write_text("")
    (actual / "mdclaw/_cli.py").write_text("def main(argv):\n    print('CLI_EXECUTED', argv)\n")
    completed = subprocess.run([sys.executable, "-c", RUNTIME_CHECK, str(expected), "--version"],
                               cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(actual)},
                               text=True, capture_output=True, timeout=30)
    assert (completed.returncode == 0) is same_source
    assert ("CLI_EXECUTED" in completed.stdout) is same_source
    assert ("MDDATABENCH_SOURCE" in completed.stderr) is same_source
    if not same_source:
        assert "mddatabench_source_mismatch" in completed.stderr


@pytest.mark.parametrize("array", [False, True])
def test_actual_mdclaw_generators_are_accepted(tmp_path, array):
    sbatch = pytest.importorskip("mdclaw.slurm.sbatch")
    source = tmp_path / "frozen"
    container = {"image": "/images/mdclaw.sif", "source_mode": "overlay", "source_root": str(source),
                 "extra_flags": "--nv"}
    common = dict(job_name="probe", partition="all", cpus_per_task=1, gpus=0, gres=None,
                  time_limit="00:01:00", memory=None, dependency=None, output_dir=str(tmp_path),
                  account=None, qos=None, extra_sbatch=None, environment=None,
                  stdout_log="probe.out", stderr_log="probe.err", container=container)
    if array:
        script = sbatch._generate_array_sbatch_script(
            tasks=[{"command": "mdclaw --version", "job_dir": str(tmp_path / str(i)),
                    "node_id": "prod_001"} for i in range(2)], max_concurrent=None, **common)
    else:
        script = sbatch._generate_sbatch_script(command="mdclaw --version", nodes=1, ntasks=1,
                                                nodelist=None, **common)
    checked, count = guard_script(script, source, Path(container["image"]))
    assert count == (2 if array else 1)
    assert checked.count("MDDATABENCH_SOURCE") == count
    assert subprocess.run(["bash", "-n"], input=checked, text=True, capture_output=True).returncode == 0
    if array:
        # Every arm must be validated, including a bad second arm.
        head, _, tail = script.rpartition(f"PYTHONPATH={source}")
        broken = head + "PYTHONPATH=/live" + tail
        with pytest.raises(ValueError, match="PYTHONPATH"):
            guard_script(broken, source, Path(container["image"]))
