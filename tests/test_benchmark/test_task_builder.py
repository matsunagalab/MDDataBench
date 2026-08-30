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


def his_reference(tmp_path, hydrogens, name="reference.pdb"):
    """One internal HIS residue with a chosen hydrogen naming/formula."""
    atoms = [
        ("N", "N"), ("CA", "C"), ("C", "C"), ("O", "O"),
        ("CB", "C"), ("CG", "C"), ("ND1", "N"), ("CD2", "C"),
        ("CE1", "C"), ("NE2", "N"),
        *((atom_name, "H") for atom_name in hydrogens),
    ]
    rows = []
    for serial, (atom_name, element) in enumerate(atoms, start=1):
        rows.append(
            f"ATOM  {serial:5d} {atom_name:>4s} HIS A{1:4d}    "
            f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00          {element:>2s}"
        )
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\nEND\n")
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


def _stated_his(tmp_path, hydrogens, monkeypatch=None, exemption=None):
    reference = his_reference(tmp_path, hydrogens)
    source = deposit(tmp_path, {"A": ["HIS"]}, {"A": [(107, "HIS")]})
    chains = [{"deposit_chain": "A", "seqres_start": 1,
               "seqres_spans": [(1, 1)]}]
    if exemption:
        from mddatabench import composition as cp

        for function in ("metal_ligand_positions", "catalytic_dyad_positions"):
            if function == exemption:
                monkeypatch.setattr(
                    cp, function,
                    lambda monomers, _metals: {id(monomers[0]): {1}},
                )
            else:
                monkeypatch.setattr(cp, function, lambda _monomers, _metals: {})
    return tb.stated_protonation(reference, source, chains)


def test_his_with_both_ring_protons_is_disclosed_as_protonated(tmp_path):
    result = _stated_his(
        tmp_path, ["HN", "HA", "HB1", "HB2", "HD1", "HD2", "HE1", "HE2"])
    assert result == [{
        "chain": "A", "residue": "107", "name": "HIS",
        "meaning": "protonated histidine", "reference_residue": "1",
    }]


def test_neutral_his_is_not_disclosed(tmp_path):
    result = _stated_his(
        tmp_path, ["HN", "HA", "HB1", "HB2", "HD2", "HE1", "HE2"])
    assert result == []


def test_hip_formula_is_a_fallback_when_ring_proton_names_are_absent(tmp_path):
    result = _stated_his(tmp_path, [f"H{index}" for index in range(1, 9)])
    assert result[0]["meaning"] == "protonated histidine"


@pytest.mark.parametrize("exemption", [
    "metal_ligand_positions", "catalytic_dyad_positions",
])
def test_hip_like_his_exemptions_still_win(tmp_path, monkeypatch, exemption):
    result = _stated_his(
        tmp_path, ["HN", "HA", "HB1", "HB2", "HD1", "HD2", "HE1", "HE2"],
        monkeypatch, exemption)
    assert result == []


def test_reference_position_skips_a_removed_fusion_span():
    entry = {"seqres_spans": [(9, 216), (323, 410)]}
    assert tb._reference_seqres_position(entry, 208) == 216
    assert tb._reference_seqres_position(entry, 209) == 323
    assert tb._reference_seqres_position(entry, 255) == 369
    assert tb._reference_seqres_position(entry, 296) == 410


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


# --- ligated or not is a decision the deposit does not record -----------------
# A fusion construct written as two ranges can be simulated as two chains or as
# one.  5ZK8 bonds residue 214 to 383 at 1.35 A where the deposit leaves them
# 9.63 A apart; 5YC8 keeps 199 and 79 residues apart.  Which it is follows from
# where the ranges came from, not from counting anything: one reference chain
# with an internal deletion is one polymer, several reference chains merged onto
# one deposit chain are several.

def test_one_reference_chain_with_a_deletion_was_ligated():
    """5ZK8: reference chain A, 273 residues, 115 removed from the middle."""
    merged = tb.merge_by_deposit_chain([
        {"deposit_chain": "A", "ranges": [["18", "214"], ["383", "458"]],
         "residues": 273, "removed_residues": 115, "internal_deletion": True},
    ])
    assert tb.joins_its_pieces(merged) == frozenset({"A"})


def test_two_reference_chains_on_one_deposit_chain_were_not():
    """5YC8: reference chains A (199) and B (79), both deposit chain A."""
    merged = tb.merge_by_deposit_chain([
        {"deposit_chain": "A", "ranges": [["16", "214"]], "residues": 199},
        {"deposit_chain": "A", "ranges": [["380", "458"]], "residues": 79},
    ])
    assert len(merged) == 1 and len(merged[0]["ranges"]) == 2
    assert tb.joins_its_pieces(merged) == frozenset()


def test_three_reference_chains_are_three_polymers():
    """6KUY: 140, 45 and 79 residues, all on deposit chain A."""
    merged = tb.merge_by_deposit_chain([
        {"deposit_chain": "A", "ranges": [["35", "172"]], "residues": 140},
        {"deposit_chain": "A", "ranges": [["183", "227"]], "residues": 45},
        {"deposit_chain": "A", "ranges": [["365", "443"]], "residues": 79},
    ])
    assert tb.joins_its_pieces(merged) == frozenset()


def test_a_single_range_chain_is_never_reported():
    merged = tb.merge_by_deposit_chain([
        {"deposit_chain": "A", "ranges": [["1", "100"]], "residues": 100}])
    assert tb.joins_its_pieces(merged) == frozenset()


def test_each_chain_is_answered_on_its_own():
    """6I53 has several multi-range chains; provenance answers each separately."""
    merged = tb.merge_by_deposit_chain([
        {"deposit_chain": "A", "ranges": [["10", "323"], ["384", "418"]],
         "residues": 349, "removed_residues": 60, "internal_deletion": True},
        {"deposit_chain": "E", "ranges": [["8", "312"]], "residues": 303},
        {"deposit_chain": "E", "ranges": [["418", "447"]], "residues": 33},
    ])
    assert tb.joins_its_pieces(merged) == frozenset({"A"})


def test_the_prompt_says_it_only_for_the_chains_that_were_joined():
    metadata = {"WAT": "TIP3P", "TEMP": 300, "ENSEMBLE": "NPT", "FF": ["Amber ff14SB"]}
    chains = [{"deposit_chain": "A", "ranges": [["18", "214"], ["383", "458"]],
               "internal_deletion": True, "removed_residues": 115}]
    joined = tb.build_prompt("t", "Receptor", "5ZK8", metadata, chains, {}, {},
                             1.0, joined_chains={"A"})
    apart = tb.build_prompt("t", "Receptor", "5ZK8", metadata, chains, {}, {}, 1.0)
    assert "single continuous chain" in joined
    assert "single continuous chain" not in apart
    assert "crystallisation partner" in joined and "crystallisation partner" in apart


def _deposit(tmp_path, seqres_by_chain, observed=None):
    """A PDB with SEQRES for each chain and, by default, every residue observed."""
    rows = []
    for chain, sequence in seqres_by_chain.items():
        names = ["ALA" if c == "A" else "GLY" for c in sequence]
        for i in range(0, len(names), 13):
            rows.append(f"SEQRES {i // 13 + 1:3d} {chain} {len(names):4d}  "
                        + " ".join(names[i:i + 13]))
    serial = 1
    for chain, sequence in seqres_by_chain.items():
        numbers = (observed or {}).get(chain, list(range(1, len(sequence) + 1)))
        for resnum in numbers:
            for name, element in (("N", "N"), ("CA", "C"), ("C", "C")):
                rows.append(f"ATOM  {serial:5d}  {name:<3s} ALA {chain}{resnum:4d}    "
                            f"{serial * 1.0:8.3f}{0.0:8.3f}{0.0:8.3f}"
                            f"  1.00  0.00          {element:>2s}")
                serial += 1
    path = tmp_path / "deposit.pdb"
    path.write_text("\n".join(rows) + "\nEND\n")
    return str(path)


# --- a deposit chain can collect reference chains for two opposite reasons ----
# 6I53 is a GABA-A pentamer whose subunits are each fusion constructs, so deposit
# chain E collects four reference chains: two copies of two pieces. Moving one
# duplicate per twin, in arrival order, left both full-length copies on E -- the
# only overlapping range pair in the cast -- and stranded a 33-residue piece away
# from the copy it belongs to. Pieces of one construct are disjoint and copies
# overlap, which answers both at once.

def test_disjoint_ranges_are_pieces_and_overlapping_ones_are_copies():
    assert not tb.spans_overlap([["10", "312"]], [["418", "447"]])
    assert tb.spans_overlap([["10", "312"]], [["8", "312"]])
    assert tb.spans_overlap([["10", "312"]], [["312", "400"]]), "touching is covering"


def test_an_endpoint_that_is_not_a_number_is_not_guessed_at():
    """A chain numbered 100, 100A has no arithmetic; only an identical pair counts."""
    assert tb.spans_overlap([["100", "100A"]], [["100", "100A"]])
    assert not tb.spans_overlap([["100", "100A"]], [["100", "200"]])


def test_two_copies_of_a_subunit_are_given_a_chain_each(tmp_path):
    """Each construct after the first claims a SEQRES twin."""
    deposit = _deposit(tmp_path, {"E": "AAAAA", "B": "AAAAA"})
    entries = [
        {"reference_chain": "A", "deposit_chain": "E", "ranges": [["1", "3"]],
         "seqres_spans": [(1, 3)], "residues": 3},
        {"reference_chain": "D", "deposit_chain": "E", "ranges": [["1", "3"]],
         "seqres_spans": [(1, 3)], "residues": 3},
    ]
    placed = tb.assign_distinct_chains(entries, deposit)
    assert sorted(e["deposit_chain"] for e in placed) == ["B", "E"]


def test_the_pieces_of_one_construct_stay_together(tmp_path):
    """A 33-mer belongs with the copy whose ranges it does not overlap."""
    deposit = _deposit(tmp_path, {"E": "A" * 10, "B": "A" * 10})
    entries = [
        {"reference_chain": "A", "deposit_chain": "E", "ranges": [["1", "3"]],
         "seqres_spans": [(1, 3)], "residues": 3},
        {"reference_chain": "B", "deposit_chain": "E", "ranges": [["8", "10"]],
         "seqres_spans": [(8, 10)], "residues": 3},
        {"reference_chain": "D", "deposit_chain": "E", "ranges": [["1", "3"]],
         "seqres_spans": [(1, 3)], "residues": 3},
        {"reference_chain": "E", "deposit_chain": "E", "ranges": [["8", "10"]],
         "seqres_spans": [(8, 10)], "residues": 3},
    ]
    placed = {e["reference_chain"]: e["deposit_chain"]
              for e in tb.assign_distinct_chains(entries, deposit)}
    assert placed["A"] == placed["B"], "the first copy's two pieces share a chain"
    assert placed["D"] == placed["E"], "and so do the second copy's"
    assert placed["A"] != placed["D"], "but the two copies do not"


def test_a_moved_two_piece_entry_keeps_both_pieces(tmp_path):
    """6I53 asked for deposit D 10-401, which spans 45 residues the deposit lacks.

    Collapsing a two-interval match into one span both invents those residues and
    loses the statement that the two pieces are joined.
    """
    deposit = _deposit(tmp_path, {"A": "A" * 20, "D": "A" * 20},
                       observed={"A": list(range(1, 21)),
                                 "D": list(range(1, 6)) + list(range(15, 21))})
    entry = {"reference_chain": "H", "deposit_chain": "A", "residues": 11,
             "ranges": [["1", "5"], ["15", "20"]], "seqres_spans": [(1, 5), (15, 20)],
             "internal_deletion": True}
    moved = tb.remeasure_on(entry, deposit, "D")
    assert moved["deposit_chain"] == "D"
    # Two intervals stay two ranges. The numbers themselves come from the
    # alignment on the chain it moved to, which is the point -- they are measured
    # there rather than carried over -- so what is pinned is that the pieces stay
    # apart instead of collapsing into one span across the removed part.
    assert len(moved["ranges"]) == 2
    (_, first_end), (second_start, _) = moved["ranges"]
    assert int(second_start) > int(first_end) + 1, "the removed part stays removed"


# --- what the prompt does not name is standard --------------------------------
# A pKa predictor disagrees with the reference somewhere. MDClaw runs
# pdb2pqr+propka at pH 7.4 and neutralised two aspartates of 5ZK8 that the
# reference kept charged; the atom-count check then reported a composition
# difference for a decision the prompt never asked about. Every reference in the
# cast carries hydrogens, so "standard except where stated" is measured.

def _prompt(protonation):
    metadata = {"WAT": "TIP3P", "TEMP": 300, "ENSEMBLE": "NPT", "FF": ["Amber ff14SB"]}
    chains = [{"deposit_chain": "A", "ranges": [["1", "100"]]}]
    return tb.build_prompt("t", "Protein", "1ABC", metadata, chains, {},
                           protonation, 1.0)


def test_the_standard_state_is_stated():
    assert "standard state at pH 7" in _prompt([])


def test_it_says_every_when_nothing_else_was_named():
    text = _prompt([])
    assert "Simulate every ionisable side chain" in text
    assert "every other" not in text


def test_it_says_every_other_when_something_was_named():
    text = _prompt([{"chain": "A", "residue": 107,
                     "meaning": "protonated histidine"}])
    assert "Residue 107 of chain A is a protonated histidine." in text
    assert "Simulate every other ionisable side chain" in text


def test_a_reduced_disulfide_is_an_instruction_not_a_hint():
    metadata = {"WAT": "TIP3P", "TEMP": 300, "ENSEMBLE": "NPT"}
    chains = [{"deposit_chain": "A", "ranges": [["1", "96"]]}]
    text = tb.build_prompt(
        "t", "Protein", "1AY7", metadata, chains, {}, [], 1.0,
        disulfides={"formed": [], "reduced": [
            {"chain": "A", "residues": ["7", "96"]},
        ]},
    )

    assert ("Simulate Cys7 and Cys96 of chain A as free (reduced) cysteines; "
            "do not form a disulfide bond between them.") in text
    assert "Simulate every other ionisable side chain" in text


def test_a_flattened_peptide_component_is_fully_buildable_from_the_prompt():
    metadata = {"WAT": "TIP3P", "TEMP": 298, "ENSEMBLE": "NPT"}
    chains = [{"deposit_chain": "A", "ranges": [["1", "56"]]}]
    component = {
        "residue_name": "LIG",
        "description": "Ac-Phe-Ala-Tyr-Nε-trimethyl-Lys-Ser-NH2",
        "formula": "C35H52N7O8",
        "smiles": "example-smiles",
        "expected_formal_net_charge": 1,
        "placement_source": {
            "chain": "B", "positions": ["1", "7"],
            "sequence": "ACE–PHE–ALA–TYR–M3L–SER–NH2",
        },
    }
    text = tb.build_prompt(
        "t", "Protein", "4MN3", metadata, chains, {}, [], 1.0,
        extra_components=[component],
    )

    assert "one extra component named **LIG**" in text
    assert "**C35H52N7O8**" in text and "charge **+1**" in text
    assert "SMILES `example-smiles`" in text
    assert "chain B positions 1–7" in text
    assert "one LIG residue, not as separate residues or caps" in text


# --- a repeated residue used to shift every later anchor -----------------------
# The mapping walked SEQRES and the observed residues together, advancing past
# every mismatch. 1AHW chain C is SEQRES "S G T T N T" against an observed
# "T N T" starting at author 4, so the walk spent SEQRES position 3 on author 4
# and shifted everything after it: the prompt asked for author 5-211, 207
# residues where the reference has 208, and named a different set of residues as
# unresolved than the ones that are.

def _chain_pdb(tmp_path, name, sequence, observed):
    """SEQRES for the whole chain, ATOM records for the observed part."""
    three = {"S": "SER", "G": "GLY", "T": "THR", "N": "ASN", "V": "VAL",
             "A": "ALA", "L": "LEU", "K": "LYS"}
    rows = []
    codes = [three[c] for c in sequence]
    for i in range(0, len(codes), 13):
        rows.append(f"SEQRES {i // 13 + 1:3d} C {len(codes):4d}  "
                    + " ".join(codes[i:i + 13]))
    serial = 1
    for number, code in observed:
        for atom, element in (("N", "N"), ("CA", "C"), ("C", "C")):
            rows.append(f"ATOM  {serial:5d}  {atom:<3s} {three[code]} C{number:4d}    "
                        f"{serial * 1.4:8.3f}{0.0:8.3f}{0.0:8.3f}"
                        f"  1.00  0.00          {element:>2s}")
            serial += 1
    path = tmp_path / name
    path.write_text("\n".join(rows) + "\nEND\n")
    return str(path)


def test_a_repeat_before_the_first_observed_residue_does_not_shift_it(tmp_path):
    """1AHW chain C, reduced: SGTTNT against TNT observed from 4."""
    deposit = _chain_pdb(tmp_path, "repeat.pdb", "SGTTNT",
                         [(4, "T"), (5, "N"), (6, "T")])
    mapping = tb.seqres_to_auth(deposit, "C")
    assert mapping == {4: "4", 5: "5", 6: "6"}, "the second T, not the first"


def test_a_run_is_placed_whole_and_runs_keep_their_order(tmp_path):
    """Two runs either side of a gap, each landing where its codes fit."""
    deposit = _chain_pdb(tmp_path, "runs.pdb", "AKLVNTAKL",
                         [(1, "A"), (2, "K"), (3, "L"), (7, "A"), (8, "K"), (9, "L")])
    mapping = tb.seqres_to_auth(deposit, "C")
    assert mapping == {1: "1", 2: "2", 3: "3", 7: "7", 8: "8", 9: "9"}
    assert 4 not in mapping and 6 not in mapping, "the gap stays unplaced"


def test_runs_are_split_on_a_break_in_the_numbering():
    pairs = [("1", "A"), ("2", "K"), ("5", "L"), ("6", "V")]
    assert [[n for n, _, _ in run] for run in tb.observed_runs(pairs)] == [[1, 2], [5, 6]]


def test_a_run_that_matches_nothing_stops_rather_than_guessing(tmp_path):
    """A deposit whose residues its own SEQRES does not contain."""
    deposit = _chain_pdb(tmp_path, "conflict.pdb", "AAAA",
                         [(1, "A"), (2, "A"), (5, "K"), (6, "L"), (7, "V"), (8, "N")])
    mapping = tb.seqres_to_auth(deposit, "C")
    assert mapping == {1: "1", 2: "2"}, "and nothing after the run it cannot place"
    assert not tb.mapping_is_trustworthy(deposit, "C", mapping), (
        "too little of the chain placed to state a number from it")


# --- what a partly placed chain is worth --------------------------------------
# A share was the wrong test. A chain whose middle disagrees with its own SEQRES
# placed 60 of 99 residues, passed a half threshold, and produced a prompt saying
# 40 residues of the range are unresolved when the deposit resolves 39 of them.
# Which part failed is exactly what is not known, so nothing about it is safe to
# state.

def test_a_chain_that_places_completely_is_trusted(tmp_path):
    deposit = _chain_pdb(tmp_path, "whole.pdb", "AKLVNT",
                         [(1, "A"), (2, "K"), (5, "N"), (6, "T")])
    mapping = tb.seqres_to_auth(deposit, "C")
    assert len(mapping) == 4
    assert tb.mapping_is_trustworthy(deposit, "C", mapping)


def test_a_chain_that_places_most_of_itself_is_not(tmp_path):
    """Sixty of ninety-nine used to pass, and the prompt it made was wrong."""
    deposit = _chain_pdb(
        tmp_path, "conflict.pdb", "A" * 40 + "K" + "A" * 59,
        [(i, "A") for i in range(1, 61)] + [(i, "A") for i in range(62, 101)])
    mapping = tb.seqres_to_auth(deposit, "C")
    assert 0 < len(mapping) < 99
    assert not tb.mapping_is_trustworthy(deposit, "C", mapping)


def test_one_free_amino_acid_does_not_condemn_the_chain(tmp_path):
    """1DTD ends with a GLU 300 that is a ligand beside its zinc, not residue 300."""
    deposit = _chain_pdb(tmp_path, "ligand.pdb", "AAAA",
                         [(1, "A"), (2, "A"), (3, "A"), (4, "A"), (300, "K")])
    mapping = tb.seqres_to_auth(deposit, "C")
    assert len(mapping) == 4, "the polymer places; the loose residue does not"
    assert tb.mapping_is_trustworthy(deposit, "C", mapping)


def test_an_unplaceable_run_does_not_cost_the_runs_after_it(tmp_path):
    """Breaking out made one stray record drop the whole rest of the chain."""
    deposit = _chain_pdb(tmp_path, "stray.pdb", "AAAANNNN",
                         [(1, "A"), (2, "A"), (10, "K"),
                          (20, "N"), (21, "N"), (22, "N")])
    mapping = tb.seqres_to_auth(deposit, "C")
    assert mapping[1] == "1" and mapping[2] == "2"
    assert "20" in mapping.values(), "the run after the stray record still places"


def test_selection_refuses_a_chain_whose_numbering_is_not_recoverable(tmp_path):
    """The guard lived beside the mapping and nothing in the library called it."""
    deposit = _chain_pdb(
        tmp_path, "unplaceable.pdb", "A" * 40 + "K" + "A" * 59,
        [(i, "A") for i in range(1, 61)] + [(i, "A") for i in range(62, 101)])
    record = {"鎖": [{"参照鎖": "A", "寄託鎖": "C", "長さ": 99,
                     "種別": "SEQRES に連続一致", "SEQRES位置": "1-100"}]}
    with pytest.raises(SystemExit) as raised:
        tb.selection(record, deposit)
    assert "does not place" in str(raised.value)

# --- build sites come from the named list, never from the aggregate count ---


def test_a_count_without_names_produces_no_build_prose():
    """The defect this exists to stop.

    `build_missing` is a length that survives being merged and moved between
    deposit chains. In the shipped contracts it reports a non-zero value for
    seven tasks whose reference built nothing, and prose generated from it told
    an agent to add residues the reference does not have -- failing the
    composition check it was meant to satisfy.
    """
    entry = {"deposit_chain": "A", "ranges": [("16", "214")], "build_missing": 1}
    assert tb._validated_build_sites(entry) == []


def test_named_sites_are_returned_in_order():
    entry = {"deposit_chain": "C", "ranges": [("5", "211")],
             "build_residues": [83, 84, 85], "build_missing": 3}
    assert tb._validated_build_sites(entry) == [83, 84, 85]


def test_an_insertion_code_site_survives():
    """036 declares 1A-79; the site model must not reduce it to an integer."""
    entry = {"deposit_chain": "A", "ranges": [("1A", "79")],
             "build_residues": ["1A"], "build_missing": 1}
    assert tb._validated_build_sites(entry) == ["1A"]


def test_a_site_that_is_also_omitted_fails_generation():
    """011_membrane_6kuy's shape: leave these out, and also build them."""
    entry = {"deposit_chain": "A", "ranges": [("1", "50")],
             "omitted": [(10, 12)], "build_residues": [10]}
    with pytest.raises(ValueError, match="both built and omitted"):
        tb._validated_build_sites(entry)


def test_a_site_outside_every_range_fails_generation():
    entry = {"deposit_chain": "A", "ranges": [("1", "50")], "build_residues": [60]}
    with pytest.raises(ValueError, match="outside every stated range"):
        tb._validated_build_sites(entry)


def test_a_repeated_site_fails_generation():
    entry = {"deposit_chain": "A", "ranges": [("1", "50")], "build_residues": [20, 20]}
    with pytest.raises(ValueError, match="listed twice"):
        tb._validated_build_sites(entry)


def test_merging_two_reference_chains_keeps_both_site_lists():
    """The count was merged and the sites were not, so one list was lost."""
    merged = tb.merge_by_deposit_chain([
        {"deposit_chain": "A", "ranges": [("1", "50")], "residues": 50,
         "build_missing": 1, "build_residues": [10]},
        {"deposit_chain": "A", "ranges": [("60", "90")], "residues": 31,
         "build_missing": 1, "build_residues": [70]},
    ])
    assert len(merged) == 1
    assert merged[0]["build_residues"] == [10, 70]
    assert merged[0]["build_missing"] == 2


def test_merging_does_not_duplicate_a_shared_site():
    merged = tb.merge_by_deposit_chain([
        {"deposit_chain": "A", "ranges": [("1", "50")], "residues": 50,
         "build_missing": 1, "build_residues": [10]},
        {"deposit_chain": "A", "ranges": [("1", "50")], "residues": 50,
         "build_missing": 1, "build_residues": [10]},
    ])
    assert merged[0]["build_residues"] == [10]

def _build_prompt_for(chain_entry):
    metadata = {"WAT": "TIP3P", "TEMP": 300, "ENSEMBLE": "NPT",
                "FF": ["Amber ff14SB"]}
    return tb.build_prompt("t", "Protein", "1ABC", metadata, [chain_entry],
                           {}, [], 1.0)


def test_build_prompt_writes_nothing_from_a_bare_count():
    """Through build_prompt, not the helper.

    The helper tests above pin _validated_build_sites. This pins the caller: if
    build_prompt regained a build_missing fallback of its own they would all
    still pass, and prose generated from that count is what told an agent to add
    residues seven references do not have.
    """
    text = _build_prompt_for(
        {"deposit_chain": "A", "ranges": [["16", "214"]], "build_missing": 1})
    assert "does not resolve" not in text
    assert "build them" not in text.lower()


def test_build_prompt_writes_the_named_sites_with_their_chain():
    text = _build_prompt_for(
        {"deposit_chain": "C", "ranges": [["5", "211"]],
         "build_missing": 3, "build_residues": [83, 84, 85]})
    assert ("Chain C does not resolve residues 83, 84, 85; the range runs "
            "through them, so build them.") in text


def test_build_prompt_writes_the_singular_for_one_site():
    text = _build_prompt_for(
        {"deposit_chain": "A", "ranges": [["1", "100"]],
         "build_missing": 1, "build_residues": [42]})
    assert "does not resolve residue 42;" in text


def test_build_prompt_refuses_a_site_its_own_prompt_omits():
    """011_membrane_6kuy's shape, refused at the point the text is written."""
    with pytest.raises(ValueError, match="both built and omitted"):
        _build_prompt_for(
            {"deposit_chain": "A", "ranges": [["1", "100"]],
             "omitted": [(10, 12)], "build_missing": 1, "build_residues": [10]})


def test_an_omitted_modified_residue_is_not_restored():
    """6ME3 excludes YCM1004; it must not also request CYS1004."""
    metadata = {"WAT": "TIP3P", "TEMP": 310, "ENSEMBLE": "NPT"}
    chain = {"deposit_chain": "A", "ranges": [["1001", "1196"]],
             "omitted": [["1004", "1004"]]}
    text = tb.build_prompt(
        "t", "Protein", "6ME3", metadata, [chain],
        [{"name": "YCM", "parent": "CYS", "chain": "A", "residue": "1004"}],
        [], 1.0,
    )

    assert "Residue 1004 (YCM) is not part of the reference" in text
    assert "modified CYS" not in text


def test_excluded_components_are_named_in_the_prompt():
    metadata = {"WAT": "TIP3P", "TEMP": 310, "ENSEMBLE": "NPT"}
    chains = [{"deposit_chain": "A", "ranges": [["2", "129"]]}]
    text = tb.build_prompt(
        "t", "Complex with a bound imido", "1FFW", metadata, chains, {}, [], 2.5,
        excluded_components=("PON", "MN"),
    )

    assert "**PON** and **MN** are not part of the reference" in text
    assert "Simulate the protein without them." in text

    plain = tb.build_prompt("t", "Complex", "1FFW", metadata, chains, {}, [], 2.5)
    assert "not part of the reference. Simulate the protein without" not in plain
