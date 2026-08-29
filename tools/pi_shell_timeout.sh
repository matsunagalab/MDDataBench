#!/bin/bash
# Per-command watchdog for the pi agent, scoped to benchmark runs.
#
# pi resolves its shell through settings.json `shellPath` and invokes it as
#   <shellPath> -c "<command>"
# (pi-coding-agent dist/utils/shell.js: getShellConfig -> getBashShellConfig).
# Pointing shellPath here therefore caps every command the agent runs.
#
# settings.json is global, but the cap is not: only commands whose working
# directory is inside an MDDataBench (or legacy MDPrepBench) run are wrapped. Every other pi
# session on this machine gets a plain /bin/bash, one extra exec deep.
#
# Why: in the 2026-08-14 pass^k rep1, four of forty tasks each burned 42-55
# minutes of a 60-minute budget inside ONE environment-probing command — a
# recursive grep over benchmark_runs, `which tleap; ls /opt/anaconda3/...`, a
# host-venv openmm probe. That is 4.0 h of the run's 11.7 h. pass^k scores a
# timeout as a task failure, so without a watchdog the run measures the absence
# of one rather than the model's ability.
#
# 600 s default: the longest legitimate command in the July 40-task reference run
# was 257.7 s (p99 = 63 s), so this leaves >2x headroom over anything real while
# cutting a 55-minute hang to 10 minutes. The agent sees exit 124 plus whatever
# output was produced, and can recover instead of losing the task.
#
# No --foreground: GNU timeout then puts the command in its own process group and
# signals the whole group, so forked pipeline children and backgrounded jobs die
# with it. Verified with marker files — no orphans.

case "${PWD}" in
    */MDPrepBench/benchmark_runs/*|*/MDDataBench/outputs/runs/*)
        exec timeout --kill-after=15 "${PI_CMD_TIMEOUT_SECONDS:-600}" /bin/bash "$@"
        ;;
esac
exec /bin/bash "$@"
