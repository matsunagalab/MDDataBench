"""Failure and recovery episodes of one attempt, from three kinds of evidence.

A failure is observed at one of three points: an MDClaw tool result with
``success: false`` in the transcript, a DAG node whose status is ``failed``
(MDClaw keeps failed nodes immutable, so a recovery is always a new node), or
a Slurm job that ended in a non-completed state. Recovery is defined as the
same stage succeeding later: a later successful result of the same stage, a
later completed node of the same type, or a later completed job of the same
stage. What was changed between the two is recorded as evidence (argument
differences, diagnostic tools used, branches created); the causal reading is
left to a person.
"""

from __future__ import annotations

import re
import shlex
from collections import Counter
from datetime import datetime
from pathlib import Path

from .attempt_diagnostics import read_record
from .transcript import DIAGNOSTIC_TOOLS, STAGES, USAGE_FIELDS, _command_of, _stage_of

_JOB_STAGE = re.compile(r"^(min|eq|prod|md|equil|minim|production)", re.IGNORECASE)
_JOB_ALIASES = {"md": "prod", "equil": "eq", "minim": "min", "production": "prod"}
TERMINAL_OK = frozenset({"COMPLETED"})
NON_FAILURE = frozenset({"COMPLETED", "RUNNING", "PENDING", None, ""})


def _job_stage(name: str | None) -> str:
    match = _JOB_STAGE.match(name or "")
    if not match:
        return "other"
    stage = match.group(1).lower()
    return _JOB_ALIASES.get(stage, stage)


def _argv(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _argument_diff(before: str, after: str) -> list[str]:
    """Tokens that appear in the retry command but not in the failed one."""
    return [token for token in _argv(after) if token not in set(_argv(before))
            and token.startswith("--")][:20]


def _seconds_between(start: str | None, end: str | None) -> float | None:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def _span_cost(calls: list[dict], start: int, end: int) -> dict:
    """Calls and tokens spent from the failing call up to and including the recovery."""
    window = [call for call in calls if start <= call["index"] <= end]
    totals = Counter()
    for call in window:
        for field in USAGE_FIELDS:
            totals[field] += int((call.get("usage") or {}).get(field) or 0)
    return {"calls": len(window), **{field: totals[field] for field in USAGE_FIELDS},
            "seconds": _seconds_between(next((c.get("at") for c in window if c.get("at")), None),
                                        next((c.get("at") for c in reversed(window) if c.get("at")), None))}


def _means_between(calls: list[dict], results: list[dict], start: int, end: int,
                   failed_command: str, recovered_command: str | None) -> list[str]:
    means = []
    tools = [tool["name"] for call in calls if start < call["index"] <= end
             for tool in call["tool_calls"]]
    mdclaw_tools = [item["tool"] for item in results if start < item["call_index"] <= end]
    if any(tool in DIAGNOSTIC_TOOLS for tool in mdclaw_tools):
        means.append("diagnostic_tool")
    if "create_node" in mdclaw_tools:
        means.append("new_node")
    if any(tool in {"read", "Read", "view"} for tool in tools):
        means.append("read_documentation")
    if recovered_command and _argument_diff(failed_command, recovered_command):
        means.append("argument_change")
    return means


def tool_episodes(calls: list[dict], results: list[dict], exit_reason: str | None) -> list[dict]:
    episodes = []
    for position, item in enumerate(results):
        if item["success"]:
            continue
        stage = item["stage"]
        # A meta tool (create_node, trace_failure, ...) recovers only when the
        # same tool later succeeds; a stage recovers when any of its tools does.
        recovery = next((later for later in results[position + 1:]
                         if later["success"] and later["stage"] == stage
                         and (stage != "meta" or later["tool"] == item["tool"])), None)
        end = recovery["call_index"] if recovery else (calls[-1]["index"] if calls else item["call_index"])
        episode = {"kind": "tool", "stage": stage, "tool": item["tool"], "node_id": item["node_id"],
                   "code": item.get("code") or "unspecified", "message": item.get("message"),
                   "start_call": item["call_index"], "end_call": end,
                   "cost": _span_cost(calls, item["call_index"], end),
                   "means": _means_between(calls, results, item["call_index"], end,
                                           item.get("command") or "",
                                           recovery.get("command") if recovery else None),
                   "argument_changes": (_argument_diff(item.get("command") or "",
                                                       recovery.get("command") or "")
                                        if recovery else []),
                   "outcome": ("recovered" if recovery else
                               "timed_out" if exit_reason == "timeout" else "abandoned")}
        episodes.append(episode)
    return episodes


def node_episodes(job_dir: Path, exit_reason: str | None) -> list[dict]:
    nodes = []
    for path in sorted(Path(job_dir).glob("nodes/*/node.json")):
        node = read_record(path)
        if node:
            nodes.append({"node_id": node.get("node_id", path.parent.name),
                          "node_type": node.get("node_type") or node.get("type"),
                          "status": node.get("status"), "created_at": node.get("created_at"),
                          "updated_at": node.get("updated_at"),
                          "code": (node.get("metadata") or {}).get("failure_code"),
                          "errors": (node.get("metadata") or {}).get("errors", [])})
    nodes.sort(key=lambda n: n.get("created_at") or "")
    episodes = []
    for position, node in enumerate(nodes):
        if node["status"] != "failed":
            continue
        later = next((n for n in nodes[position + 1:]
                      if n["node_type"] == node["node_type"] and n["status"] == "completed"), None)
        episodes.append({"kind": "node", "stage": node["node_type"], "node_id": node["node_id"],
                         "code": node.get("code") or "node_failed",
                         "message": "; ".join(map(str, node.get("errors") or []))[:300],
                         "recovered_node_id": later["node_id"] if later else None,
                         "cost": {"seconds": _seconds_between(node.get("updated_at"),
                                                              (later or {}).get("updated_at"))},
                         "means": ["new_node"] if later else [],
                         "outcome": ("recovered" if later else
                                     "timed_out" if exit_reason == "timeout" else "abandoned")})
    return episodes


def job_episodes(md_jobs: list[dict], exit_reason: str | None) -> list[dict]:
    jobs = sorted((job for job in md_jobs if job.get("job_id")),
                  key=lambda job: job.get("submitted_at") or "")
    episodes = []
    for position, job in enumerate(jobs):
        if job.get("state") in NON_FAILURE:
            continue
        stage = _job_stage(job.get("job_name"))
        later = next((j for j in jobs[position + 1:]
                      if _job_stage(j.get("job_name")) == stage and j.get("state") in TERMINAL_OK), None)
        episodes.append({"kind": "job", "stage": stage, "job_id": str(job["job_id"]),
                         "code": job.get("state"), "recovered_job_id": (later or {}).get("job_id"),
                         "cost": {"seconds": _seconds_between(job.get("ended_at"),
                                                              (later or {}).get("ended_at"))},
                         "means": ["resubmission"] if later else [],
                         "outcome": ("recovered" if later else
                                     "timed_out" if exit_reason == "timeout" else "abandoned")})
    return episodes


def recovery_report(calls: list[dict], results: list[dict], job_dir: Path | None,
                    md_jobs: list[dict], exit_reason: str | None) -> dict:
    """Episodes from every evidence kind plus per-attempt counts."""
    episodes = tool_episodes(calls, results, exit_reason)
    if job_dir and Path(job_dir).is_dir():
        episodes += node_episodes(Path(job_dir), exit_reason)
    episodes += job_episodes(md_jobs or [], exit_reason)
    outcomes = Counter(e["outcome"] for e in episodes)
    diagnostic_calls = sum(1 for item in results if item["tool"] in DIAGNOSTIC_TOOLS)
    return {"schema_version": 1, "episodes": episodes,
            "counts": {"episodes": len(episodes), **{k: outcomes.get(k, 0) for k in
                                                       ("recovered", "abandoned", "timed_out")},
                       "tool": sum(e["kind"] == "tool" for e in episodes),
                       "node": sum(e["kind"] == "node" for e in episodes),
                       "job": sum(e["kind"] == "job" for e in episodes)},
            "failure_free": not episodes,
            "diagnostic_tool_calls": diagnostic_calls,
            "stages_failed": sorted({e["stage"] for e in episodes}, key=lambda s: (
                STAGES.index(s) if s in STAGES else len(STAGES)))}


def stage_of_tool(tool: str | None, node_id: str | None) -> str:
    return _stage_of(tool, node_id)


__all__ = ["recovery_report", "tool_episodes", "node_episodes", "job_episodes",
           "stage_of_tool", "_command_of"]
