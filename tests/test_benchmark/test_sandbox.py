"""The agent sandbox shows an attempt its own files, its images and the system, nothing else."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from mddatabench import experiments as ex
from mddatabench import sandbox
from mddatabench.source_overlay import sandbox_submission


def fake_attempt(tmp_path, condition="cli_sif", *, sandboxed=True):
    experiment = tmp_path / "experiment"
    attempt = experiment / "attempts" / "001_task" / f"{condition}__pi__model__r1"
    workspace = attempt / "workspace"
    workspace.mkdir(parents=True)
    host_binds = experiment / "host-binds"
    host_binds.mkdir()
    (host_binds / "passwd").write_text("root:x:0:0::/root:/bin/sh\n")
    image = tmp_path / "images" / "mdclaw-target.sif"
    image.parent.mkdir()
    image.write_text("image")
    link = tmp_path / "images" / "mdclaw.sif"
    link.symlink_to(image.name)
    runtime = tmp_path / "images" / "runtime.sif"
    runtime.write_text("runtime")
    manifest = {
        "attempt_id": f"001_task__{condition}__pi__model__r1", "condition": condition,
        "skill_source": "user",
        "paths": {"workspace": str(workspace), "task_file": "/harness/task.json",
                  "prompt_file": "/harness/prompt.md"},
        "reference": {"node": "mmb", "accession": "A0001", "bundle_sha256": "x"},
        "environment": {"sif": str(link), "sif_resolved": str(image),
                        "runtime_sif": str(runtime),
                        "container_binds": ["/usr/bin/sbatch", "/etc/slurm",
                                            f"{host_binds / 'passwd'}:/etc/passwd"],
                        "agent_sandbox": sandboxed}}
    (attempt / "manifest.json").write_text(json.dumps(manifest))
    return attempt, manifest


def fake_pi(tmp_path):
    agent = tmp_path / "pi-home" / ".pi" / "agent"
    (agent / "bin").mkdir(parents=True)
    (agent / "settings.json").write_text(json.dumps(
        {"defaultModel": "m", "packages": ["git:github.com/matsunagalab/mdclaw@main"]}))
    (agent / "models.json").write_text("{}")
    (agent / "auth.json").write_text("{}")
    (agent / "skills").mkdir()
    (agent / "extensions").mkdir()
    package = agent / "git" / "github.com" / "matsunagalab" / "mdclaw"
    (package / "skills" / "md-prepare").mkdir(parents=True)
    (package / "skills" / "md-prepare" / "SKILL.md").write_text("# md-prepare\n")
    (package / "package.json").write_text("{}")
    (package / "docs").mkdir()
    (package / "docs" / "memo.md").write_text("per-task failure analyses\n")
    install = tmp_path / "pi-home" / ".local" / "share" / "pi-node" / "node-v22"
    (install / "bin").mkdir(parents=True)
    return {"install_dirs": [str(install)], "agent_dir": str(agent),
            "real_home": str(tmp_path / "pi-home"), "skill_package": str(package),
            "user_skill_targets": str(tmp_path / "pi-home" / ".agents" / "skills")}


def binds(plan):
    return {op["dst"]: op for op in plan["ops"] if op["op"] in {"bind", "rbind"}}


def test_job_plan_lists_the_attempt_its_image_and_the_system_only(tmp_path):
    attempt, manifest = fake_attempt(tmp_path)
    sandbox.prepare_attempt(attempt, manifest)
    plan = json.loads((attempt / "sandbox" / "plan-job.json").read_text())
    shown = binds(plan)
    workspace = manifest["paths"]["workspace"]
    assert shown[workspace]["ro"] is False
    assert shown[str(attempt / "slurm")]["ro"] is True  # a job only reads the checked copies
    assert str(attempt / "agent-session") not in shown  # pi's session belongs to the agent
    assert shown[str(attempt / "manifest.json")]["src"] == str(
        attempt / "sandbox" / "manifest.agent.json")
    assert shown[str(attempt.parents[2] / "host-binds" / "passwd")]["ro"] is True
    image = manifest["environment"]["sif_resolved"]
    assert shown[image]["ro"] is True
    assert {"op": "symlink", "dst": manifest["environment"]["sif"], "target": image} in plan["ops"]
    assert shown[plan["home"]]["src"] == str(attempt / "sandbox" / "home")
    # Nothing else of the experiment, and never the sandbox directory itself.
    sources = [op.get("src", "") for op in plan["ops"]]
    assert not any(src == str(attempt) or src == str(attempt.parents[2]) for src in sources)
    assert not any(src.startswith(str(attempt / "sandbox")) and not src.endswith(
        ("home", "manifest.agent.json")) for src in sources)
    assert manifest["environment"]["runtime_sif"] not in shown


def test_sif_only_sees_its_runtime_image_and_not_the_mdclaw_image(tmp_path):
    attempt, manifest = fake_attempt(tmp_path, "sif_only")
    shown = binds(sandbox.build_plan(attempt, manifest, role="job"))
    assert manifest["environment"]["runtime_sif"] in shown
    assert manifest["environment"]["sif_resolved"] not in shown


def test_redacted_manifest_drops_the_reference_and_harness_paths(tmp_path):
    attempt, manifest = fake_attempt(tmp_path)
    visible = sandbox.redacted_manifest(manifest)
    assert "reference" not in visible
    assert visible["paths"] == {"workspace": manifest["paths"]["workspace"]}
    assert visible["environment"] == manifest["environment"]
    sandbox.prepare_attempt(attempt, manifest)
    written = json.loads((attempt / "sandbox" / "manifest.agent.json").read_text())
    assert "reference" not in written and "A0001" not in json.dumps(written)
    assert (attempt / "sandbox" / "sandbox.py").read_text() == Path(sandbox.__file__).read_text()


@pytest.mark.parametrize("condition", ["cli_sif", "sif_only"])
def test_no_skill_conditions_get_no_package_and_no_package_list(tmp_path, condition):
    attempt, manifest = fake_attempt(tmp_path, condition)
    pi = fake_pi(tmp_path)
    plan = sandbox.build_plan(attempt, manifest, role="agent", pi=pi)
    assert not any("/git/" in op.get("src", "") for op in plan["ops"])
    assert not any(op.get("src", "").endswith(("/skills", "/extensions")) for op in plan["ops"])
    settings = next(op for op in plan["ops"] if op["op"] == "write"
                    and op["dst"].endswith("settings.json"))
    assert "packages" not in json.loads(settings["text"])  # pi cannot fetch the skills itself
    shown = binds(plan)
    agent = Path(plan["home"]) / ".pi" / "agent"
    assert shown[str(agent / "auth.json")]["ro"] is True  # credentials bound, never copied
    assert pi["install_dirs"][0] in shown
    assert str(attempt / "agent-session") in shown


def test_skill_condition_gets_the_skills_and_nothing_else_of_the_checkout(tmp_path):
    attempt, manifest = fake_attempt(tmp_path, "cli_skill_sif")
    pi = fake_pi(tmp_path)
    plan = sandbox.build_plan(attempt, manifest, role="agent", pi=pi)
    package = Path(pi["skill_package"])
    sources = {op.get("src") for op in plan["ops"]}
    assert str(package / "skills") in sources and str(package / "package.json") in sources
    assert str(package) not in sources and str(package / "docs") not in sources
    settings = next(op for op in plan["ops"] if op["op"] == "write"
                    and op["dst"].endswith("settings.json"))
    assert json.loads(settings["text"])["packages"]


def test_a_pi_on_a_system_path_binds_nothing_over_the_root(tmp_path):
    attempt, manifest = fake_attempt(tmp_path)
    pi = {**fake_pi(tmp_path), "install_dirs": ["/", "/usr/local"]}
    plan = sandbox.build_plan(attempt, manifest, role="agent", pi=pi)
    assert not any(op["op"] == "bind" and op["src"] in {"/", "/usr/local"} for op in plan["ops"])


def test_sandbox_submission_wraps_a_script_and_keeps_its_directives(tmp_path):
    attempt, manifest = fake_attempt(tmp_path, "sif_only")
    script = Path(manifest["paths"]["workspace"]) / "job.sh"
    script.write_text("#!/bin/bash\n#SBATCH --gpus=1\n#SBATCH -J md\n\necho run\n#SBATCH --late\n")
    arguments = ["--time=00:20:00", "-J", "name", str(script), "arg1"]
    submitted, record = sandbox_submission(arguments, str(attempt / "manifest.json"))
    wrapper = Path(submitted[-2])
    assert submitted[:3] == ["--time=00:20:00", "-J", "name"] and submitted[-1] == "arg1"
    text = wrapper.read_text()
    assert text.startswith("#!/bin/bash\n#SBATCH --gpus=1\n#SBATCH -J md\n")
    assert "--late" not in text  # sbatch ignores directives after the first command too
    assert f"{attempt / 'sandbox' / 'sandbox.py'} --plan {attempt / 'sandbox' / 'plan-job.json'}" in text
    assert Path(record["payload"]).read_text() == script.read_text()
    assert not os.access(record["payload"], os.W_OK) and not os.access(wrapper, os.W_OK)


def test_sandbox_submission_turns_wrap_into_a_payload_and_refuses_stdin(tmp_path):
    attempt, manifest = fake_attempt(tmp_path, "sif_only")
    submitted, record = sandbox_submission(["--gpus=1", "--wrap=python md.py"],
                                           str(attempt / "manifest.json"))
    assert submitted[0] == "--gpus=1" and len(submitted) == 2
    assert Path(record["payload"]).read_text() == "#!/bin/bash\npython md.py\n"
    with pytest.raises(ValueError, match="standard input"):
        sandbox_submission(["--gpus=1"], str(attempt / "manifest.json"))


def test_unsandboxed_attempts_submit_unchanged(tmp_path):
    attempt, manifest = fake_attempt(tmp_path, "sif_only", sandboxed=False)
    arguments = ["--gpus=1", "job.sh"]
    assert sandbox_submission(arguments, str(attempt / "manifest.json")) == (arguments, None)


def test_the_operator_session_does_not_reach_a_sandboxed_agent():
    environment = {"PATH": "/usr/bin", "LANG": "C", "SLURM_CONF_SERVER": "s:6817",
                   "KEY_MODELLER10v8": "k", "CLAUDE_CODE_MESSAGING_TOKEN": "t",
                   "CLAUDECODE": "1", "HERDR_SOCKET_PATH": "/x", "XDG_RUNTIME_DIR": "/run/user/1",
                   "DBUS_SESSION_BUS_ADDRESS": "unix:x", "SSH_AUTH_SOCK": "/y",
                   "PI_CODING_AGENT_DIR": "/home/u/.pi/agent", "AI_AGENT": "claude"}
    assert ex._sandbox_environment(environment) == {
        "PATH": "/usr/bin", "LANG": "C", "SLURM_CONF_SERVER": "s:6817", "KEY_MODELLER10v8": "k"}


def test_agent_sandbox_is_a_boolean_and_needs_pi(tmp_path):
    from tests.test_benchmark.test_experiments import DATASET, cell, write_spec
    spec = json.loads(write_spec(tmp_path, [cell()]).read_text())
    with pytest.raises(ValueError, match="true or false"):
        ex._normalise_spec({**spec, "agent_sandbox": "yes"}, tmp_path / "e", DATASET)
    with pytest.raises(ValueError, match="pi harness only"):
        ex._normalise_spec({**spec, "agent_sandbox": True, "cells": [cell(harness="codex")]},
                           tmp_path / "e", DATASET)
    assert ex._normalise_spec(spec, tmp_path / "e", DATASET)["agent_sandbox"] is False


def test_sandboxed_image_attempts_launch_through_the_attempt_launcher(tmp_path, monkeypatch):
    from tests.test_benchmark.test_experiments import DATASET, attempts, cell, fake_probe, image_spec
    fake_probe(monkeypatch)
    probed = []
    monkeypatch.setattr(ex, "_probe_sandbox",
                        lambda root, spec, images: probed.append(root) or {"ok": True})
    spec, _ = image_spec(tmp_path, [cell("cli_sif")], agent_sandbox=True)
    root = tmp_path / "experiment"
    ex.init_experiment(str(root), str(spec), str(DATASET))
    assert probed == [root.resolve()]
    assert json.loads((root / "experiment.json").read_text())["sandbox_probe"] == {"ok": True}
    manifest_path = attempts(root)[0]
    attempt = manifest_path.parent
    assert json.loads(manifest_path.read_text())["environment"]["agent_sandbox"] is True
    assert (attempt / "sandbox" / "sandbox.py").is_file()
    assert (attempt / "sandbox" / "plan-job.json").is_file()
    dry = ex.run_attempt_agent(str(attempt), dry_run=True)
    assert dry["command"][1:4] == [str(attempt / "sandbox" / "sandbox.py"), "--plan",
                                   str(attempt / "sandbox" / "plan-agent.json")]
    assert dry["command"][4] == "--"
    assert dry["sandbox_plan"]["role"] == "agent"


def test_a_reset_retires_the_sandbox_with_the_run():
    assert "sandbox" in ex._RUN_RECORDS


# ---- the real thing, where the host allows unprivileged namespaces -----------

def _namespaces_available() -> bool:
    if not shutil.which("unshare"):
        return False
    probe = subprocess.run(["unshare", "--user", "--map-root-user", "--mount", "--pid", "--fork",
                            "true"], capture_output=True, check=False)
    return probe.returncode == 0


needs_namespaces = pytest.mark.skipif(not _namespaces_available(),
                                      reason="unprivileged user namespaces unavailable")


@needs_namespaces
def test_the_sandbox_hides_everything_but_the_attempt(tmp_path):
    attempt, manifest = fake_attempt(tmp_path, "sif_only")
    secret = tmp_path / "secret.txt"
    secret.write_text("reference answer")
    sibling = attempt.parent / "cli_skill_sif__pi__model__r1"
    sibling.mkdir()
    plan = sandbox.prepare_attempt(attempt, manifest)
    workspace = Path(manifest["paths"]["workspace"])
    script = (f'test ! -e {secret} && test ! -e {sibling} && test ! -e {attempt / "sandbox"} '
              f'&& test -e {manifest["environment"]["runtime_sif"]} '
              f'&& test ! -e {manifest["environment"]["sif_resolved"]} '
              f'&& test -z "$(ls -A "$HOME")" && touch {workspace / "made"} '
              f'&& ! touch /usr/x 2>/dev/null && test "$(id -u)" = "{os.getuid()}" '
              f'&& python3 -c "import json; m=json.load(open(\'{attempt / "manifest.json"}\')); '
              f'assert \'reference\' not in m" && echo INSIDE_OK')
    completed = subprocess.run(sandbox.launcher_command(attempt, plan, ["/bin/sh", "-c", script]),
                               cwd=workspace, capture_output=True, text=True, timeout=120)
    assert "INSIDE_OK" in completed.stdout, completed.stderr
    assert (workspace / "made").is_file()


@needs_namespaces
def test_the_exit_code_comes_back_and_left_over_processes_die(tmp_path):
    attempt, manifest = fake_attempt(tmp_path)
    plan = sandbox.prepare_attempt(attempt, manifest)
    marker = f"sleep {int(time.time()) % 100000 + 200000}"
    completed = subprocess.run(
        sandbox.launcher_command(attempt, plan, ["/bin/sh", "-c", f"setsid {marker} & exit 7"]),
        cwd=manifest["paths"]["workspace"], capture_output=True, text=True, timeout=120)
    assert completed.returncode == 7, completed.stderr
    time.sleep(1)
    survivors = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
    assert survivors.stdout.strip() == ""
