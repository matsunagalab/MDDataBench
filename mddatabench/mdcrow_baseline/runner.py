"""Run one MDDataBench attempt with the public MDCrow agent.

Runs inside MDCrow's own Python environment, inside the attempt sandbox, on a
GPU node. Imports nothing from mddatabench (it is not visible there); its
sibling ``recorder.py`` is imported by path.

What is set here and nowhere in MDCrow's source:

- **The model connection.** MDCrow's ``_make_llm`` raises on model names it
  does not know, so ``mdcrow.agent.agent._make_llm`` is replaced by one that
  returns ``ChatOpenAI`` on the gateway's OpenAI-compatible endpoint. MDCrow's
  own temperature (0.1) and ``request_timeout`` (1000 s) are kept. Streaming
  is off so the response carries token usage (MDCrow streams to stdout by
  default; the text is the same). ``max_tokens`` is set to the value the pi
  harness sends (32768); no reasoning parameter is sent, as pi sends none to
  this gateway.
- **The OpenMM platform.** MDCrow asks for ``CPU`` by name; the recorder
  answers that request with ``CUDA``.
- **The recorder** (see ``recorder.py``).
- **A wall-clock deadline.** ``SIGALRM`` interrupts the agent at the deadline;
  OpenMM returns to Python between report intervals, so an MD run stops
  within one interval.

MDCrow is constructed as in the paper's experiment notebooks:
``agent_type="Structured"``, ``top_k_tools="all"``, ``use_memory=False``,
everything else at MDCrow's defaults. The question is the task prompt, verbatim.

Writes ``<record_dir>/run.json`` (exit reason, timings, token usage) and
``<record_dir>/transcript.jsonl`` (each LLM call: the full prompt, which
carries MDCrow's scratchpad of tool calls and observations, and the reply). The API key is read from a file and never written anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent


class DeadlineReached(BaseException):
    """Not an ``Exception``: MDCrow's tools catch ``Exception`` and return
    "Failed..." to the agent, which would swallow the deadline."""


def _write_json(path: Path, value) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str))
    os.replace(tmp, path)


def _load_key(key_file: str, provider: str) -> str:
    data = json.loads(Path(key_file).read_text())
    entry = data[provider]
    key = entry.get("key") if isinstance(entry, dict) else entry
    if not isinstance(key, str) or not key:
        raise ValueError(f"no key for provider {provider!r} in the key file")
    return key


def make_callback(transcript: Path, usage: dict):
    """A LangChain callback that logs calls and sums token usage."""
    from langchain_core.callbacks import BaseCallbackHandler

    def log(kind, **fields):
        with open(transcript, "a") as handle:
            handle.write(json.dumps({"t": round(time.time(), 3), "event": kind, **fields},
                                    default=str) + "\n")

    class Recorder(BaseCallbackHandler):
        def on_llm_start(self, serialized, prompts, **kwargs):
            self._t0 = time.time()
            log("llm_start", prompt_chars=sum(len(p) for p in prompts))

        def on_chat_model_start(self, serialized, messages, **kwargs):
            # The whole prompt: MDCrow's ReAct scratchpad carries every tool
            # call and observation, and tool callbacks do not reach here.
            self._t0 = time.time()
            log("llm_start", messages=[{"role": m.type, "content": m.content}
                                       for batch in messages for m in batch])

        def on_llm_end(self, response, **kwargs):
            output = (response.llm_output or {})
            tokens = output.get("token_usage") or {}
            usage["calls"] += 1
            if tokens:
                usage["calls_with_usage"] += 1
                usage["prompt_tokens"] += int(tokens.get("prompt_tokens") or 0)
                usage["completion_tokens"] += int(tokens.get("completion_tokens") or 0)
                details = tokens.get("completion_tokens_details") or {}
                usage["reasoning_tokens"] += int((details or {}).get("reasoning_tokens") or 0)
            text = ""
            try:
                text = response.generations[0][0].text
            except (IndexError, AttributeError):
                pass
            log("llm_end", seconds=round(time.time() - getattr(self, "_t0", time.time()), 3),
                token_usage=tokens, model=output.get("model_name"), text=text)

        def on_llm_error(self, error, **kwargs):
            usage["llm_errors"] += 1
            log("llm_error", error=repr(error))

    return Recorder()


def patch_tool_calls(events: dict, log_path: Path) -> None:
    """Keep a malformed reply or tool call from ending the agent.

    Three changes in LangChain, none in MDCrow:

    - An empty reply (the model spent all of ``max_tokens`` on reasoning) is a
      parse error, not a final answer. MDCrow builds its AgentExecutor with
      ``handle_parsing_errors=True``, so the agent is told the reply was invalid
      and goes on; LangChain would otherwise end the run with an empty answer.
      The error is raised before LangChain's ``OutputFixingParser``: that parser
      asks the LLM to re-format the reply without the task or the scratchpad,
      and for an empty reply the LLM answers "please provide a question" as the
      Final Answer, which ends the run just the same (seen in the first v7b
      attempts, 2026-11-04).
    - A JSON *string* ``action_input`` that decodes to an object
      (``"action_input": "{\\"pdb_id\\": ...}"``) is decoded. LangChain would pass
      the string as one positional argument, and MDCrow's keyword-only tools
      raise ``TypeError``.
    - A ``TypeError`` from a tool call (wrong or missing arguments) is returned to
      the agent as the observation, the way MDCrow's tools already return
      "Failed..." for their own errors, instead of ending the run.
    """
    import functools

    from langchain.agents.structured_chat.output_parser import (
        StructuredChatOutputParser, StructuredChatOutputParserWithRetries)
    from langchain_core.agents import AgentAction
    from langchain_core.exceptions import OutputParserException
    from langchain_core.tools import BaseTool

    def log(kind, **fields):
        with open(log_path, "a") as handle:
            handle.write(json.dumps({"t": round(time.time(), 3), "event": kind, **fields},
                                    default=str) + "\n")

    original_parse_with_retries = StructuredChatOutputParserWithRetries.parse

    @functools.wraps(original_parse_with_retries)
    def parse_with_retries(self, text):
        if not text.strip():
            events["empty_replies_rejected"] += 1
            log("empty_reply_rejected")
            raise OutputParserException("Could not parse LLM output: empty reply")
        return original_parse_with_retries(self, text)

    StructuredChatOutputParserWithRetries.parse = parse_with_retries

    original_parse = StructuredChatOutputParser.parse

    @functools.wraps(original_parse)
    def parse(self, text):
        result = original_parse(self, text)
        if isinstance(result, AgentAction) and isinstance(result.tool_input, str):
            try:
                decoded = json.loads(result.tool_input)
            except ValueError:
                decoded = None
            if isinstance(decoded, dict):
                events["json_string_inputs_decoded"] += 1
                log("tool_input_decoded", tool=result.tool)
                result = AgentAction(result.tool, decoded, result.log)
        return result

    StructuredChatOutputParser.parse = parse

    original_run = BaseTool.run

    @functools.wraps(original_run)
    def run(self, tool_input, *args, **kwargs):
        try:
            return original_run(self, tool_input, *args, **kwargs)
        except TypeError as exc:
            events["tool_type_errors_returned"] += 1
            log("tool_type_error", tool=self.name, error=repr(exc))
            return (f"Failed: the call to {self.name} raised TypeError: {exc}. "
                    "Check the tool's input arguments.")

    BaseTool.run = run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--record-dir", required=True)
    parser.add_argument("--model", required=True, help="model id at the gateway")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--key-provider", default="rikyu")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--deadline-seconds", type=int, default=5400)
    parser.add_argument("--platform", default="CUDA",
                        help="platform that answers MDCrow's request for 'CPU'; "
                             "'none' leaves the request alone")
    args = parser.parse_args(argv)

    started = time.time()
    record = Path(args.record_dir).resolve()
    record.mkdir(parents=True, exist_ok=True)
    workspace = Path(args.workspace).resolve()
    prompt = Path(args.prompt_file).read_text()
    run = {"schema_version": 1, "started": started, "model": args.model,
           "base_url": args.base_url, "max_tokens": args.max_tokens,
           "deadline_seconds": args.deadline_seconds,
           "platform_substitute": None if args.platform == "none" else args.platform,
           "exit_reason": "running", "pid": os.getpid(),
           "host": os.uname().nodename,
           "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES")}
    usage = {"calls": 0, "calls_with_usage": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "reasoning_tokens": 0, "llm_errors": 0}
    run["token_usage"] = usage
    harness_events = {"empty_replies_rejected": 0, "json_string_inputs_decoded": 0,
                      "tool_type_errors_returned": 0}
    run["harness_events"] = harness_events
    _write_json(record / "run.json", run)

    # MDCrow finds its working root by walking up from the cwd to a directory
    # holding setup.py, and writes reporter files into the cwd.
    os.chdir(workspace)

    sys.path.insert(0, str(HERE))
    from recorder import Recorder                                     # noqa: E402
    recorder = Recorder(record / "openmm",
                        substitute_platform=run["platform_substitute"]).install()

    def on_alarm(signum, frame):
        raise DeadlineReached(f"deadline of {args.deadline_seconds} s reached")

    signal.signal(signal.SIGALRM, on_alarm)
    signal.signal(signal.SIGTERM, on_alarm)     # Slurm's own limit, as a backstop
    signal.alarm(max(1, args.deadline_seconds))

    try:
        key = _load_key(args.key_file, args.key_provider)
        from langchain_openai import ChatOpenAI
        import mdcrow
        import mdcrow.agent.agent as agent_module

        callback = make_callback(record / "transcript.jsonl", usage)
        patch_tool_calls(harness_events, record / "transcript.jsonl")

        def make_llm(model, temp, streaming):
            # The callback is attached to the model itself: MDCrow.run passes
            # its ``callbacks`` to AgentExecutor.invoke as a keyword, which
            # langchain 0.2 ignores (it reads callbacks from ``config`` only).
            return ChatOpenAI(model=model, base_url=args.base_url, api_key=key,
                              temperature=temp, request_timeout=1000, streaming=False,
                              max_tokens=args.max_tokens, callbacks=[callback])

        agent_module._make_llm = make_llm
        run["mdcrow_file"] = mdcrow.__file__
        agent = agent_module.MDCrow(agent_type="Structured", model=args.model,
                                    top_k_tools="all", use_memory=False)
        run["ckpt_dir"] = str(Path(agent.path_registry.ckpt_dir).resolve())
        _write_json(record / "run.json", run)
        output, _ = agent.run(prompt)
        run["final_output"] = output.get("output") if isinstance(output, dict) else str(output)
        run["exit_reason"] = "completed"
    except DeadlineReached as exc:
        run["exit_reason"] = "deadline"
        run["error"] = str(exc)
    except BaseException as exc:                                      # noqa: BLE001
        run["exit_reason"] = "exception"
        run["error"] = repr(exc)
        run["traceback"] = traceback.format_exc()[-8000:]
    finally:
        signal.alarm(0)
        run["ended"] = time.time()
        run["wall_seconds"] = round(run["ended"] - started, 3)
        run["simulations_recorded"] = recorder.simulations
        _write_json(record / "run.json", run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
