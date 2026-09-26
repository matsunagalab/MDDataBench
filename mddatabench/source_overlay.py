"""Validate and retain the source contract of campaign SLURM payloads.

This module is copied beside the attempt's standalone sbatch shim. CLI
conditions accept MDClaw's single-command and array script forms; arbitrary
shell programs cannot establish which Python package they will execute.

Two source modes exist. ``overlay`` binds a frozen checkout into the image and
imports it through ``PYTHONPATH``; every job must name exactly that checkout.
``image`` runs the package baked into the SIF and nothing else: ``PYTHONPATH``
must be empty, no bind may shadow the image's package, and the runtime check
compares the imported module with the path probed from the image at
``init_experiment`` time.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import uuid
from pathlib import Path


RUNTIME_CHECK = """import json, sys
from pathlib import Path
import mdclaw
expected = Path(sys.argv[1]).resolve() / 'mdclaw' / '__init__.py'
actual = Path(mdclaw.__file__).resolve()
if actual != expected:
    raise SystemExit('mddatabench_source_mismatch: expected %s, imported %s' % (expected, actual))
print('MDDATABENCH_SOURCE ' + json.dumps({'module': str(actual)}), file=sys.stderr, flush=True)
from mdclaw._cli import main
main(sys.argv[2:])
"""

IMAGE_RUNTIME_CHECK = """import json, os, sys
from pathlib import Path
expected = Path(sys.argv[1])
# An image may put its own site-packages on PYTHONPATH (this one does); any
# entry that does not contain the expected package is an overlay.
foreign = [p for p in os.environ.get('PYTHONPATH', '').split(os.pathsep)
           if p and not str(expected).startswith(str(Path(p).resolve()) + os.sep)]
if foreign:
    raise SystemExit('mddatabench_source_mismatch: PYTHONPATH reaches outside the image package: %r' % foreign)
import mdclaw
actual = Path(mdclaw.__file__).resolve()
if actual != expected:
    raise SystemExit('mddatabench_source_mismatch: expected image module %s, imported %s' % (expected, actual))
print('MDDATABENCH_SOURCE ' + json.dumps({'module': str(actual), 'mode': 'image'}), file=sys.stderr, flush=True)
from mdclaw._cli import main
main(sys.argv[2:])
"""


def _same_image(token: str, image: Path, aliases: tuple[Path, ...] = ()) -> bool:
    """Whether an exec line names the attempt's image.

    The shim runs inside the SIF in image mode, where the shared image path
    (a symlink replaced in place) and its target are usually not visible, so
    ``resolve()`` there cannot tell that the configured path and its resolved
    target are the same file. The manifest records both, taken on the host at
    init; either spelling is the attempt's image. MDClaw's own sif-slurm skill
    tells agents to pin the resolved path (kimi-k3 v4: 4 refusals, glm-5.3-flash
    3cond: 9, each followed by a hand-written script).
    """
    candidates = {image, *aliases}
    named = Path(token)
    return named in candidates or named.resolve() in {c.resolve() for c in candidates}


def _check_runtime(runtime: str, attempt_root: Path | None) -> None:
    """Refuse a container runtime the agent wrote into its own attempt directory.

    MDClaw resolves the runtime on the submitting PATH, which begins with the
    attempt's ``.mddatabench/bin``; an executable named ``singularity`` placed
    there (or anywhere in the attempt tree) would become the job's runtime and
    decide what actually runs. Three glm-5.3-flash attempts wrote such wrappers
    on 2026-09-26 (benign ones, forwarding to the host binary). MDClaw itself
    writes either a bare name or an absolute path, so nothing else is accepted.
    """
    named = Path(runtime)
    if named.name not in _CONTAINER_RUNTIMES:
        raise ValueError("expected a Singularity/Apptainer exec command")
    if not named.is_absolute() and runtime != named.name:
        raise ValueError(f"the container runtime {runtime!r} must be a bare name or an absolute path")
    if attempt_root is None or not named.is_absolute():
        return
    root = attempt_root.resolve()
    if named.is_relative_to(attempt_root) or named.resolve().is_relative_to(root):
        raise ValueError(
            f"the container runtime {runtime} is a file inside the attempt directory; delete it "
            f"and resubmit: without it submit_job writes a bare '{named.name}', which the job's "
            "generated preamble finds on the node")


def _guard_command(line: str, source: Path | None, image: Path, *, mode: str = "overlay",
                   module: Path | None = None, images: tuple[Path, ...] = (),
                   attempt_root: Path | None = None) -> str:
    # Reject expansion and shell control flow; re-emit validated literal argv.
    if any(token in line for token in ("$", "`", "\n")):
        raise ValueError("container command must use literal arguments")
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|<>()")
    lexer.whitespace_split = True
    tokens = list(lexer)
    if any(token and set(token) <= set(";&|<>()") for token in tokens):
        raise ValueError("use one MDClaw command per job or array task")
    if len(tokens) < 4 or Path(tokens[0]).name not in _CONTAINER_RUNTIMES or tokens[1] != "exec":
        raise ValueError("expected a Singularity/Apptainer exec command")
    _check_runtime(tokens[0], attempt_root)
    binds, env, i = [], {}, 2
    while i < len(tokens) and tokens[i].startswith("-"):
        option, sep, value = tokens[i].partition("=")
        if option in {"--nv", "--cleanenv", "--no-home"} and not sep:
            i += 1
            continue
        if option not in {"--bind", "-B", "--env", "--pwd"}:
            raise ValueError(f"unverifiable container option: {option}")
        if not sep:
            i += 1
            if i >= len(tokens):
                raise ValueError(f"missing value for {option}")
            value = tokens[i]
        if option in {"--bind", "-B"}:
            binds.extend(value.split(","))
        elif option == "--env":
            for item in value.split(","):
                key, equal, val = item.partition("=")
                if not equal or key in env:
                    raise ValueError("ambiguous container environment")
                env[key] = val
        i += 1
    if i >= len(tokens) or not _same_image(tokens[i], image, images):
        raise ValueError("container image differs from the attempt manifest")
    if mode == "image":
        if module is None:
            raise ValueError("image mode needs the probed image module path")
        if env.get("PYTHONPATH"):
            raise ValueError("container PYTHONPATH must be empty in image mode")
        for bind in binds:
            parts = bind.split(":")
            dest = Path(parts[1] if len(parts) > 1 else parts[0]).resolve()
            if dest == module or dest in module.parents:
                raise ValueError("a bind may shadow the image's MDClaw package")
        check_source = str(module)
        runtime_check = IMAGE_RUNTIME_CHECK
    elif mode == "overlay":
        if source is None:
            raise ValueError("overlay mode needs the frozen source path")
        if env.get("PYTHONPATH") != str(source):
            raise ValueError("container PYTHONPATH must be exactly the frozen MDClaw source")
        source_bound = False
        for bind in binds:
            parts = bind.split(":")
            host = Path(parts[0]).resolve()
            dest = Path(parts[1] if len(parts) > 1 else parts[0]).resolve()
            if dest == source and host == source:
                source_bound = True
            elif host != dest and (dest == source or dest in source.parents or source in dest.parents):
                raise ValueError("a bind may shadow the frozen source")
        if not source_bound:
            raise ValueError("the frozen source must be explicitly bound at its original path")
        check_source = str(source)
        runtime_check = RUNTIME_CHECK
    else:
        raise ValueError(f"unknown source mode {mode!r}")
    payload = tokens[i + 1:]
    if not payload or payload[0] != "mdclaw":
        raise ValueError("CLI campaign jobs must invoke mdclaw directly")
    # The actual CLI runs in the interpreter whose imported package is checked.
    # Isolating its working directory avoids a workspace module shadowing the
    # expected package when `python -c` puts cwd first on sys.path.
    checked = "import sys; sys.path = [p for p in sys.path if p]; " + runtime_check
    return shlex.join(tokens[:i + 1] + ["python", "-c", checked, check_source, *payload[1:]])


# MDClaw 87f6862 (2026-09-16) and later writes this block before the payload
# of every container-wrapped submit_job / submit_array_job script (mdclaw.slurm.
# config._container_runtime_preamble): when the runtime named on the exec lines
# is not on the node's PATH it sources the login profile and the module init,
# and does nothing else. It is accepted only verbatim, once, at top level
# before the first payload (never inside an array arm), naming the same
# runtime as every exec line, so no other shell can ride along with it. Until
# it was recognised the shim refused every script the image's own submit_job
# wrote (glm-5.3-flash 3cond, 2026-09-26: the first submission refused in 149
# of 153 CLI attempts that reached sbatch, agents then hand-writing scripts).
_RUNTIME_PREAMBLE_HEAD = re.compile(r"if ! command -v (\S+) >/dev/null 2>&1; then")
_RUNTIME_PREAMBLE_BODY = (
    "[ -r /etc/profile ] && . /etc/profile >/dev/null 2>&1 || true",
    '[ -r "${MDCLAW_MODULE_INIT:-/etc/profile.d/modules.sh}" ] && '
    '. "${MDCLAW_MODULE_INIT:-/etc/profile.d/modules.sh}" >/dev/null 2>&1 || true',
    "fi",
)
_CONTAINER_RUNTIMES = {"singularity", "apptainer"}
_CASE_OPEN = 'case "$SLURM_ARRAY_TASK_ID" in'


def _runtime_preamble(lines: list[str], index: int) -> str | None:
    """The runtime named by a verbatim runtime preamble starting at ``index``."""
    match = _RUNTIME_PREAMBLE_HEAD.fullmatch(lines[index].strip())
    if not match:
        return None
    body = [line.strip() for line in lines[index + 1:index + 1 + len(_RUNTIME_PREAMBLE_BODY)]]
    if tuple(body) != _RUNTIME_PREAMBLE_BODY:
        raise ValueError("the container runtime preamble differs from the one MDClaw generates")
    try:
        (runtime,) = shlex.split(match.group(1))
    except ValueError:
        raise ValueError("the container runtime preamble must name one runtime") from None
    if Path(runtime).name not in _CONTAINER_RUNTIMES:
        raise ValueError("the container runtime preamble must name singularity or apptainer")
    return runtime


def guard_script(script: str, source: Path | None, image: Path, *, mode: str = "overlay",
                 module: Path | None = None, images: tuple[Path, ...] = (),
                 attempt_root: Path | None = None) -> tuple[str, int]:
    """Accept the generated single-command or array grammar, guarding each arm.

    Besides the payload lines and the array ``case`` scaffold, the only shell
    accepted is MDClaw's container-runtime preamble, verbatim. ``images`` are
    other spellings of the attempt's image (its host-resolved path);
    ``attempt_root`` is the attempt directory, where no container runtime may
    live.
    """
    lines = script.splitlines()
    if any(line.startswith("# NVIDIA MPS:") for line in lines):
        raise ValueError("an MPS-packed job (submit_mps_job) cannot be audited in a benchmark "
                         "attempt; submit each node with submit_job or submit_array_job")
    scaffold = {_CASE_OPEN, '*)', ';;', 'esac', 'exit 1',
                'echo "Unknown SLURM_ARRAY_TASK_ID: $SLURM_ARRAY_TASK_ID" >&2'}
    count = 0
    preamble_runtime = None
    in_case = False
    skip = 0
    for index, line in enumerate(lines):
        if skip:
            skip -= 1
            continue
        line = line.strip()
        if line == _CASE_OPEN:
            in_case = True
        if not line or line.startswith("#") or line in scaffold or re.fullmatch(r"\d+\)", line):
            continue
        try:
            runtime = _runtime_preamble(lines, index)
        except ValueError as exc:
            raise ValueError(f"{exc} (refused line: {line[:160]!r})") from None
        if runtime is not None:
            if preamble_runtime is not None or count or in_case:
                raise ValueError("the container runtime preamble must come once, "
                                 "before the payload and outside the array dispatch")
            _check_runtime(runtime, attempt_root)
            preamble_runtime = runtime
            skip = len(_RUNTIME_PREAMBLE_BODY)
            continue
        if line.startswith('printf \'%s %s %s\\n\' "[array_task=${SLURM_ARRAY_TASK_ID}]" '):
            # Replace the generated banner with the runtime source record.
            lines[index] = ""
            continue
        if preamble_runtime is not None:
            try:
                first = shlex.split(line)[0]
            except (ValueError, IndexError):
                first = None
            if first is not None and Path(first).name in _CONTAINER_RUNTIMES and first != preamble_runtime:
                raise ValueError("the payload's container runtime differs from the one its preamble checks")
        try:
            lines[index] = "    " + _guard_command(line, source, image, mode=mode, module=module,
                                                   images=images, attempt_root=attempt_root)
        except ValueError as exc:
            raise ValueError(f"{exc} (refused line: {line[:160]!r})") from None
        count += 1
    if not count:
        raise ValueError("no MDClaw payload found")
    return "\n".join(lines) + "\n", count


def source_mode(manifest: dict) -> str:
    """The attempt's source contract: ``overlay`` (default), ``image`` or ``none``."""
    if manifest.get("condition") == "sif_only":
        return "none"
    environment = manifest.get("environment") or {}
    return str(environment.get("source_mode") or "overlay")


def prepare_submission(arguments: list[str], manifest_path: str) -> tuple[list[str], dict | None]:
    """Validate a CLI job and submit a retained copy of the checked bytes."""
    manifest_file = Path(manifest_path).resolve()
    manifest = json.loads(manifest_file.read_text())
    mode = source_mode(manifest)
    if mode == "none":
        return arguments, None
    environment = manifest["environment"]
    image = Path(environment["sif"]).resolve()
    source = module = None
    if mode == "image":
        module = Path(environment["image_mdclaw_module"])
    else:
        source = Path(environment["mdclaw_source"]).resolve()
        if not (source / "mdclaw" / "__init__.py").is_file() or not (source / "bin" / "mdclaw").is_file():
            raise ValueError("frozen MDClaw source is unavailable")
    # MDClaw passes one script path, without script arguments. Scheduler
    # overrides may precede it, but --wrap/stdin cannot be audited as a file.
    if not arguments or any(arg == "--wrap" or arg.startswith("--wrap=") for arg in arguments):
        raise ValueError("submit a generated script file, not --wrap or stdin")
    if any(not arg.startswith("-") for arg in arguments[:-1]):
        raise ValueError("submit one script without script arguments; use --option=value for sbatch options")
    original = Path(arguments[-1]).resolve()
    if not original.is_file():
        raise ValueError("the last sbatch argument must be a generated script file")
    script = original.read_text()
    aliases = tuple(Path(p) for p in (environment.get("sif_resolved"),) if p)
    guarded, count = guard_script(script, source, image, mode=mode, module=module,
                                  images=aliases, attempt_root=manifest_file.parent)
    directory = manifest_file.parent / "slurm" / "source-checked"
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = directory / f"{uuid.uuid4().hex}.sbatch"
    snapshot.write_text(guarded)
    snapshot.chmod(0o444)
    record = {"source_mode": mode, "source": str(source) if source else None,
              "image": str(image), "commands": count,
              "mdclaw_tree_sha256": manifest["revisions"].get("mdclaw_tree_sha256"),
              "image_mdclaw_module": str(module) if module else None,
              "sif_sha256": (manifest.get("hashes") or {}).get("sif"),
              "original_script": str(original), "submitted_script": str(snapshot),
              "original_sha256": hashlib.sha256(script.encode()).hexdigest(),
              "submitted_sha256": hashlib.sha256(guarded.encode()).hexdigest()}
    arguments = [*arguments[:-1], str(snapshot)]
    return arguments, record
