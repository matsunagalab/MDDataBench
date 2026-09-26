"""Filesystem sandbox for one attempt's agent and for the Slurm jobs it submits.

Why. Agents run as the campaign owner and can read whatever the owner can. An
audit of glm-5.3-flash-3cond-full (2026-09-26, 229 transcripts) found a
CLI-only agent (063_metal_6wrh cli_sif r2) that located the owner's MDClaw
checkout and read about ten skill pages, and another (005_membrane_6a93
cli_sif r3) that read a skill-condition attempt's submitted scripts. The agent
instructions forbid both; this module removes the files from view.

How. ``unshare`` puts the process into new user, mount and PID namespaces; no
root and no setuid helper are involved. A new root is assembled on a tmpfs
from read-only system trees, the site software, the attempt's own
directories, the images and a per-attempt home, and ``pivot_root`` makes it
the only view: the owner's home, other attempts and campaigns, the harness
checkout, the reference bundles and other processes do not exist inside. The
command then runs in a nested user namespace as the owner's uid with no
capabilities, so it cannot undo the mounts. Apptainer, called inside, cannot
use its setuid starter there and runs the SIF in its own user namespace
through squashfuse (measured on the Rikyu login node: ``mdclaw --version``
took 3.7 s this way and 4.2 s setuid, and the SIF was not extracted). When the
command exits, or the attempt is killed, the PID namespace ends and takes
every process the agent left behind with it.

Threat model. This closes what an agent sees by exploring (``find /``, ``ls
~``, a path it noticed in some output). It is not a wall against an agent that
sets out to escape: the real ``sbatch`` stays reachable, and a job submitted
around the shim runs unsandboxed. Such a job is absent from the shim's record
and present in Slurm accounting, so it can be found afterwards.

Stdlib only: the harness copies this file into every attempt directory and
runs it with the host ``python3`` on the login node and at the start of every
agent job on a compute node.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import pwd
import shutil
import signal
import subprocess
import sys
from pathlib import Path

PLAN_SCHEMA = 1

# Read-only system trees every sandbox sees. /home, /data1, /fast1 and /tmp
# (the other top-level mounts on Rikyu) are absent unless a bind names a path
# in them.
SYSTEM_TREES = ("/usr", "/etc", "/var", "/opt")
# Site software the agent needs: Apptainer, which is self-contained here (its
# wrapper adds only its own utils/ to PATH and LD_LIBRARY_PATH). The rest of
# /shared (spack, CUDA, the HPC SDK, model weights) is left out: nothing an
# attempt runs uses it, and a `find /` through it on Lustre took minutes.
SITE_SOFTWARE = ("/shared/software/apptainer",)
TOP_LEVEL_LINKS = ("/bin", "/sbin", "/lib", "/lib64", "/lib32", "/libx32")
# Mount flags a user namespace cannot clear on a mount it inherited; a
# read-only remount must repeat them or the kernel refuses it.
_LOCKED_FLAGS = {"nosuid", "nodev", "noexec", "noatime", "nodiratime", "relatime",
                 "strictatime", "lazytime"}
_PIVOT_ROOT_SYSCALL = {"aarch64": 41, "arm64": 41, "x86_64": 155}
_GRACE_SECONDS = 8


def redacted_manifest(manifest: dict) -> dict:
    """The manifest as the agent and its jobs may see it.

    The shim needs the environment, hashes and revisions. The MDDB accession of
    the reference and the harness paths of task.json and the prompt are the
    evaluator's, not the agent's.
    """
    visible = {key: value for key, value in manifest.items() if key != "reference"}
    paths = dict(visible.get("paths") or {})
    paths.pop("task_file", None)
    paths.pop("prompt_file", None)
    visible["paths"] = paths
    return visible


def _op(op: str, dst: str, **fields) -> dict:
    return {"op": op, "dst": str(dst), **fields}


def _system_ops() -> list[dict]:
    ops = []
    for tree in SYSTEM_TREES:
        if os.path.isdir(tree):
            ops.append(_op("rbind", tree, src=tree, ro=True))
    for link in TOP_LEVEL_LINKS:
        if os.path.islink(link):
            ops.append(_op("symlink", link, target=os.readlink(link)))
        elif os.path.isdir(link):
            ops.append(_op("rbind", link, src=link, ro=True))
    ops += [_op("rbind", "/dev", src="/dev"),
            _op("tmpfs", "/dev/shm", mode="1777", size="8g", hide=True),
            _op("rbind", "/sys", src="/sys"),
            _op("proc", "/proc"),
            _op("rbind", "/run", src="/run"),
            # Runtime directories of the owner's other sessions (sockets, agents).
            _op("tmpfs", "/run/user", mode="0755", size="16m", hide=True),
            _op("tmpfs", "/tmp", mode="1777", size="64g"),
            _op("tmpfs", "/var/tmp", mode="1777", size="16g", hide=True)]
    for tree in SITE_SOFTWARE:
        if os.path.isdir(tree):
            ops.append(_op("rbind", tree, src=tree, ro=True))
    return ops


def _file_bind(src, dst, ro=True) -> list[dict]:
    src, dst = str(src), str(dst)
    return [_op("bind", dst, src=src, ro=ro)] if os.path.exists(src) else []


def _image_ops(path: str | None, resolved: str | None) -> list[dict]:
    """Show one image under the name the agent is given and its resolved name."""
    if not path:
        return []
    target = os.path.realpath(resolved or path)
    ops = _file_bind(target, target)
    if os.path.abspath(path) != target:
        ops.append(_op("symlink", os.path.abspath(path), target=target))
    return ops


def _pi_ops(home: str, pi: dict, skills: bool) -> list[dict]:
    """pi's installation and a minimal agent directory.

    The agent directory is assembled on a tmpfs: settings are copied (pi may
    write them), credentials are bound read-only and never copied into the
    attempt. The no-skill conditions get settings without the package list, so
    pi cannot fetch the MDClaw package by itself; the skill condition gets the
    package's manifest and ``skills/`` and nothing else of the checkout (whose
    docs/ hold the benchmark memo with per-task failure analyses).
    """
    ops = []
    system = SYSTEM_TREES + TOP_LEVEL_LINKS
    for root in pi.get("install_dirs") or []:
        # A pi on a system path is already visible; never bind a system tree
        # (or /) over the new root.
        if root == "/" or any(root == tree or root.startswith(tree + "/") for tree in system):
            continue
        ops.append(_op("bind", root, src=root, ro=True))
    agent_src = Path(pi["agent_dir"])
    agent = Path(home) / ".pi" / "agent"
    ops.append(_op("tmpfs", Path(home) / ".pi", mode="0700", size="64m"))
    ops.append(_op("mkdir", agent / "tmp", mode="0700"))
    settings = {}
    if (agent_src / "settings.json").is_file():
        try:
            settings = json.loads((agent_src / "settings.json").read_text())
        except ValueError:
            settings = {}
    if not skills:
        settings.pop("packages", None)
    ops.append(_op("write", agent / "settings.json", text=json.dumps(settings, indent=2) + "\n",
                   mode="0600"))
    for name in ("models.json", "auth.json"):
        ops += _file_bind(agent_src / name, agent / name)
    if (agent_src / "bin").is_dir():  # fd and rg, which pi otherwise downloads
        ops.append(_op("bind", agent / "bin", src=str(agent_src / "bin"), ro=True))
    if skills:
        package = pi.get("skill_package")
        if package:
            package = Path(package)
            relative = package.relative_to(agent_src)
            ops += _file_bind(package / "package.json", agent / relative / "package.json")
            ops.append(_op("bind", agent / relative / "skills", src=str(package / "skills"),
                           ro=True))
        for name in ("skills", "extensions"):
            if (agent_src / name).is_dir():
                ops.append(_op("bind", agent / name, src=str(agent_src / name), ro=True))
        # ~/.pi/agent/skills holds relative links into ~/.agents/skills.
        user_skill_targets = Path(pi.get("user_skill_targets") or "")
        if pi.get("user_skill_targets") and user_skill_targets.is_dir():
            ops.append(_op("bind", Path(home) / user_skill_targets.relative_to(pi["real_home"]),
                           src=str(user_skill_targets), ro=True))
    return ops


def build_plan(attempt: Path, manifest: dict, *, role: str, pi: dict | None = None) -> dict:
    """The view one attempt's agent (``role='agent'``) or job (``'job'``) gets.

    Everything the process may see is listed; nothing else exists inside.
    """
    if role not in {"agent", "job"}:
        raise ValueError("role must be 'agent' or 'job'")
    attempt = Path(attempt).resolve()
    environment = manifest.get("environment") or {}
    user = pwd.getpwuid(os.getuid())
    home = user.pw_dir
    sandbox_dir = attempt / "sandbox"
    ops = _system_ops()
    ops.append(_op("bind", home, src=str(sandbox_dir / "home"), ro=False))
    workspace = Path((manifest.get("paths") or {}).get("workspace") or attempt / "workspace")
    ops.append(_op("bind", workspace, src=str(workspace), ro=False))
    # The shim keeps its checked copies under slurm/; a job only reads them.
    ops.append(_op("bind", attempt / "slurm", src=str(attempt / "slurm"), ro=(role == "job")))
    if role == "agent":
        ops.append(_op("bind", attempt / "agent-session", src=str(attempt / "agent-session"),
                       ro=False))
    ops += _file_bind(sandbox_dir / "manifest.agent.json", attempt / "manifest.json")
    # Experiment-level files the container binds name (passwd/group copies).
    experiment = attempt.parents[2]
    for entry in environment.get("container_binds") or []:
        source = entry.split(":", 1)[0]
        if Path(source).resolve().is_relative_to(experiment):
            ops += _file_bind(source, source)
    if manifest.get("condition") == "sif_only":
        # The runtime image only: the MDClaw image is the CLI conditions' tool
        # (the manifest names it for every condition, the SIF-only agent is
        # never told of it).
        ops += _image_ops(environment.get("runtime_sif"), None)
    else:
        ops += _image_ops(environment.get("sif"), environment.get("sif_resolved"))
    if role == "agent" and pi:
        ops += _pi_ops(home, pi, skills=manifest.get("condition") == "cli_skill_sif")
    return {"schema": PLAN_SCHEMA, "role": role, "attempt_id": manifest.get("attempt_id"),
            "uid": os.getuid(), "gid": os.getgid(), "home": home,
            "newroot": str(sandbox_dir / "root"), "cwd": str(workspace), "ops": ops}


def prepare_attempt(attempt: Path, manifest: dict) -> Path:
    """Create the attempt's sandbox directory; return the job plan's path.

    ``sandbox/`` is never shown to the agent: it holds the launcher its jobs
    run, the plans, and the redacted manifest, none of which it may change.
    Only ``sandbox/home`` appears inside, as the agent's home.
    """
    sandbox_dir = Path(attempt) / "sandbox"
    for name in ("home", "root"):
        (sandbox_dir / name).mkdir(parents=True, exist_ok=True)
    (Path(attempt) / "slurm").mkdir(exist_ok=True)
    (Path(attempt) / "agent-session").mkdir(exist_ok=True)
    shutil.copy2(__file__, sandbox_dir / "sandbox.py")
    (sandbox_dir / "manifest.agent.json").write_text(
        json.dumps(redacted_manifest(manifest), indent=2, sort_keys=True) + "\n")
    job_plan = sandbox_dir / "plan-job.json"
    job_plan.write_text(json.dumps(build_plan(attempt, manifest, role="job"), indent=2) + "\n")
    return job_plan


def launcher_command(attempt: Path, plan_path: Path, command: list[str]) -> list[str]:
    python = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
    return [python, str(Path(attempt) / "sandbox" / "sandbox.py"), "--plan", str(plan_path),
            "--", *command]


# ---- inside the namespaces ---------------------------------------------------

def _run(argv: list[str]) -> None:
    completed = subprocess.run(argv, capture_output=True, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"{' '.join(argv)}: {completed.stderr.strip() or completed.returncode}")


def _mountpoint(dst: str, directory: bool) -> None:
    if directory:
        os.makedirs(dst, exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.lexists(dst):
            open(dst, "a").close()


def _remount_ro(dst: str) -> None:
    options = subprocess.run(["findmnt", "-n", "-o", "VFS-OPTIONS", "--mountpoint", dst],
                             capture_output=True, text=True, check=False).stdout.strip()
    kept = [flag for flag in options.split(",") if flag in _LOCKED_FLAGS]
    _run(["mount", "-o", ",".join(["remount", "bind", "ro", *kept]), dst])


def _apply(op: dict, root: str) -> None:
    dst = root + op["dst"]
    kind = op["op"]
    if kind in {"bind", "rbind"}:
        src = op["src"]
        if not os.path.exists(src):
            raise RuntimeError(f"sandbox source does not exist: {src}")
        _mountpoint(dst, os.path.isdir(src))
        _run(["mount", "--rbind" if kind == "rbind" else "--bind", src, dst])
        if op.get("ro"):
            _remount_ro(dst)
    elif kind == "tmpfs":
        if op.get("hide") and not os.path.isdir(dst):
            return  # covers a directory of a shown tree; nothing there to cover
        os.makedirs(dst, exist_ok=True)
        _run(["mount", "-t", "tmpfs", "-o", f"mode={op.get('mode', '0755')},"
              f"size={op.get('size', '1g')}", "tmpfs", dst])
    elif kind == "proc":
        os.makedirs(dst, exist_ok=True)
        _run(["mount", "-t", "proc", "-o", "nosuid,nodev,noexec", "proc", dst])
    elif kind == "symlink":
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.lexists(dst):
            os.symlink(op["target"], dst)
    elif kind == "mkdir":
        os.makedirs(dst, exist_ok=True)
        os.chmod(dst, int(op.get("mode", "0755"), 8))
    elif kind == "write":
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w") as handle:
            handle.write(op["text"])
        os.chmod(dst, int(op.get("mode", "0644"), 8))
    else:
        raise RuntimeError(f"unknown sandbox operation {kind!r}")


def _pivot_root(root: str) -> None:
    os.chdir(root)
    os.makedirs(".oldroot", exist_ok=True)
    tool = shutil.which("pivot_root") or "/usr/sbin/pivot_root"
    if os.path.exists(tool):
        _run([tool, ".", ".oldroot"])
    else:
        number = _PIVOT_ROOT_SYSCALL[platform.machine()]
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.syscall(number, b".", b".oldroot") != 0:
            raise OSError(ctypes.get_errno(), "pivot_root failed")
    os.chdir("/")
    _run(["umount", "-l", "/.oldroot"])
    os.rmdir("/.oldroot")


def _exit_code(status: int) -> int:
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


def _inside(plan: dict, command: list[str]) -> int:
    """PID 1 of the sandbox: build the root, start the command, reap, forward signals."""
    root = plan["newroot"]
    os.makedirs(root, exist_ok=True)
    _run(["mount", "-t", "tmpfs", "-o", "mode=0755,size=256m", "tmpfs", root])
    for op in plan["ops"]:
        _apply(op, root)
    # A job starts where sbatch was called; the agent where the harness put it.
    # Both paths are bound at the same place inside.
    start = os.getcwd()
    _pivot_root(root)
    child = os.fork()
    if child == 0:
        try:
            os.setpgid(0, 0)
            try:
                os.chdir(start)
            except OSError:
                os.chdir(plan.get("cwd") or "/")
            os.environ["HOME"] = plan["home"]
            os.execvp("unshare", ["unshare", "--user", f"--map-user={plan['uid']}",
                                  f"--map-group={plan['gid']}", "--", *command])
        except OSError as exc:
            sys.stderr.write(f"mddatabench sandbox: cannot start {command[:1]}: {exc}\n")
        os._exit(127)

    def forward(signum, frame):
        try:
            os.killpg(child, signal.SIGTERM)
        except ProcessLookupError:
            pass
        signal.signal(signal.SIGALRM, lambda *_: os._exit(128 + signum))
        signal.alarm(_GRACE_SECONDS)

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, forward)
    while True:
        try:
            pid, status = os.waitpid(-1, 0)
        except ChildProcessError:
            return 1
        if pid == child:
            # Returning ends PID 1, and the kernel kills whatever is left.
            return _exit_code(status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--plan", required=True)
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command given")
    plan = json.loads(Path(args.plan).read_text())
    if plan.get("schema") != PLAN_SCHEMA:
        parser.error(f"unsupported sandbox plan schema {plan.get('schema')!r}")
    if args.inside:
        try:
            return _inside(plan, command)
        except Exception as exc:  # noqa: BLE001 - report and fail the attempt visibly
            sys.stderr.write(f"mddatabench sandbox: {exc}\n")
            return 125
    unshare = shutil.which("unshare") or "/usr/bin/unshare"
    # --kill-child: when this process dies (the harness's timeout, Slurm's
    # time limit), PID 1 inside gets SIGTERM, forwards it, and the namespace
    # ends a few seconds later with everything in it.
    os.execv(unshare, [unshare, "--user", "--map-root-user", "--mount", "--pid", "--fork",
                       "--kill-child=SIGTERM", "--", sys.executable, os.path.abspath(__file__),
                       "--plan", os.path.abspath(args.plan), "--inside", "--", *command])
    return 127  # not reached


if __name__ == "__main__":
    raise SystemExit(main())
