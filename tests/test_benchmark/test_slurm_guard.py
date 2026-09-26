"""A sandboxed attempt's Slurm clients reach its own jobs and nothing else."""

from __future__ import annotations

import json
import stat

import pytest

from mddatabench import slurm_guard as sg


@pytest.fixture
def cluster(tmp_path, monkeypatch):
    """Fake real clients that log their argv; squeue/sacct answer ownership queries."""
    attempt = tmp_path / "exp" / "attempts" / "001_t" / "cli_sif__r1"
    events = attempt / "workspace" / ".mddatabench" / "sbatch-events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(json.dumps({"job_id": "100"}) + "\n")
    (attempt / "manifest.json").write_text("{}")
    real = tmp_path / "real"
    real.mkdir()
    log = tmp_path / "calls.log"
    queue = f"100|{attempt}/workspace\n101_2|{attempt}/workspace/study\n900|/data1/other/t1r\n"
    for tool in sg.GUARDED + ("sbatch",):
        script = real / tool
        script.write_text(
            "#!/bin/sh\n"
            f'echo "{tool} $*" >> {log}\n'
            f'case "$*" in *"%i|%Z"*) printf "{queue}" ;; '
            f'*"JobIDRaw,WorkDir"*) printf "100|{attempt}/workspace\\n900|/data1/other/t1r\\n" ;; esac\n')
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(sg, "REAL_DIR", str(real))
    monkeypatch.setenv("MDDATABENCH_MANIFEST", str(attempt / "manifest.json"))
    monkeypatch.setenv("MDDATABENCH_EVENT_LOG", str(events))
    return log


def calls(log):
    return [line.split(" ", 1) for line in log.read_text().splitlines()] if log.exists() else []


def last(log, tool):
    return next(args for name, args in reversed(calls(log)) if name == tool)


def test_the_incident_command_now_reaches_only_the_attempts_jobs(cluster):
    """scancel $(squeue -u $USER -h -o '%i') cancelled every job of the owner."""
    assert sg.main(["squeue", "-u", "someone", "-h", "-o", "%i"]) == 0
    assert last(cluster, "squeue").endswith("--jobs=100,101")
    assert sg.main(["scancel", "100", "101_2"]) == 0
    assert last(cluster, "scancel") == "100 101_2"


@pytest.mark.parametrize("selector", [["-u", "rku"], ["--user=rku"], ["--me"], ["-n", "prod"],
                                      ["--name=prod"], ["-p", "gpu"], ["--state=PENDING"],
                                      ["-t", "R"], ["-A", "rkp00079"], ["-urku"], ["-w", "c154"]])
def test_scancel_refuses_to_select_jobs_by_anything_but_id(cluster, selector, capsys):
    assert sg.main(["scancel", *selector]) == 1
    assert not any(name == "scancel" for name, _ in calls(cluster))
    assert "own jobs" in capsys.readouterr().err


def test_scancel_cancels_own_jobs_and_refuses_the_others(cluster, capsys):
    assert sg.main(["scancel", "-s", "KILL", "100", "900"]) == 1
    assert last(cluster, "scancel") == "-s KILL 100"
    assert "900 is not a job of this benchmark attempt" in capsys.readouterr().err
    assert sg.main(["scancel", "900"]) == 1
    assert last(cluster, "scancel") == "-s KILL 100"  # nothing new was cancelled


def test_a_job_run_inside_the_attempt_counts_even_if_the_shim_did_not_record_it(cluster):
    assert sg.main(["scancel", "101"]) == 0
    assert last(cluster, "scancel") == "101"


def test_listings_show_only_the_attempts_jobs(cluster):
    sg.main(["squeue", "-j", "900,100"])
    assert last(cluster, "squeue").endswith("--jobs=100")
    sg.main(["squeue", "-j", "900"])
    assert last(cluster, "squeue").endswith(sg._NO_MATCH)
    sg.main(["sacct", "-X", "-o", "JobID,State"])
    assert last(cluster, "sacct").endswith("--jobs=100")


def test_scontrol_shows_the_cluster_and_only_own_jobs(cluster, capsys):
    assert sg.main(["scontrol", "show", "partition"]) == 0
    assert sg.main(["scontrol", "show", "job", "100"]) == 0
    assert sg.main(["scontrol", "show", "job", "900"]) == 1
    assert "not a job of this benchmark attempt" in capsys.readouterr().err
    sg.main(["scontrol", "show", "jobs"])
    shown = [args for name, args in calls(cluster) if name == "scontrol"]
    assert shown[-2:] == ["show jobs 100", "show jobs 101"]


def test_scontrol_changes_only_own_jobs(cluster):
    assert sg.main(["scontrol", "hold", "100"]) == 0
    assert sg.main(["scontrol", "hold", "900"]) == 1
    assert sg.main(["scontrol", "update", "JobId=100", "TimeLimit=10"]) == 0
    assert sg.main(["scontrol", "update", "JobId=900", "TimeLimit=10"]) == 1
    assert sg.main(["scontrol", "update", "NodeName=c154", "State=DRAIN"]) == 1
    assert sg.main(["scontrol", "shutdown"]) == 1


@pytest.mark.parametrize("tool", ["srun", "salloc", "sattach", "scrontab", "strigger"])
def test_allocation_and_scheduling_clients_are_refused(cluster, tool, capsys):
    assert sg.main([tool, "hostname"]) == 1
    assert "not available in a benchmark attempt" in capsys.readouterr().err
    assert not any(name == tool for name, _ in calls(cluster))


def test_without_an_attempt_nothing_is_owned(cluster, monkeypatch):
    monkeypatch.delenv("MDDATABENCH_MANIFEST")
    monkeypatch.delenv("MDDATABENCH_EVENT_LOG")
    assert sg.main(["scancel", "100"]) == 1
    sg.main(["squeue"])
    assert last(cluster, "squeue").endswith(sg._NO_MATCH)


def test_squeue_noheader_is_not_mistaken_for_help(cluster):
    """`squeue -h` is --noheader; passing it through unfiltered was the incident itself."""
    sg.main(["squeue", "-h"])
    assert last(cluster, "squeue") == "-h --jobs=100,101"
    sg.main(["squeue", "--help"])
    assert last(cluster, "squeue") == "--help"
