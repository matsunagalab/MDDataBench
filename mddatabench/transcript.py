"""One record per model call, whatever harness wrote the transcript.

The campaign runner captures each harness's own JSON stream. Those streams
repeat usage many times (pi writes the same usage in message_start, every
message_update, message_end and again in turn_end and agent_end; Claude Code
repeats a message per content block and ends with a cumulative result; Codex
reports a turn total), so token accounting must first decide what one model
call is. This module does that and nothing else: it returns calls with their
usage, tool calls and tool results, and derives token totals, skill reads,
MDClaw results and a timeline from them. Scores are never touched.

Usage fields are normalised to the provider's own accounting:

- ``prompt_uncached``: prompt tokens the provider charged as new computation
- ``cache_read``: prompt tokens served from a prompt/KV cache
- ``cache_write``: prompt tokens written to a cache (Anthropic, OpenAI)
- ``prompt_total``: ``prompt_uncached + cache_read + cache_write``
- ``output``: completion tokens, including reasoning
- ``reasoning``: the reasoning share of ``output`` when reported
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

USAGE_FIELDS = ("prompt_uncached", "cache_read", "cache_write", "prompt_total", "output",
                "reasoning")

# MDClaw tool -> DAG stage. Node ids carry the stage as a prefix (prep_001);
# tools without a node fall back to this map.
TOOL_STAGES = {
    "fetch_structure": "source", "download_structure": "source", "register_source": "source",
    "bootstrap_md_workflow": "source", "list_source_candidates": "source",
    "prepare_complex": "prep", "prepare_structure": "prep", "select_chains": "prep",
    "clean_structure": "prep", "inspect_structure": "prep", "inspect_chains": "prep",
    "solvate_structure": "solv", "embed_in_membrane": "solv",
    "build_amber_system": "topo", "build_openmm_system": "topo",
    "run_minimization": "min", "run_equilibration": "eq", "run_production": "prod",
    "submit_job": "submission", "submit_array_job": "submission",
    "check_job": "submission", "cancel_job": "submission",
}
STAGES = ("source", "prep", "solv", "topo", "min", "eq", "prod", "submission")
DIAGNOSTIC_TOOLS = frozenset({"trace_failure", "inspect_job", "explain_node", "check_job_log",
                              "inspect_cluster", "list_source_candidates"})
# DAG bookkeeping and diagnosis: these carry a node id but do no stage work,
# so their success must not count as recovering that stage.
META_TOOLS = DIAGNOSTIC_TOOLS | frozenset({"create_node", "show_policy", "set_policy",
                                           "configure_container", "list_tracked_jobs",
                                           "list_jobs", "complete_node"})
_MDCLAW_TOOL = re.compile(
    r"(?:\bmdclaw|\$\{?M\}?|\$MDCLAW)\s+((?:--[\w-]+(?:[= ]\S+)?\s+)*)([a-z][a-z0-9_]+)")
_NODE_ID = re.compile(r"--node-id[= ]+(\S+)")
_JOB_DIR = re.compile(r"--job-dir[= ]+(\S+)")


def _iso(milliseconds) -> str | None:
    try:
        return datetime.fromtimestamp(float(milliseconds) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_text(item) for item in content)
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if "content" in content:
            return _text(content["content"])
    return ""


def _usage(prompt_uncached=0, cache_read=0, cache_write=0, output=0, reasoning=0) -> dict:
    values = {"prompt_uncached": int(prompt_uncached or 0), "cache_read": int(cache_read or 0),
              "cache_write": int(cache_write or 0), "output": int(output or 0),
              "reasoning": int(reasoning or 0)}
    values["prompt_total"] = values["prompt_uncached"] + values["cache_read"] + values["cache_write"]
    return values


def _call(index: int, at: str | None, usage: dict | None, stop_reason=None) -> dict:
    return {"index": index, "at": at, "usage": usage, "stop_reason": stop_reason,
            "tool_calls": [], "tool_results": []}


def _read_lines(path: Path):
    for line in path.read_text(errors="replace").splitlines() if path.exists() else []:
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


# ---- pi ---------------------------------------------------------------------

def _pi_usage(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    usage = _usage(raw.get("input"), raw.get("cacheRead"), raw.get("cacheWrite"),
                   raw.get("output"), raw.get("reasoning"))
    # A provider that pi was told not to ask for usage leaves every field at
    # zero (the Rikyu endpoint until 2026-09-09); that is missing, not free.
    return usage if usage["prompt_total"] or usage["output"] else None


def _pi_calls(path: Path) -> list[dict]:
    calls, by_tool_id = [], {}
    for row in _read_lines(path):
        kind = row.get("type")
        if kind == "message_end":
            message = row.get("message") or {}
            if message.get("role") != "assistant":
                continue
            call = _call(len(calls), _iso(message.get("timestamp")), _pi_usage(message.get("usage")),
                         message.get("stopReason"))
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "toolCall":
                    tool = {"id": block.get("id"), "name": block.get("name"),
                            "arguments": block.get("arguments") or {}}
                    call["tool_calls"].append(tool)
                    by_tool_id[tool["id"]] = call
            calls.append(call)
        elif kind == "tool_execution_end":
            call = by_tool_id.get(row.get("toolCallId"))
            if call is not None:
                call["tool_results"].append({"id": row.get("toolCallId"), "name": row.get("toolName"),
                                             "text": _text(row.get("result")),
                                             "is_error": bool(row.get("isError"))})
    return calls


# ---- Claude Code --------------------------------------------------------------

def _claude_usage(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    details = raw.get("output_tokens_details") or {}
    return _usage(raw.get("input_tokens"), raw.get("cache_read_input_tokens"),
                  raw.get("cache_creation_input_tokens"), raw.get("output_tokens"),
                  details.get("thinking_tokens"))


def _claude_calls(path: Path) -> list[dict]:
    calls, by_message_id, by_tool_id = [], {}, {}
    for row in _read_lines(path):
        kind, message = row.get("type"), row.get("message") or {}
        if kind == "result" and isinstance(row.get("usage"), dict) and calls:
            # The per-message output_tokens in stream-json are partial counts
            # taken while streaming (measured 2026-09-10: 17 + 1 against a
            # final 82). The result event carries the session total; keep it
            # on the last call as the authoritative session figure.
            calls[-1]["session_usage"] = _claude_usage(row["usage"])
            continue
        if kind == "assistant":
            # stream-json repeats one API message per content block; the id
            # is the API message id, so merge on it and keep one usage.
            key = message.get("id") or f"anonymous:{len(calls)}"
            call = by_message_id.get(key)
            if call is None:
                call = _call(len(calls), None, _claude_usage(message.get("usage")),
                             message.get("stop_reason"))
                by_message_id[key] = call
                calls.append(call)
            elif message.get("usage"):
                call["usage"] = _claude_usage(message.get("usage"))
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool = {"id": block.get("id"), "name": block.get("name"),
                            "arguments": block.get("input") or {}}
                    if tool["id"] not in by_tool_id:
                        call["tool_calls"].append(tool)
                        by_tool_id[tool["id"]] = call
        elif kind == "user":
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    call = by_tool_id.get(block.get("tool_use_id"))
                    if call is not None:
                        call["tool_results"].append({"id": block.get("tool_use_id"), "name": None,
                                                     "text": _text(block.get("content")),
                                                     "is_error": bool(block.get("is_error"))})
    for call in calls:
        for result in call["tool_results"]:
            names = {tool["id"]: tool["name"] for tool in call["tool_calls"]}
            result["name"] = names.get(result["id"])
    return calls


# ---- Codex --------------------------------------------------------------------

def _codex_usage(raw: dict | None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    total_input = int(raw.get("input_tokens") or 0)
    cached = int(raw.get("cached_input_tokens") or raw.get("cached_tokens") or 0)
    written = int(raw.get("cache_write_input_tokens") or 0)
    # OpenAI counts cached tokens inside input_tokens.
    return _usage(max(0, total_input - cached - written), cached, written,
                  raw.get("output_tokens"), raw.get("reasoning_output_tokens"))


def _codex_calls(path: Path) -> list[dict]:
    calls, current = [], None

    def open_call():
        nonlocal current
        if current is None:
            current = _call(len(calls), None, None)
            calls.append(current)
        return current

    for row in _read_lines(path):
        kind = row.get("type") or (row.get("msg") or {}).get("type")
        payload = row.get("msg") or row
        if kind in {"item.completed", "exec_command_end"}:
            item = payload.get("item") or payload
            if item.get("type") in {None, "command_execution", "exec_command_end"} and (
                    item.get("command") is not None):
                call = open_call()
                command = item.get("command")
                if isinstance(command, list):
                    command = " ".join(map(str, command))
                identifier = item.get("id") or item.get("call_id")
                call["tool_calls"].append({"id": identifier, "name": "command_execution",
                                           "arguments": {"command": command}})
                call["tool_results"].append({"id": identifier, "name": "command_execution",
                                             "text": _text(item.get("aggregated_output")
                                                           or item.get("stdout") or ""),
                                             "is_error": str(item.get("exit_code", "0")) not in {"0", "None"}})
        elif kind == "turn.completed":
            call = open_call()
            call["usage"] = _codex_usage(payload.get("usage"))
            current = None
        elif kind == "token_count":
            info = payload.get("info") or {}
            last = info.get("last_token_usage")
            if last:
                call = open_call()
                call["usage"] = _codex_usage(last)
                current = None
    return calls


PARSERS = {"pi": _pi_calls, "claude-code": _claude_calls, "claude": _claude_calls,
           "codex": _codex_calls}


def iter_calls(path: str | Path, harness: str) -> list[dict]:
    """Model calls of one attempt transcript, in order, with usage and tools."""
    parser = PARSERS.get(harness)
    if parser is None:
        raise ValueError(f"no transcript parser for harness {harness!r}")
    return parser(Path(path))


# ---- derived views ------------------------------------------------------------

def token_usage(calls: list[dict]) -> dict:
    """Per-attempt totals over calls that carry usage; missing calls are counted."""
    totals = Counter()
    with_usage = 0
    for call in calls:
        if call.get("usage"):
            with_usage += 1
            for field in USAGE_FIELDS:
                totals[field] += int(call["usage"].get(field) or 0)
    provenance = "transcript" if with_usage else "unavailable"
    session = next((call["session_usage"] for call in reversed(calls)
                    if call.get("session_usage")), None)
    if session:
        totals, with_usage, provenance = Counter(session), max(with_usage, 1), "transcript_total"
    return {"calls": len(calls), "calls_with_usage": with_usage,
            "calls_without_usage": len(calls) - with_usage,
            **{field: (totals[field] if with_usage else None) for field in USAGE_FIELDS},
            "provenance": provenance,
            # Compatibility with the schema-2 columns.
            "input_tokens": totals["prompt_total"] if with_usage else None,
            "output_tokens": totals["output"] if with_usage else None,
            "reasoning_tokens": totals["reasoning"] if with_usage else None}


def _command_of(tool: dict) -> str:
    arguments = tool.get("arguments") or {}
    for key in ("command", "cmd"):
        if isinstance(arguments.get(key), str):
            return arguments[key]
    if isinstance(arguments.get("command"), list):
        return " ".join(map(str, arguments["command"]))
    return ""


def _path_of(tool: dict) -> str:
    arguments = tool.get("arguments") or {}
    for key in ("path", "file_path", "filePath", "file"):
        if isinstance(arguments.get(key), str):
            return arguments[key]
    return ""


def skill_reads(calls: list[dict], skill_roots: list[str] = ()) -> dict:
    """How much of the transcript went into reading skill pages."""
    roots = [str(Path(root).resolve()) for root in skill_roots if root]

    def is_skill(path: str) -> bool:
        if not path:
            return False
        resolved = str(Path(path).resolve()) if path.startswith("/") else path
        return any(resolved.startswith(root + "/") for root in roots) or \
            "/skills/" in resolved or resolved.endswith("SKILL.md")

    reads, chars = 0, 0
    for call in calls:
        results = {result["id"]: result for result in call["tool_results"]}
        for tool in call["tool_calls"]:
            path = _path_of(tool)
            command = _command_of(tool)
            hit = is_skill(path) or any(is_skill(token) for token in command.split()
                                        if "/skills/" in token or token.endswith("SKILL.md"))
            if hit:
                reads += 1
                chars += len((results.get(tool["id"]) or {}).get("text") or "")
    return {"reads": reads, "chars": chars}


def _stage_of(tool_name: str | None, node_id: str | None) -> str:
    if tool_name in META_TOOLS:
        return "meta"
    if node_id:
        prefix = node_id.split("_", 1)[0]
        if prefix in STAGES:
            return prefix
    return TOOL_STAGES.get(tool_name or "", "other")


def mdclaw_invocations(calls: list[dict]) -> list[dict]:
    """MDClaw tools named in shell commands, whether or not their JSON was echoed.

    Agents pipe results through python or redirect them to files, so the
    parsed results below are a subset; the invocation list is what labels the
    timeline. ``is_error`` is the shell's exit status for the whole command.
    """
    invocations = []
    for call in calls:
        results = {result["id"]: result for result in call["tool_results"]}
        for tool in call["tool_calls"]:
            command = _command_of(tool)
            for match in _MDCLAW_TOOL.finditer(command):
                name = match.group(2)
                if name in {"exec", "run"}:
                    continue
                node = _NODE_ID.search(command[match.start():])
                node_id = node.group(1).strip("\"'") if node else None
                invocations.append({"call_index": call["index"], "tool": name,
                                    "node_id": node_id, "stage": _stage_of(name, node_id),
                                    "is_error": bool((results.get(tool["id"]) or {}).get("is_error")),
                                    "command": command[:500]})
    return invocations


def mdclaw_results(calls: list[dict]) -> list[dict]:
    """Every MDClaw JSON result in the transcript, with its tool, node and code."""
    results = []
    for call in calls:
        by_id = {tool["id"]: tool for tool in call["tool_calls"]}
        for result in call["tool_results"]:
            text = result.get("text") or ""
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                continue
            try:
                payload = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or "success" not in payload:
                continue
            command = _command_of(by_id.get(result["id"]) or {})
            match = _MDCLAW_TOOL.search(command)
            node = _NODE_ID.search(command)
            tool = payload.get("tool") or (match.group(2) if match else None)
            node_id = node.group(1) if node else payload.get("node_id")
            job = _JOB_DIR.search(command)
            results.append({"call_index": call["index"], "at": call.get("at"), "tool": tool,
                            "stage": _stage_of(tool, node_id), "node_id": node_id,
                            "job_dir": job.group(1) if job else payload.get("job_dir"),
                            "success": bool(payload.get("success")),
                            "code": payload.get("code"),
                            "message": str(payload.get("message") or payload.get("error") or "")[:300],
                            "command": command[:500]})
    return results


def error_codes(results: list[dict]) -> dict:
    return dict(Counter(item.get("code") or "unspecified" for item in results
                        if not item["success"]))


def timeline(calls: list[dict], results: list[dict] | None = None,
             skill_roots: list[str] = ()) -> list[dict]:
    """Per call: elapsed time, cumulative tokens and the stage it worked on."""
    results = results if results is not None else mdclaw_results(calls)
    by_call, stage_by_call = {}, {}
    for item in results:
        by_call.setdefault(item["call_index"], []).append(item)
    for item in mdclaw_invocations(calls):
        if item["stage"] not in {"other", "meta"}:
            stage_by_call.setdefault(item["call_index"], []).append(item["stage"])
    first = next((call["at"] for call in calls if call.get("at")), None)
    start = datetime.fromisoformat(first) if first else None
    cumulative = Counter()
    rows = []
    for call in calls:
        usage = call.get("usage") or {}
        for field in USAGE_FIELDS:
            cumulative[field] += int(usage.get(field) or 0)
        stages = ([item["stage"] for item in by_call.get(call["index"], [])
                   if item["stage"] not in {"other", "meta"}]
                  or stage_by_call.get(call["index"], [])
                  or ["meta" for item in by_call.get(call["index"], []) if item["stage"] == "meta"][:1])
        tools = [tool["name"] for tool in call["tool_calls"]]
        if stages:
            label = stages[-1]
        elif skill_reads([call], skill_roots)["reads"]:
            label = "skill_read"
        elif tools:
            label = "probe"
        else:
            label = "text"
        elapsed = None
        if start and call.get("at"):
            elapsed = (datetime.fromisoformat(call["at"]) - start).total_seconds()
        rows.append({"index": call["index"], "at": call.get("at"), "elapsed_seconds": elapsed,
                     "stage": label, "tools": tools,
                     "mdclaw": [{"tool": i["tool"], "success": i["success"], "code": i["code"]}
                                for i in by_call.get(call["index"], [])],
                     "usage": call.get("usage"),
                     "cumulative": {field: cumulative[field] for field in USAGE_FIELDS}})
    return rows
