"""Token accounting, MDClaw results and recovery episodes from harness transcripts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mddatabench import recovery, transcript as t


def pi_usage(inp, out, read=0, reasoning=0):
    return {"input": inp, "output": out, "cacheRead": read, "cacheWrite": 0,
            "reasoning": reasoning, "totalTokens": inp + out + read,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}


def pi_assistant(ts, usage, tool_calls=(), text=None):
    content = [{"type": "text", "text": text}] if text else []
    content += [{"type": "toolCall", "id": cid, "name": "bash", "arguments": {"command": cmd}}
                for cid, cmd in tool_calls]
    message = {"role": "assistant", "content": content, "usage": usage, "timestamp": ts,
               "stopReason": "toolUse" if tool_calls else "stop"}
    # pi streams the same message through message_start/update/end and turn_end.
    return [{"type": "message_start", "message": message},
            {"type": "message_update", "message": message, "usage": usage},
            {"type": "message_end", "message": message},
            {"type": "turn_end", "message": message, "toolResults": []}]


def pi_tool_end(cid, text, is_error=False):
    return [{"type": "tool_execution_end", "toolCallId": cid, "toolName": "bash",
             "result": {"content": [{"type": "text", "text": text}]}, "isError": is_error}]


MDCLAW = "singularity exec --env PYTHONPATH= /images/mdclaw.sif mdclaw"
SKILL = "/home/me/.pi/agent/git/github.com/matsunagalab/mdclaw/skills/md-prepare/SKILL.md"


def write_pi_transcript(path: Path, with_usage=True, timeout=False):
    u = (lambda i, o, r=0, re=0: pi_usage(i, o, r, re)) if with_usage else (lambda *a: pi_usage(0, 0))
    rows = []
    rows += pi_assistant(1_000, u(100, 10), [("bash:0", f"cat {SKILL}")])
    rows += pi_tool_end("bash:0", "# md-prepare\n" + "x" * 500)
    rows += pi_assistant(11_000, u(50, 20, 600, 5), [("bash:1", f"{MDCLAW} --job-dir study/jobs/main --node-id prep_001 prepare_complex --chains A")])
    rows += pi_tool_end("bash:1", json.dumps({"success": False, "code": "unknown_forcefield",
                                                "message": "ff99 is not supported"}), True)
    rows += pi_assistant(21_000, u(40, 30, 700, 10), [("bash:2", f"{MDCLAW} --job-dir study/jobs/main --node-id prep_001 trace_failure")])
    rows += pi_tool_end("bash:2", json.dumps({"success": True, "recovery_options": []}))
    rows += pi_assistant(31_000, u(30, 40, 800), [("bash:3", f"{MDCLAW} --job-dir study/jobs/main --node-id prep_002 prepare_complex --chains A --forcefield ff14SB")])
    rows += pi_tool_end("bash:3", "logs...\n" + json.dumps({"success": True, "node_id": "prep_002"}))
    rows += pi_assistant(41_000, u(20, 50, 900), [("bash:4", f"{MDCLAW} --job-dir study/jobs/main --node-id solv_001 solvate_structure > $TMPDIR/out.json")])
    rows += pi_tool_end("bash:4", "")
    if not timeout:
        rows += pi_assistant(51_000, u(10, 60, 1000), text="Submitted.")
    rows.append({"type": "agent_end", "messages": [{"role": "assistant", "usage": u(999, 999)}]})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_pi_calls_are_one_per_assistant_message_with_results_attached(tmp_path):
    path = tmp_path / "agent.stdout.jsonl"
    write_pi_transcript(path)
    calls = t.iter_calls(path, "pi")
    assert [c["index"] for c in calls] == [0, 1, 2, 3, 4, 5]
    assert calls[0]["at"].startswith("1970-01-01T00:00:01")
    assert calls[1]["usage"] == {"prompt_uncached": 50, "cache_read": 600, "cache_write": 0,
                                 "prompt_total": 650, "output": 20, "reasoning": 5}
    assert calls[1]["tool_results"][0]["is_error"] is True
    assert calls[5]["tool_calls"] == [] and calls[5]["stop_reason"] == "stop"


def test_token_totals_ignore_repeated_records_and_flag_zero_usage(tmp_path):
    path = tmp_path / "agent.stdout.jsonl"
    write_pi_transcript(path)
    usage = t.token_usage(t.iter_calls(path, "pi"))
    assert usage["calls"] == 6 and usage["calls_with_usage"] == 6
    assert usage["prompt_uncached"] == 250 and usage["cache_read"] == 4000
    assert usage["prompt_total"] == 4250 and usage["output"] == 210 and usage["reasoning"] == 15
    assert usage["input_tokens"] == 4250 and usage["provenance"] == "transcript"
    write_pi_transcript(path, with_usage=False)
    zero = t.token_usage(t.iter_calls(path, "pi"))
    assert zero["calls"] == 6 and zero["calls_with_usage"] == 0
    assert zero["prompt_total"] is None and zero["provenance"] == "unavailable"


def test_mdclaw_results_invocations_and_skill_reads(tmp_path):
    path = tmp_path / "agent.stdout.jsonl"
    write_pi_transcript(path)
    calls = t.iter_calls(path, "pi")
    results = t.mdclaw_results(calls)
    assert [(r["tool"], r["stage"], r["node_id"], r["success"], r["code"]) for r in results] == [
        ("prepare_complex", "prep", "prep_001", False, "unknown_forcefield"),
        ("trace_failure", "meta", "prep_001", True, None),
        ("prepare_complex", "prep", "prep_002", True, None)]
    assert t.error_codes(results) == {"unknown_forcefield": 1}
    invocations = t.mdclaw_invocations(calls)
    assert [(i["tool"], i["stage"]) for i in invocations][-1] == ("solvate_structure", "solv")
    assert len(invocations) == 4     # the redirected solvate call is still an invocation
    reads = t.skill_reads(calls, ["/home/me/.pi/agent/git/github.com/matsunagalab/mdclaw/skills"])
    assert reads == {"reads": 1, "chars": 513}
    rows = t.timeline(calls, results, [])
    assert [r["stage"] for r in rows] == ["skill_read", "prep", "meta", "prep", "solv", "text"]
    assert rows[-1]["cumulative"]["prompt_total"] == 4250
    assert rows[1]["elapsed_seconds"] == 10.0


def test_recovery_episode_links_failure_to_the_next_success_of_the_stage(tmp_path):
    path = tmp_path / "agent.stdout.jsonl"
    write_pi_transcript(path)
    calls = t.iter_calls(path, "pi")
    report = recovery.recovery_report(calls, t.mdclaw_results(calls), None, [], "completed")
    assert report["counts"] == {"episodes": 1, "recovered": 1, "abandoned": 0, "timed_out": 0,
                                "tool": 1, "node": 0, "job": 0}
    episode = report["episodes"][0]
    assert episode["stage"] == "prep" and episode["code"] == "unknown_forcefield"
    assert episode["start_call"] == 1 and episode["end_call"] == 3
    assert episode["cost"]["calls"] == 3 and episode["cost"]["prompt_total"] == 650 + 740 + 830
    assert episode["cost"]["seconds"] == 20.0
    assert set(episode["means"]) == {"diagnostic_tool", "argument_change"}
    assert episode["argument_changes"] == ["--forcefield"]
    assert report["failure_free"] is False and report["diagnostic_tool_calls"] == 1


def test_unrecovered_failures_are_timed_out_or_abandoned(tmp_path):
    path = tmp_path / "agent.stdout.jsonl"
    rows = pi_assistant(1_000, pi_usage(10, 5), [("bash:0", f"{MDCLAW} --node-id topo_001 build_amber_system")])
    rows += pi_tool_end("bash:0", json.dumps({"success": False, "code": "forcefield_water_blocked"}), True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    calls = t.iter_calls(path, "pi")
    for exit_reason, outcome in (("timeout", "timed_out"), ("completed", "abandoned")):
        report = recovery.recovery_report(calls, t.mdclaw_results(calls), None, [], exit_reason)
        assert report["episodes"][0]["outcome"] == outcome


def test_node_and_job_episodes_from_dag_and_scheduler_evidence(tmp_path):
    job_dir = tmp_path / "study/jobs/main"
    for node_id, node_type, status, created in (("solv_001", "solv", "failed", "2026-09-09T10:00:00"),
                                                ("solv_002", "solv", "completed", "2026-09-09T10:05:00"),
                                                ("topo_001", "topo", "failed", "2026-09-09T10:10:00")):
        (job_dir / "nodes" / node_id).mkdir(parents=True)
        (job_dir / "nodes" / node_id / "node.json").write_text(json.dumps({
            "node_id": node_id, "node_type": node_type, "status": status, "created_at": created,
            "updated_at": created, "metadata": {"failure_code": "node_execution_context_invalid"}
            if status == "failed" else {}}))
    jobs = [{"job_id": "1", "job_name": "min_x", "state": "COMPLETED", "submitted_at": "a", "ended_at": "2026-09-09T11:00:00"},
            {"job_id": "2", "job_name": "eq_x", "state": "FAILED", "submitted_at": "b", "ended_at": "2026-09-09T11:10:00"},
            {"job_id": "3", "job_name": "eq_x_retry", "state": "COMPLETED", "submitted_at": "c", "ended_at": "2026-09-09T11:30:00"}]
    report = recovery.recovery_report([], [], job_dir, jobs, "completed")
    kinds = {(e["kind"], e["stage"], e["outcome"]) for e in report["episodes"]}
    assert kinds == {("node", "solv", "recovered"), ("node", "topo", "abandoned"),
                     ("job", "eq", "recovered")}
    job = next(e for e in report["episodes"] if e["kind"] == "job")
    assert job["recovered_job_id"] == "3" and job["cost"]["seconds"] == 1200.0
    assert report["stages_failed"] == ["solv", "topo", "eq"]


def test_claude_stream_json_merges_blocks_and_prefers_the_session_total(tmp_path):
    path = tmp_path / "claude.jsonl"
    usage1 = {"input_tokens": 2, "cache_creation_input_tokens": 10070,
              "cache_read_input_tokens": 18531, "output_tokens": 17}
    rows = [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"id": "msg_1", "usage": usage1, "content": [
            {"type": "text", "text": "Running."}]}},
        {"type": "assistant", "message": {"id": "msg_1", "usage": usage1, "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "echo hello"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "hello", "is_error": False}]}},
        {"type": "assistant", "message": {"id": "msg_2", "usage": {
            "input_tokens": 2, "cache_creation_input_tokens": 694, "cache_read_input_tokens": 28601,
            "output_tokens": 1}, "content": [{"type": "text", "text": "OK"}]}},
        {"type": "result", "usage": {"input_tokens": 4, "cache_creation_input_tokens": 10764,
                                     "cache_read_input_tokens": 47132, "output_tokens": 82,
                                     "output_tokens_details": {"thinking_tokens": 3}}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    calls = t.iter_calls(path, "claude-code")
    assert len(calls) == 2 and calls[0]["tool_calls"][0]["name"] == "Bash"
    assert calls[0]["tool_results"][0]["text"] == "hello"
    usage = t.token_usage(calls)
    assert usage["provenance"] == "transcript_total"
    assert (usage["prompt_uncached"], usage["cache_read"], usage["cache_write"], usage["output"],
            usage["reasoning"]) == (4, 47132, 10764, 82, 3)


def test_codex_turn_usage_separates_cached_input(tmp_path):
    path = tmp_path / "codex.jsonl"
    rows = [
        {"type": "thread.started", "thread_id": "x"},
        {"type": "item.completed", "item": {"id": "item_2", "type": "command_execution",
                                             "command": "/usr/bin/bash -lc 'echo hello'",
                                             "aggregated_output": "hello\n", "exit_code": 0}},
        {"type": "item.completed", "item": {"id": "item_3", "type": "agent_message", "text": "OK"}},
        {"type": "turn.completed", "usage": {"input_tokens": 31758, "cached_input_tokens": 15744,
                                             "cache_write_input_tokens": 0, "output_tokens": 46,
                                             "reasoning_output_tokens": 7}},
        {"id": "1", "msg": {"type": "exec_command_end", "call_id": "c9", "command": ["bash", "-lc", "false"],
                            "aggregated_output": "", "exit_code": 1}},
        {"id": "2", "msg": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 99999}, "last_token_usage": {
                "input_tokens": 1000, "cached_input_tokens": 900, "output_tokens": 10}}}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    calls = t.iter_calls(path, "codex")
    assert len(calls) == 2
    assert calls[0]["usage"] == {"prompt_uncached": 16014, "cache_read": 15744, "cache_write": 0,
                                 "prompt_total": 31758, "output": 46, "reasoning": 7}
    assert calls[1]["tool_results"][0]["is_error"] is True
    assert t.token_usage(calls)["prompt_uncached"] == 16014 + 100


def test_unknown_harness_is_refused():
    with pytest.raises(ValueError, match="no transcript parser"):
        t.iter_calls("x.jsonl", "gemini")
