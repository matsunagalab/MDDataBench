"""Validate and retain the source contract of campaign SLURM payloads.

This module is copied beside the attempt's standalone sbatch shim. CLI
conditions accept MDClaw's single-command and array script forms; arbitrary
shell programs cannot establish which Python package they will execute.
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


def _guard_command(line: str, source: Path, image: Path) -> str:
    # Reject expansion and shell control flow; re-emit validated literal argv.
    if any(token in line for token in ("$", "`", "\n")):
        raise ValueError("container command must use literal arguments")
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|<>()")
    lexer.whitespace_split = True
    tokens = list(lexer)
    if any(token and set(token) <= set(";&|<>()") for token in tokens):
        raise ValueError("use one MDClaw command per job or array task")
    if len(tokens) < 4 or Path(tokens[0]).name not in {"singularity", "apptainer"} or tokens[1] != "exec":
        raise ValueError("expected a Singularity/Apptainer exec command")
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
    if i >= len(tokens) or Path(tokens[i]).resolve() != image:
        raise ValueError("container image differs from the attempt manifest")
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
    payload = tokens[i + 1:]
    if not payload or payload[0] != "mdclaw":
        raise ValueError("CLI campaign jobs must invoke mdclaw directly")
    # The actual CLI runs in the interpreter whose imported package is checked.
    # Isolating its working directory avoids a workspace module shadowing the
    # frozen package when `python -c` puts cwd first on sys.path.
    checked = "import sys; sys.path = [p for p in sys.path if p]; " + RUNTIME_CHECK
    return shlex.join(tokens[:i + 1] + ["python", "-c", checked, str(source), *payload[1:]])


def guard_script(script: str, source: Path, image: Path) -> tuple[str, int]:
    """Accept the generated single-command or array grammar, guarding each arm."""
    lines = script.splitlines()
    scaffold = {'case "$SLURM_ARRAY_TASK_ID" in', '*)', ';;', 'esac', 'exit 1',
                'echo "Unknown SLURM_ARRAY_TASK_ID: $SLURM_ARRAY_TASK_ID" >&2'}
    count = 0
    for index, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith("#") or line in scaffold or re.fullmatch(r"\d+\)", line):
            continue
        if line.startswith('printf \'%s %s %s\\n\' "[array_task=${SLURM_ARRAY_TASK_ID}]" '):
            # Replace the generated banner with the runtime source record.
            lines[index] = ""
            continue
        lines[index] = "    " + _guard_command(line, source, image)
        count += 1
    if not count:
        raise ValueError("no MDClaw payload found")
    return "\n".join(lines) + "\n", count


def prepare_submission(arguments: list[str], manifest_path: str) -> tuple[list[str], dict | None]:
    """Validate a CLI job and submit a retained copy of the checked bytes."""
    manifest_file = Path(manifest_path).resolve()
    manifest = json.loads(manifest_file.read_text())
    if manifest["condition"] == "sif_only":
        return arguments, None
    source = Path(manifest["environment"]["mdclaw_source"]).resolve()
    image = Path(manifest["environment"]["sif"]).resolve()
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
    guarded, count = guard_script(script, source, image)
    directory = manifest_file.parent / "slurm" / "source-checked"
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = directory / f"{uuid.uuid4().hex}.sbatch"
    snapshot.write_text(guarded)
    snapshot.chmod(0o444)
    record = {"source": str(source), "image": str(image), "commands": count,
              "mdclaw_tree_sha256": manifest["revisions"].get("mdclaw_tree_sha256"),
              "original_script": str(original), "submitted_script": str(snapshot),
              "original_sha256": hashlib.sha256(script.encode()).hexdigest(),
              "submitted_sha256": hashlib.sha256(guarded.encode()).hexdigest()}
    return [*arguments[:-1], str(snapshot)], record
