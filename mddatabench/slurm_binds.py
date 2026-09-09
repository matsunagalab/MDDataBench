"""Discover the host resources a SIF needs to run Slurm clients inside it.

Image-mode attempts invoke ``mdclaw`` only through ``singularity exec`` on the
shared image, including its Slurm tools. Those call the *host's* ``sbatch``,
``squeue`` and ``sacct``, which the image does not contain. The evaluator
therefore binds the host clients, their Slurm plugin directory, the munge
library and socket, the Slurm configuration directory, and a passwd/group pair
that names both the invoking account and ``SlurmUser``; Apptainer's synthetic
``/etc/passwd`` holds only the current user, which makes the configuration
parse fail (``Invalid user for SlurmUser slurm``) and, on NIS/LDAP hosts, the
host's own ``/etc/passwd`` lacks the invoking user (``Invalid user: <you>``).
Measured on Rikyu, 2026-09-09.

Nothing here is Rikyu-specific: clients come from ``PATH``, directories from
``scontrol show config`` and ``ldd``, and the result is a plain bind list that
an operator can also write by hand as ``container_binds`` in the campaign spec.
"""

from __future__ import annotations

import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path

CLIENTS = ("sbatch", "squeue", "sacct", "scancel", "sinfo", "scontrol")
_LIBRARY_PATTERN = re.compile(r"^\s*(\S+)\s+=>\s+(/\S+)")


def _run(argv: list[str]) -> str:
    try:
        return subprocess.run(argv, text=True, capture_output=True, timeout=60,
                              check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _scontrol_config(scontrol: str | None) -> dict[str, str]:
    config = {}
    for line in _run([scontrol, "show", "config"]).splitlines() if scontrol else []:
        key, sep, value = line.partition("=")
        if sep:
            config[key.strip()] = value.strip()
    return config


def _shared_libraries(binary: str, names: tuple[str, ...]) -> list[str]:
    found = []
    for line in _run(["ldd", binary]).splitlines():
        match = _LIBRARY_PATTERN.match(line)
        if match and any(match.group(1).startswith(name) for name in names):
            found.append(match.group(2))
    return found


def _account_files(out_dir: Path, extra_users: list[str]) -> list[str]:
    """Host passwd/group plus getent entries for the invoking and Slurm users."""
    out_dir.mkdir(parents=True, exist_ok=True)
    me = pwd.getpwuid(os.getuid()).pw_name
    users = [me, *extra_users, "munge"]
    passwd = Path("/etc/passwd").read_text().splitlines() if Path("/etc/passwd").is_file() else []
    seen = {line.split(":", 1)[0] for line in passwd}
    for user in users:
        entry = _run(["getent", "passwd", user]).strip()
        if entry and entry.split(":", 1)[0] not in seen:
            passwd.append(entry)
            seen.add(entry.split(":", 1)[0])
    group = Path("/etc/group").read_text().splitlines() if Path("/etc/group").is_file() else []
    seen_groups = {line.split(":", 1)[0] for line in group}
    for gid in sorted({os.getgid(), *os.getgroups()}):
        entry = _run(["getent", "group", str(gid)]).strip()
        if entry and entry.split(":", 1)[0] not in seen_groups:
            group.append(entry)
            seen_groups.add(entry.split(":", 1)[0])
    for name in [*extra_users, "munge"]:
        entry = _run(["getent", "group", name]).strip()
        if entry and entry.split(":", 1)[0] not in seen_groups:
            group.append(entry)
            seen_groups.add(entry.split(":", 1)[0])
    (out_dir / "passwd").write_text("\n".join(passwd) + "\n")
    (out_dir / "group").write_text("\n".join(group) + "\n")
    return [f"{out_dir / 'passwd'}:/etc/passwd", f"{out_dir / 'group'}:/etc/group"]


def discover_slurm_binds(out_dir: str) -> list[str]:
    """Return ``--bind`` entries that expose the host's Slurm clients to a SIF."""
    clients = {name: shutil.which(name) for name in CLIENTS}
    if not clients["sbatch"]:
        raise ValueError("sbatch is not on PATH; image mode needs host Slurm clients "
                         "or an explicit container_binds list in the spec")
    binds: list[str] = []

    def add(path: str | None, resolve: bool = True) -> None:
        # Libraries are bound under the soname path ldd reports (for example
        # ``/lib/aarch64-linux-gnu/libmunge.so.2``): the loader inside the
        # image looks for that name, not for the ``.so.2.0.0`` file it links to.
        if path and os.path.exists(path):
            entry = os.path.realpath(path) if resolve else path
            if entry not in binds:
                binds.append(entry)

    for path in clients.values():
        add(path)
    config = _scontrol_config(clients["scontrol"])
    plugin_dirs = [config.get("PluginDir")]
    libraries = _shared_libraries(clients["sbatch"], ("libslurm",))
    plugin_dirs += [str(Path(os.path.realpath(lib)).parent) for lib in libraries]
    for directory in plugin_dirs:
        # The controller may report a plugin path for another architecture;
        # only bind directories that exist on this submission host.
        if directory and os.path.isdir(directory) and (Path(directory) / "auth_munge.so").exists():
            add(directory)
            for lib in _shared_libraries(str(Path(directory) / "auth_munge.so"), ("libmunge",)):
                add(lib, resolve=False)
    for lib in libraries:
        if not any(os.path.realpath(lib).startswith(bound + "/") for bound in binds):
            add(lib, resolve=False)
    conf = config.get("SLURM_CONF") or os.environ.get("SLURM_CONF")
    if conf:
        add(str(Path(conf).parent))
    add("/etc/slurm")
    for socket_dir in ("/run/munge", "/var/run/munge"):
        add(socket_dir)
    slurm_user = re.sub(r"\(.*\)", "", config.get("SlurmUser", "slurm")).strip() or "slurm"
    binds += _account_files(Path(out_dir), [slurm_user])
    return binds
