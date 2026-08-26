"""A build instruction the prompt contradicts is a defect, not a residue to skip.

The aggregate polymer comparison used to filter declared build sites through a
silent membership test: a site outside every stated range, or one the prompt
elsewhere asks to leave out, simply vanished from the expected count. That is
how 011_membrane_6kuy came to say both "Residue 173-182 of chain A is not part
of the reference. Leave it out." and "build them" without the audit noticing.

These exercise the three shapes the filter used to swallow.
"""

from __future__ import annotations

import json
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

# --- all three branches through audit_task_contract, without bundles --------


def _stub_records(monkeypatch, deposit, reference):
    """Feed audit_task_contract structures instead of files.

    The excluded-site branch is covered end to end against the real 068 bundle
    below, but the other two need a deposit that resolves or omits a specific
    residue, which no shipped task does. Stubbing the reader exercises the same
    audit path without inventing coordinate files.
    """
    from mddatabench import contract_audit as ca

    def fake(path):
        return reference if str(path).endswith("reference.pdb") else deposit

    monkeypatch.setattr(ca, "_structure_records", fake)
    monkeypatch.setattr(ca, "_deposit_path", lambda pdb_id, cache: "deposit.cif")
    monkeypatch.setattr(ca, "_deposit_disulfide_positions", lambda *a, **k: set())
    monkeypatch.setattr(ca, "_reference_disulfide_positions", lambda *a: set())
    monkeypatch.setattr(ca, "_connected_metals", lambda *a, **k: set())
    monkeypatch.setattr(ca, "_deposit_components", lambda *a, **k: [])


def _task(tmp_path, extra_lines):
    task = tmp_path / "task"
    task.mkdir()
    (task / "prompt.md").write_text(
        "# Task 999_test\n\n"
        "Simulate TEST, PDB entry **1XYZ**, chain **A** residues **1–5**, "
        "in explicit solvent.\n\n"
        "- at least **1 ns** of production MD\n\n" + extra_lines)
    (task / "task.json").write_text(json.dumps({
        "reference": {"pdb_ids": ["1XYZ"],
                      "selection": {"chains": ["A"],
                                    "ranges": {"A": [["1", "5"]]}}}}))
    return task


def _residues(*numbers):
    from mddatabench.contract_audit import Residue

    return [Residue("A", n, "", "ALA") for n in numbers]


def test_a_site_outside_the_stated_range_is_reported(tmp_path, monkeypatch):
    from mddatabench.contract_audit import audit_task_contract

    _stub_records(monkeypatch, _residues(1, 2, 3, 4, 5), _residues(1, 2, 3, 4, 5))
    task = _task(tmp_path, "Chain A does not resolve residue 99; the range "
                           "runs through them, so build them.\n")
    report = audit_task_contract(str(task), str(tmp_path), deposit_cache=str(tmp_path))
    kinds = {f["kind"]: f for f in report["findings"]}
    assert "prompt_build_site_outside_selection" in kinds
    assert kinds["prompt_build_site_outside_selection"]["site"] == "A:99"


def test_a_site_the_deposit_resolves_is_reported(tmp_path, monkeypatch):
    """Asking to build a residue that has coordinates is a contradiction too."""
    from mddatabench.contract_audit import audit_task_contract

    _stub_records(monkeypatch, _residues(1, 2, 3, 4, 5), _residues(1, 2, 3, 4, 5))
    task = _task(tmp_path, "Chain A does not resolve residue 3; the range "
                           "runs through them, so build them.\n")
    report = audit_task_contract(str(task), str(tmp_path), deposit_cache=str(tmp_path))
    kinds = {f["kind"]: f for f in report["findings"]}
    assert "prompt_build_site_is_observed" in kinds
    assert kinds["prompt_build_site_is_observed"]["site"] == "A:3"


def test_a_genuine_unresolved_site_is_not_reported(tmp_path, monkeypatch):
    """The control: residue 3 absent from the deposit and present in the
    reference is exactly what a build instruction is for."""
    from mddatabench.contract_audit import audit_task_contract

    _stub_records(monkeypatch, _residues(1, 2, 4, 5), _residues(1, 2, 3, 4, 5))
    task = _task(tmp_path, "Chain A does not resolve residue 3; the range "
                           "runs through them, so build them.\n")
    report = audit_task_contract(str(task), str(tmp_path), deposit_cache=str(tmp_path))
    assert not [f for f in report["findings"] if "build_site" in f["kind"]]

