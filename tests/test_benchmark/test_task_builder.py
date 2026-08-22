"""Deriving a task's statement of its reference, instead of typing it in.

Every case here was a real defect found generating the hundred on 2026-08-23,
and each one produced a prompt that was wrong in a way a reader would not catch.

The three PLpro tasks are the fixture the builder is checked against, because
their prompts were written by hand and then verified by solving them: 6W9C is
chain C residues 4-315 with three residues to build, 6WRH the same range with
C111S, and 4OW0 the same range with OCS at 112.
"""

from __future__ import annotations

import pytest

from mddatabench import _task_builder as tb


def deposit(tmp_path, seqres, observed, name="dep.pdb"):
    """A minimal PDB carrying SEQRES and ATOM records."""
    lines = []
    for chain, residues in seqres.items():
        for start in range(0, len(residues), 13):
            # SEQRES columns: serial 8-10, chain 12, count 14-17, residues from 20.
            lines.append(f"SEQRES{start // 13 + 1:>4} {chain}{len(residues):>5}  "
                         + " ".join(residues[start:start + 13]))
    serial = 1
    for chain, residues in observed.items():
        for number, resname in residues:
            lines.append(f"ATOM  {serial:5d}  CA  {resname:>3} {chain}{number:>4}    "
                         f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C")
            serial += 1
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\nEND\n")
    return str(path)


def test_seqres_positions_are_not_residue_numbers(tmp_path):
    """6WRH's reference covers SEQRES 7-318, which is author 4-315. A contract
    stating SEQRES indices would be wrong for every deposit whose numbering does
    not start at one."""
    path = deposit(tmp_path, {"A": ["MET"] * 3 + ["ALA"] * 5},
                   {"A": [(n, "ALA") for n in range(1, 6)]})
    mapping = tb.seqres_to_auth(path, "A")
    assert mapping == {4: "1", 5: "2", 6: "3", 7: "4", 8: "5"}


def test_an_unresolved_end_is_extrapolated_because_the_prompt_must_name_it(tmp_path):
    """D01's reference builds residue 315, which the deposit does not resolve."""
    path = deposit(tmp_path, {"A": ["ALA"] * 6}, {"A": [(n, "ALA") for n in range(1, 5)]})
    mapping = tb.seqres_to_auth(path, "A")
    number, exact = tb.auth_number(mapping, 6)
    assert number == "6" and exact is False


def test_a_gap_inside_a_range_is_not_a_boundary(tmp_path):
    """1AHW's chain C has eight unresolved residues in the middle. Splitting on
    them produced "5-5 and 5-83 and 91-95 and 89-211" for one span."""
    names = ["ALA", "CYS", "ASP", "GLU", "PHE", "GLY", "HIS", "ILE", "LYS", "LEU"]
    path = deposit(tmp_path, {"A": names},
                   {"A": [(n, names[n - 1]) for n in list(range(1, 4)) + list(range(8, 11))]})
    mapping = tb.seqres_to_auth(path, "A")
    assert mapping == {1: "1", 2: "2", 3: "3", 8: "8", 9: "9", 10: "10"}
    ranges, certain = tb.auth_ranges(mapping, 1, 10)
    assert ranges == [["1", "10"]] and certain is True


def test_a_renumbered_fusion_partner_is_a_boundary(tmp_path):
    """A deposit numbers a crystallisation partner in the 1000s, so one SEQRES
    span becomes three author ranges rather than "1004-318"."""
    residues = [(str(n), "ALA") for n in range(1, 4)]
    residues += [(str(n), "ALA") for n in range(1001, 1004)]
    residues += [(str(n), "ALA") for n in range(4, 7)]
    path = deposit(tmp_path, {"A": ["ALA"] * 9}, {"A": residues})
    mapping = tb.seqres_to_auth(path, "A")
    ranges, _ = tb.auth_ranges(mapping, 1, 9)
    assert ranges == [["1", "3"], ["1001", "1003"], ["4", "6"]]


def test_identical_chains_are_not_all_placed_on_the_first_one(tmp_path):
    """A self-complementary duplex put both strands on deposit chain C, and the
    two identical ranges then read as a chain with a fusion in the middle."""
    path = deposit(tmp_path, {"C": ["DA"] * 4, "D": ["DA"] * 4},
                   {"C": [(n, "DA") for n in range(1, 5)],
                    "D": [(n, "DA") for n in range(1, 5)]})
    entries = [{"deposit_chain": "C", "ranges": [["1", "4"]]},
               {"deposit_chain": "C", "ranges": [["1", "4"]]}]
    out = tb.assign_distinct_chains(entries, path)
    assert [e["deposit_chain"] for e in out] == ["C", "D"]


def test_terminal_nucleotides_are_recognised():
    """Leaving DA5 and DT3 out of the table dropped both ends of every strand:
    1A66's 12-mer duplex came back as a 10-mer."""
    assert all(name in tb.NUCLEIC for name in ("DA5", "DA3", "DT5", "DT3", "RA", "RU"))


@pytest.mark.parametrize("ranges, expected, omitted", [
    ([["1", "10"], ["12", "20"]], [["1", "20"]], [["11", "11"]]),
    ([["1", "10"], ["1001", "1100"]], [["1", "10"], ["1001", "1100"]], []),
])
def test_small_gaps_coalesce_and_large_ones_do_not(ranges, expected, omitted):
    """6ME3 omits one residue inside its fusion partner; four exact ranges are
    faithful and unreadable, three plus a named omission are both."""
    assert tb.coalesce(ranges) == (expected, omitted)


def test_an_unbuildable_force_field_is_not_named():
    """MoDEL is Parm99, which the builder refuses as obsolete. Naming it would
    make the prompt unfollowable, and the md checks are force-field independent
    by design."""
    assert tb.buildable_force_field(["Amber Parm99"]) is None
    assert tb.buildable_force_field(["Amber ff14SB"]) == "Amber ff14SB"


def test_a_named_chain_is_used_only_when_the_deposit_has_it(tmp_path):
    """MDDB calls 6WRH's reference "from PDB 6WRH C-chain" and 6WRH has only
    chain A."""
    path = deposit(tmp_path, {"A": ["ALA"] * 3}, {"A": [(n, "ALA") for n in range(1, 4)]})
    assert tb.resolve_chain("C", "A", path) == "A"
    assert tb.resolve_chain("A", "A", path) == "A"


def test_a_paper_title_is_shortened_to_a_name():
    entry = {"struct": {"title": "X-Ray Structural and Biological Evaluation of a Series "
                                 "of Potent and Highly Selective Inhibitors"}}
    assert len(tb.molecule_name(entry, set())) <= 70
