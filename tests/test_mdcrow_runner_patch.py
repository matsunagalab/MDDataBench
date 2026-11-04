"""The runner's tool-call patch (runs in the MDCrow environment only)."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("langchain")

RUNNER_DIR = Path(__file__).resolve().parents[1] / "mddatabench" / "mdcrow_baseline"

# The reply glm-5.3-flash gave in 131_ligand_2pql r3 of the first v7 campaign.
GLM_REPLY = textwrap.dedent('''\
    Thought: prepare the structure.

    Action:
    ```
    {
      "action": "CleaningToolFunction",
      "action_input": "{\\"pdb_id\\": \\"2PQL_033607\\", \\"remove_water\\": false}"
    }
    ```''')


def test_json_string_input_is_decoded_and_type_errors_are_returned(tmp_path):
    script = textwrap.dedent(f"""
        import json, sys
        from pathlib import Path
        sys.path.insert(0, {str(RUNNER_DIR)!r})
        from runner import patch_tool_calls
        from langchain.agents.structured_chat.output_parser import (
            StructuredChatOutputParserWithRetries)
        from langchain_core.tools import BaseTool

        events = {{"empty_replies_rejected": 0, "bare_json_actions_read": 0,
                   "json_string_inputs_decoded": 0, "tool_type_errors_returned": 0}}
        patch_tool_calls(events, Path({str(tmp_path / 'log.jsonl')!r}))

        class KwargsOnly(BaseTool):
            name: str = "CleaningToolFunction"
            description: str = "test"
            def _run(self, **input_args):
                return "ok " + json.dumps(input_args, sort_keys=True)

        action = StructuredChatOutputParserWithRetries().parse({GLM_REPLY!r})
        out = {{"tool_input": action.tool_input,
                "decoded_run": KwargsOnly().run(action.tool_input),
                "string_run": KwargsOnly().run("not json"),
                "plain_string": StructuredChatOutputParserWithRetries().parse(
                    'Action:\\n```\\n{{"action": "PDBFileDownloader", "action_input": "2PQL"}}\\n```'
                ).tool_input,
                "events": events}}
        print(json.dumps(out))
    """)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          check=True)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["tool_input"] == {"pdb_id": "2PQL_033607", "remove_water": False}
    assert out["decoded_run"] == 'ok {"pdb_id": "2PQL_033607", "remove_water": false}'
    assert out["string_run"].startswith("Failed: the call to CleaningToolFunction raised TypeError")
    assert out["plain_string"] == "2PQL"          # a non-JSON string is left alone
    assert out["events"] == {"empty_replies_rejected": 0, "bare_json_actions_read": 0,
                             "json_string_inputs_decoded": 1, "tool_type_errors_returned": 1}
    logged = [json.loads(line)["event"] for line in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert logged == ["tool_input_decoded", "tool_type_error"]


def test_agent_survives_empty_reply_and_json_string_input(tmp_path):
    """An AgentExecutor built as MDCrow builds it (StructuredChatAgent with
    LangChain's default OutputFixingParser, handle_parsing_errors=True) goes on
    after an empty reply, and the empty reply never reaches the fixing parser
    (which re-asks the LLM without the task)."""
    final = 'Action:\n```\n{"action": "Final Answer", "action_input": "done"}\n```'
    script = textwrap.dedent(f"""
        import json, sys
        from pathlib import Path
        sys.path.insert(0, {str(RUNNER_DIR)!r})
        from runner import patch_tool_calls
        from langchain.agents import AgentExecutor
        from langchain.agents.structured_chat.base import StructuredChatAgent
        from langchain_core.language_models.fake_chat_models import FakeListChatModel
        from langchain_core.tools import BaseTool

        events = {{"empty_replies_rejected": 0, "bare_json_actions_read": 0,
                   "json_string_inputs_decoded": 0, "tool_type_errors_returned": 0}}
        patch_tool_calls(events, Path({str(tmp_path / 'log.jsonl')!r}))
        calls = []

        class KwargsOnly(BaseTool):
            name: str = "CleaningToolFunction"
            description: str = "test"
            def _run(self, **input_args):
                calls.append(input_args)
                return "cleaned"

        llm = FakeListChatModel(responses=["", {GLM_REPLY!r}, {final!r}])
        tools = [KwargsOnly()]
        agent = StructuredChatAgent.from_llm_and_tools(llm, tools)
        assert agent.output_parser.output_fixing_parser is not None
        executor = AgentExecutor.from_agent_and_tools(agent, tools, handle_parsing_errors=True,
                                                      return_intermediate_steps=True)
        out = executor.invoke({{"input": "clean it"}})
        steps = [step[0].tool for step in out["intermediate_steps"]]
        print(json.dumps({{"output": out["output"], "calls": calls, "events": events,
                           "steps": steps}}))
    """)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          check=True)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["output"] == "done"
    # The empty reply became an "Invalid or incomplete response" observation;
    # had it gone to the fixing parser, the fixer would have taken GLM_REPLY.
    assert out["steps"] == ["_Exception", "CleaningToolFunction"]
    assert out["calls"] == [{"pdb_id": "2PQL_033607", "remove_water": False}]
    assert out["events"] == {"empty_replies_rejected": 1, "bare_json_actions_read": 0,
                             "json_string_inputs_decoded": 1, "tool_type_errors_returned": 0}


# The reply deepseek-v4.1-flash gave in 131_ligand_2pql r1 of v7c (no fence).
DEEPSEEK_BARE = '{\n  "action": "PDBFileDownloader",\n  "action_input": {"query": "2PQL"}\n}'


def test_bare_json_action_is_read_as_a_tool_call(tmp_path):
    cases = {
        "bare": DEEPSEEK_BARE,
        "after_thought": "Thought: download it.\n\nAction:\n" + DEEPSEEK_BARE,
        "bare_final": '{"action": "Final Answer", "action_input": "done"}',
        "prose": "The simulation finished; {see the log}.",
    }
    script = textwrap.dedent(f"""
        import json, sys
        from pathlib import Path
        sys.path.insert(0, {str(RUNNER_DIR)!r})
        from runner import patch_tool_calls
        from langchain.agents.structured_chat.output_parser import (
            StructuredChatOutputParserWithRetries)
        from langchain_core.agents import AgentAction

        events = {{"empty_replies_rejected": 0, "bare_json_actions_read": 0,
                   "json_string_inputs_decoded": 0, "tool_type_errors_returned": 0}}
        patch_tool_calls(events, Path({str(tmp_path / 'log.jsonl')!r}))
        parser = StructuredChatOutputParserWithRetries()
        out = {{}}
        for name, text in {cases!r}.items():
            r = parser.parse(text)
            out[name] = (["action", r.tool, r.tool_input, r.log == text]
                         if isinstance(r, AgentAction) else ["finish", r.return_values["output"]])
        out["events"] = events
        print(json.dumps(out))
    """)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          check=True)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["bare"] == ["action", "PDBFileDownloader", {"query": "2PQL"}, True]
    assert out["after_thought"] == ["action", "PDBFileDownloader", {"query": "2PQL"}, True]
    assert out["bare_final"] == ["finish", "done"]
    assert out["prose"] == ["finish", "The simulation finished; {see the log}."]
    assert out["events"]["bare_json_actions_read"] == 3
