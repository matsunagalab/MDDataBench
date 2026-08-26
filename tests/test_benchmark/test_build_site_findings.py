"""A build instruction the prompt contradicts is a defect, not a residue to skip.

The aggregate polymer comparison used to filter declared build sites through a
silent membership test: a site outside every stated range, or one the prompt
elsewhere asks to leave out, simply vanished from the expected count. That is
how 011_membrane_6kuy came to say both "Residue 173-182 of chain A is not part
of the reference. Leave it out." and "build them" without the audit noticing.

These exercise the three shapes the filter used to swallow.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from mddatabench.contract_audit import _declared


PROMPT = (
    "# Task 999_test\n\n"
    "Simulate TEST, PDB entry **1XYZ**, chain **A** residues **1–" "50**, "
    "in explicit solvent.\n\n"
    "- **TIP3P** water, neutralised\n"
    "- at least **1 ns** of production MD\n\n"
)


def _declared_with(*extra: str) -> dict:
    return _declared(PROMPT + "\n\n".join(extra) + "\n")


def test_exclusions_are_available_to_the_caller():
    """`_declared` kept them local, so no caller could name the collision."""
    declared = _declared_with(
        "Residue 10–12 of chain A is not part of the reference. "
        "Leave it out.")
    assert declared["excluded"]["A"] == [(10, 12)]


def test_an_excluded_residue_is_removed_from_the_selection():
    declared = _declared_with(
        "Residue 10–12 of chain A is not part of the reference. "
        "Leave it out.")
    assert 9 in declared["selected"]["A"]
    assert 10 not in declared["selected"]["A"]
    assert 13 in declared["selected"]["A"]


def test_a_build_instruction_is_parsed_with_its_chain():
    declared = _declared_with(
        "Chain A does not resolve residues 20, 21; the range runs through "
        "them, so build them.")
    assert declared["build_missing"] == {"A": {20, 21}}


def test_the_shape_of_011_is_visible_to_an_auditor():
    """Both instructions parse, and they overlap. That overlap is the defect.

    The audit reports it as prompt_build_site_is_excluded; this pins the parse
    the report depends on, without needing a deposit or a bundle.
    """
    declared = _declared_with(
        "Residue 10–12 of chain A is not part of the reference. "
        "Leave it out.",
        "Chain A does not resolve residues 10, 11; the range runs through "
        "them, so build them.")
    omitted = {value for start, end in declared["excluded"]["A"]
               for value in range(start, end + 1)}
    assert declared["build_missing"]["A"] & omitted == {10, 11}


@pytest.mark.parametrize("number,expected", [
    (60, False),   # beyond the stated range
    (0, False),    # before it
    (25, True),    # inside
])
def test_a_site_outside_every_stated_range_is_detectable(number, expected):
    declared = _declared_with(
        f"Chain A does not resolve residue {number}; the range runs through "
        "them, so build them.")
    assert (number in declared["selected"]["A"]) is expected

# --- end to end, against the real deposit cache and a real bundle ----------

DATASET = pathlib.Path(__file__).resolve().parents[2] / "benchmarks" / "mddatabench"
BUNDLE_ROOT = os.environ.get("MDDATABENCH_BUNDLE_ROOT")
needs_bundles = pytest.mark.skipif(
    not BUNDLE_ROOT or not pathlib.Path(BUNDLE_ROOT).is_dir(),
    reason="set MDDATABENCH_BUNDLE_ROOT to a fetched bundle tree")


@needs_bundles
def test_a_prompt_that_contradicts_itself_is_reported(tmp_path):
    """068 asks to build A:71-73. Also asking to omit them must be a finding.

    This is 011_membrane_6kuy's shape, which the audit used to swallow: the
    aggregate comparison filtered such sites out through a membership test and
    reported nothing at all.
    """
    from mddatabench.contract_audit import audit_task_contract

    source = DATASET / "tasks" / "068_soluble_1ail"
    build_line = ("Chain A does not resolve residues 71, 72, 73; the range "
                  "runs through them, so build them.")
    prompt = (source / "prompt.md").read_text()
    assert build_line in prompt, "the fixture task stopped asking to build"

    task = tmp_path / "task"
    task.mkdir()
    (task / "task.json").write_text((source / "task.json").read_text())
    (task / "prompt.md").write_text(prompt.replace(
        build_line,
        "Residue 71–73 of chain A is not part of the reference. Leave it "
        "out.\n\n" + build_line))

    report = audit_task_contract(
        str(task), str(pathlib.Path(BUNDLE_ROOT) / "bsc_A02KE"),
        deposit_cache=str(DATASET / "_deposits"))
    excluded = [f for f in report["findings"]
                if f["kind"] == "prompt_build_site_is_excluded"]
    assert {f["site"] for f in excluded} == {"A:71", "A:72", "A:73"}


@needs_bundles
def test_the_unmodified_task_is_clean():
    """The control: without the injected omission, 068 reports nothing."""
    from mddatabench.contract_audit import audit_task_contract

    report = audit_task_contract(
        str(DATASET / "tasks" / "068_soluble_1ail"),
        str(pathlib.Path(BUNDLE_ROOT) / "bsc_A02KE"),
        deposit_cache=str(DATASET / "_deposits"))
    assert report["findings"] == []

