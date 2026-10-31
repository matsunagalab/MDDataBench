"""Cations bound inside the polymer are kept when an ion-free reference cannot show them.

114_nucleic_1jrn (test-v6-cli, 2026-10-31): the builder excluded 1JRN's five
channel K+ because the reference does not carry them, and that reference carries
no water and no ion at all. Ten of 24 attempts then failed the fluctuation
ceiling with a G-quadruplex that had lost its channel cations. The rule names
a cation of a solvent species with at least four polymer O/N within 3.2 A on an
ion-free reference, and the prompt keeps it.
"""

import json
import os
import sys
from pathlib import Path

import pytest

from mddatabench import _task_builder as tb

REPO = Path(__file__).resolve().parents[2]
TASKS = REPO / "benchmarks" / "mddatabench" / "tasks"
DEPOSITS = REPO / "benchmarks" / "mddatabench" / "_deposits"
ROOT = os.environ.get("MDDATABENCH_BUNDLE_ROOT")

CHANNEL = [{"name": "K", "chain": "A", "residue": "5016"},
           {"name": "K", "chain": "A", "residue": "5017"},
           {"name": "K", "chain": "B", "residue": "5013"},
           {"name": "K", "chain": "B", "residue": "5014"},
           {"name": "K", "chain": "B", "residue": "5015"}]


def _builder():
    sys.path.insert(0, str(REPO / "scripts"))
    pytest.importorskip("gemmi")
    return pytest.importorskip("build_test_tasks")


def test_the_sentence_names_every_site():
    assert tb.bound_ion_sentence(CHANNEL, "nucleic acid") == (
        "Keep the deposit's five **K** ions bound inside the nucleic acid (chain A "
        "residues 5016 and 5017; chain B residues 5013, 5014 and 5015).")
    assert tb.bound_ion_sentence(CHANNEL[:1]) == (
        "Keep the deposit's one **K** ion bound inside the protein (chain A residue 5016).")
    with pytest.raises(ValueError):
        tb.bound_ion_sentence(CHANNEL + [{"name": "NA", "chain": "A", "residue": "1"}])


def test_without_bound_ions_the_prompt_is_unchanged():
    args = ("t", "x", "1ABC", {"TEMP": 300, "WAT": "TIP3P"},
            [{"deposit_chain": "A", "ranges": [["1", "10"]]}], [], [], 1.0)
    assert tb.build_prompt(*args) == tb.build_prompt(*args, bound_ions=())
    kept = tb.build_prompt(*args, bound_ions=CHANNEL, polymer_subject="nucleic acid")
    assert "Keep the deposit's five **K** ions bound inside the nucleic acid" in kept


def _chosen():
    return [{"deposit_chain": "A", "ranges": [["1001", "1012"]]},
            {"deposit_chain": "B", "ranges": [["2001", "2012"]]}]


def _reference(tmp_path, with_ion):
    lines = ["ATOM      1  P    DG A   2      0.000   0.000   0.000  1.00  0.00           P"]
    if with_ion:
        lines.append("HETATM    2 NA    NA A 100     30.000  30.000  30.000  1.00  0.00          NA")
    path = tmp_path / "reference.pdb"
    path.write_text("\n".join(lines + ["END"]) + "\n")
    return path


def test_1jrn_channel_k_is_found_on_an_ion_free_reference(tmp_path):
    bt = _builder()
    found = bt.bound_solvent_cations(DEPOSITS / "1JRN.cif", _chosen(),
                                     _reference(tmp_path, with_ion=False))
    assert [{k: ion[k] for k in ("name", "chain", "residue")} for ion in found] == CHANNEL
    assert all(ion["polymer_donors"] >= bt.BOUND_ION_MIN_DONORS for ion in found)


def test_a_reference_that_carries_ions_shows_its_own(tmp_path):
    bt = _builder()
    assert bt.bound_solvent_cations(DEPOSITS / "1JRN.cif", _chosen(),
                                    _reference(tmp_path, with_ion=True)) == []


def test_the_shipped_114_keeps_the_channel_and_excludes_nothing():
    task = json.loads((TASKS / "114_nucleic_1jrn" / "task.json").read_text())
    selection = task["reference"]["selection"]
    assert "excluded_components" not in selection
    assert [{k: ion[k] for k in ("name", "chain", "residue")}
            for ion in selection["bound_ions"]] == CHANNEL
    prompt = (TASKS / "114_nucleic_1jrn" / "prompt.md").read_text()
    assert tb.bound_ion_sentence(selection["bound_ions"], "nucleic acid") in prompt
    assert "not part of the reference" not in prompt


def _bundle(task):
    if not ROOT:
        pytest.skip("MDDATABENCH_BUNDLE_ROOT is not set")
    reference = task["reference"]
    bundle = Path(ROOT) / f"{reference['node']}_{reference['accession']}"
    if not (bundle / "reference.pdb").is_file():
        pytest.skip(f"no bundle at {bundle}")
    return bundle


@pytest.mark.parametrize("task_dir", sorted(p.parent for p in TASKS.glob("*/task.json")),
                         ids=lambda p: p.name)
def test_the_rule_applies_to_114_alone(task_dir):
    """Applied to every task; only 114's contract changes (GPCR Na+ sites have two donors)."""
    bt = _builder()
    task = json.loads((task_dir / "task.json").read_text())
    selection = task["reference"]["selection"]
    cif = DEPOSITS / f"{task['reference']['pdb_ids'][0].upper()}.cif"
    chosen = [{"deposit_chain": chain, "ranges": selection["ranges"].get(chain, [])}
              for chain in selection["chains"]]
    found = bt.bound_solvent_cations(cif, chosen, _bundle(task) / "reference.pdb")
    if task["task_id"] == "114_nucleic_1jrn":
        assert len(found) == 5
    else:
        assert found == [], task["task_id"]
