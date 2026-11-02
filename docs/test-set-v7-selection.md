# Held-out test set v7: selection rule and result (2026-11-01)

Status: **sealed.** test-v7 is 30 new tasks, 131–160, split `test_v7`, in
dataset v0.7. They were built and checked, and they are committed locally. They
are **not to be run** until that is decided: no campaign, no `init_experiment`
beyond the one dry init of Part 4, and no MDClaw run on any of them.

Why a second set. Test sets are single-use (the user's decision of
2026-11-01). Test-v6 (tasks 101–130, split `test`, `docs/test-set-selection.md`)
was run once on a frozen MDClaw, and its failures were then used to fix MDClaw
(mdclaw commits after `ac0e328`; memo 2026-10-31 (3) and (4)). So v6 is now
development data. test-v7 is the lockbox for the next frozen MDClaw.

Part 1 is v7's rule. It was written down before the v7 selection was run.
Part 2 is the result, Part 3 the build and Part 4 the verification.

## Part 1 — the rule (pre-registered)

The rule is v6's rule v4 (`docs/test-set-selection.md`, Part 1 and the build
rules of Part 3), applied again. The only changes are the ones listed under
"What v7 changes". The section numbers below are v6's.

### What stays exactly as v6

- **Integrity (1.1).**
  - Inputs: MDDB metadata, files and analyses; RCSB deposits and entry
    metadata; and, for the exclusion set only, MDPrepBench, MDStudyBench and the
    mdclaw checkout text.
  - No MDClaw, pi, agent, `run_experiment` or MD on any candidate.
  - No campaign result (`/data1/rkp00079/rku00161/runs*`) read, the test-v6
    campaigns included.
  - Deterministic: ties go to the smaller `(node, accession)`.
- **Eligibility (1.2).** The same filters, in the same order.
- **Categories (1.3).** The same definitions, the same Ig V-domain recogniser
  and the same precedence. Quotas: membrane 4, antibody 3, complex 4,
  nanobody 3, ligand 4, nucleic 4, metal 2, soluble_charmm 3 (ATLAS),
  soluble_amber 3 (MoDEL).
- **Sequence distinctness (1.4).**
  - Protein chains use 3-mers and DNA/RNA chains 6-mers.
  - Containment must be < 0.70 for the whole system and for every chain of
    ≥ 30 residues. Ig chains are compared through their V domain only.
  - No PDB ID may be shared with the development set.
- **Size caps (1.5).** The same table: the largest task of the axis among the
  98.
- **Verification (1.6).**
  - SEQRES alignment, and `selection()` must accept the record.
  - Residue rule: standard residues, named ionisation variants, modified
    residues reverted to their parent, and terminal caps at chain ends only.
  - Stability from MDDB's `rmsds`: last-third mean ≤ 4.0 Å, strictly.
  - Category content checked on the reference, and distinctness checked again
    on the reference's own sequences.
- **Obsolete RCSB entries out** (1.10, v3).
- **Diversity (1.7).** The same distance, scarcest pool first, soluble last.
  Slots a category cannot fill go to soluble, alternating ATLAS first over all
  moved slots. Rule 1 holds across categories.
- **Reserves (1.8).** 3 per category, continued from the same greedy and taken
  strictly in order.
- **Build (Part 3).**
  - `scripts/build_test_tasks.py`. Contracts are derived, never hand-written.
    Prompts come only from `_task_builder.build_prompt`.
  - The shared scoring block. The radius-of-gyration demotion applies when its
    headroom is below 4.
  - Calibration with the explicit cast window: 1 ns, 2.5 ns on inr.
  - The ligand SMILES declaration for non-polymer contract atoms
    (`contract_ligand_declarations`, memo 2026-10-31 (3)).
  - The bound-cation rule (`bound_solvent_cations` / `selection.bound_ions`,
    memo 2026-10-31 (4)).
  - The extended deny list.
  - A pick the builder cannot state precisely is replaced by the next reserve
    of its category, and the replacement is recorded. 2AF1 (symmetry-mate
    duplex) and 1PNE (kept ACE cap) carry over as known cases, because they are
    limits of the builder, not of v6.
- **Dispatch order and numbering.** membrane, ligand, metal, complex, nucleic,
  nanobody, antibody, ATLAS, MoDEL. Within a category, greedy pick order.

### What v7 changes

1. **The development set widens** to:
   - everything v6 excluded: the 98, 038, 061, D03 = 1EDN, MDPrepBench's 30 PDB
     IDs and MDStudyBench S01;
   - the 30 test-v6 tasks 101–130, compared through their MDDB reference
     sequences from their bundles, as the cast is;
   - every PDB entry mentioned in the mdclaw checkout. The checkout is read
     from the git tree of `6524d3e` (`/home/rku00161/mdclaw` HEAD on
     2026-11-01), not the working tree, so that the scan is reproducible.
     - Against v6's tree (`ac0e328`), it has 5 new tokens: 1HLV, 3K1R, 5SXP,
       6MJ7 and 6RNT. All five are test-v6 task ids in tests and in
       `docs/memo.md`, so they are mentions.
     - No new token is a non-PDB string, so `MDCLAW_NOT_PDB` is v6's 19.
   - The external sources were re-read on 2026-11-01 and are unchanged:
     - MDPrepBench (the read-only copy under `/data1/rkp00048`) still has 40
       tasks with 30 PDB IDs;
     - MDStudyBench `main` is still `f04519f` (2026-08-09), with S01 only. v7
       pins that commit.
   - v6's unused reserves, and 2AF1 and 1PNE (v6 picks that were never built
     or run), are **not** excluded. No MDClaw ever ran on them. They enter v7
     only if v7's greedy reaches them.
2. **Diversity anchors.** v6's anchors were "the tasks of the same axis among
   the 98", the MDDB tasks MDClaw had been developed against. In v7 the test-v6
   tasks are such tasks too. So the anchors of a category are the 98 **and the
   v6 tasks** of that axis.
   - The size caps stay those of the 98. v6's picks are within them, so
     including them would change nothing.
   - The withdrawn tasks, 1EDN and the external entries are still not anchors.
   - As a sensitivity record only, the same selection is also run with the 98
     alone as anchors (`selected_anchors98.json`). It does not choose anything.
3. **Population date.** The node listings are fetched fresh on 2026-11-01.
   - Since the v6 scan, cin grew from 7598 to 7650 projects and ufl from 5971
     to 6084; the other nodes are unchanged.
   - The node set is v6's: all eight are asked.
     - **oxf did not answer on 2026-11-01**, as on 2026-10-31: the TCP connect
       timed out in a 60 s probe and in the scan's three 120 s attempts.
     - ufl is scanned but feeds no category, as in v6.
   - Per-entry data that does not change between the two days was copied from
     v6's cache:
     - MDDB reference structures, `rmsds` analyses and project records;
     - RCSB PDB-format deposits, entry metadata and chemical components.
   - No RCSB weekly release falls between Saturday 2026-10-31 and Sunday
     2026-11-01 (releases are on Wednesdays).
   - The RCSB entity sequences of the external entries were fetched again for
     v7's ID set.
4. **Numbering and version.**
   - Ids 131–160, in v6's dispatch order.
   - `split: "test_v7"`, retrieval date 2026-11-01, dataset `MDDataBench-v0.7`.
   - The v6 tasks keep split `test`. Their text and contracts are unchanged.
5. **Code.** The four scripts take `--set v7`. Every per-set parameter lives in
   `scripts/heldout_sets.py`, and `v6` is the default. A `--set v6` rerun on a
   copy of v6's inputs reproduces v6's `selected.json` (every key except
   `generated`) and its 115-attempt `selection_log.json` exactly
   (`tests/test_benchmark/test_heldout_sets.py` pins the parameters, the
   numbering, the mdclaw mentions and the finalize idempotence).
   - Two defects of the v6 scripts would have changed a v6 rerun once v6's
     tasks were in the tree, and both are fixed:
     - the cast was every `task.json`, so the 30 test tasks would have become
       anchors and exclusions of their own rerun;
     - the mdclaw scan read the working tree, which has moved on since
       `ac0e328`.
   - `finalize` reset `dataset_id` to its own version whenever it differed,
     the defect the apply scripts had. It now bumps only from an older version.

Work directory: `/data1/rkp00079/rku00161/testset-v7-20261101`, with the same
layout as v6's.

## Part 2 — the result

Output: `/data1/rkp00079/rku00161/testset-v7-20261101/selection/selected.json`
(30 picks and 21 reserves, with their verification records and `selection()`
results) and `selection_log.json` (all 123 attempts in greedy order). The
listing counts are in `pool_counts.json`.

### 2.1 Population

| Filter | Remaining | mmb | cin | bsc | inr | jsc | rpbs | ufl |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all projects (7 nodes answered) | 34943 | 9372 | 7650 | 5491 | 930 | 5406 | 10 | 6084 |
| `METHOD == "Classical MD"` | 34477 | 8943 | 7649 | 5491 | 930 | 5406 | 2 | 6056 |
| all-atom | 30966 | 5432 | 7649 | 5491 | 930 | 5406 | 2 | 6056 |
| PDB ID present | 25622 | 2575 | 5167 | 5491 | 928 | 5405 | 0 | 6056 |
| water TIP3P/OPC/OPC3/TIP4P-Ew/SPC/E | 25496 | 2449 | 5167 | 5491 | 928 | 5405 | 0 | 6056 |
| numeric `TEMP` | 20505 | 2417 | 214 | 5491 | 928 | 5405 | 0 | 6050 |
| topology prmtop/tpr/psf/top | 11528 | 2178 | 214 | 2150 | 928 | 8 | 0 | 6050 |
| `fluctuation` + `rgyr` analyses | 11501 | 2162 | 213 | 2149 | 928 | 8 | 0 | 6041 |
| ≥ 10 windows × ≥ 25 frames | 10996 | 1885 | 213 | 1938 | 922 | 0 | 0 | 6038 |
| exactly one PDB ID | 10992 | 1881 | 213 | 1938 | 922 | 0 | 0 | 6038 |
| open licence | **10979** | 1880 | 201 | 1938 | 922 | 0 | 0 | 6038 |

- The 52 projects cin added since the v6 scan all lack a numeric `TEMP`, so cin's
  eligible pool is v6's.
- **Every one of v6's 10866 eligible records is unchanged**, field for field.
  The only additions are 113 ufl projects, and ufl feeds no category.
- oxf did not answer (1.2 of Part 1).

### 2.2 Category pools

The development set has 322 members:
- 131 MDDB tasks: the 98, the 30 v6 tasks, and 038, 061 and 1EDN;
- 191 external entries: MDPrepBench ∪ the 176 mdclaw mentions at `6524d3e`
  (190 PDB IDs), plus MDStudyBench S01.

| Pool step | membrane | antibody | complex | nanobody | ligand | nucleic | metal | soluble_charmm | soluble_amber |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| categorised | 55 | 39 | 407 | 220 | 193 | 56 | 13 | 1938 | 1530 |
| PDB ID not in the development set | 40 | 27 | 395 | 208 | 181 | 33 | 7 | 1906 | 1497 |
| atoms and polymer residues within the category's largest cast task | 21 | 18 | 333 | 172 | 131 | 33 | 7 | 1717 | 1413 |
| whole-system containment < 0.70 vs the development set (MDDB sequences) | 1 | 15 | 288 | 123 | 87 | 30 | 3 | 1692 | 1353 |
| every chain ≥ 30 residues < 0.70 vs every development-set chain (Ig: V domain) | 0 | 13 | 284 | 123 | 87 | 30 | 3 | 1688 | 1348 |
| deposit is a current RCSB entry | **0** | **13** | **284** | **123** | **87** | **30** | **3** | **1687** | **1339** |

Processing order (scarcest first): membrane 0, metal 3, antibody 13,
nucleic 30, ligand 87, nanobody 123, complex 284, then ATLAS and MoDEL.

**Picks: antibody 3, complex 4, nanobody 3, ligand 4, nucleic 4, ATLAS 6,
MoDEL 6. Membrane 0 of 4 and metal 0 of 2. Their six slots went to soluble:
ATLAS, MoDEL, ATLAS, MoDEL (membrane), then ATLAS, MoDEL (metal).**

- **Membrane, none.** v6's only distinct membrane system, 7DFP, is now
  development data.
  - The one candidate left after the whole-system rule, 6OIJ (M1 receptor–G11),
    fails the chain rule at 1.00 against 6OT0 (Gβ1/Gγ2/scFv16), which the mdclaw
    checkout documents (v6 2.1).
  - There is no membrane reserve.
- **Metal, none.** With 6RNT now development data, the 3 left are the systems
  v6 already rejected: 2I3H (6.09 Å), 2BFR (Ca not bound) and 8CPA (no `rmsds`).
  There is no metal reserve.
- 123 attempts: 30 kept as picks, 21 kept as reserves, 72 dropped:
  - 46 unstable references (4.03–120.6 Å; 1UTG at 4.032 Å and 437D at 4.08 Å
    are out under the strict cut);
  - 14 with a reference chain unexplained against SEQRES: 4DW2, 4M5Z, 1Q9A, six
    1VTN replicas, four 2UZK replicas, 2OR1;
  - 6 that keep a non-standard polymer residue: 2OUE, 1JLP (HYP), and 1WGB,
    1AT0, 1DUS and 1OUO (MSE);
  - 4 that are not a single chain (1CHO, 1ACB, 2J6O, 1SV4);
  - 1 whose metal is not bound (2BFR);
  - 1 without `rmsds` (8CPA).
- **Overlap with v6's lists.** This follows from running the same greedy over
  the same pool with v6's picks added as anchors.
  - All 19 of v6's unused reserves are v7 picks.
  - v6's two replaced picks, 2AF1 and 1PNE, are picked again (the builder
    replaces them again, Part 3).
  - 9 picks are new to both lists: 1A0A, 5I7X, 5GY2, 2X9O, 2FP1, 1D4T, 1EDG,
    1CS6 and 1CEX. Every v7 reserve is new.
- The largest whole-system containment between two picks is 0.48
  (4ETQ–5X0T, two Fab complexes that share constant domains). Next come
  0.44 and 0.38, among the nanobodies.
- **Sensitivity: anchors = the 98 only** (`selected_anchors98.json`, not used).
  - 19 of the 30 picks would differ:
    - complex 3, ligand 3, nanobody 2, nucleic 1, ATLAS 5, MoDEL 5;
    - the same categories fill, with the same shortfall.
  - So the anchor decision of Part 1 (change 2) is not cosmetic. It moves v7
    away from v6 in feature space, which is its purpose.

### 2.3 The 30 picks and the reserves

Columns as in v6 2.2. "max C vs v6" is the largest containment against the 30
v6 tasks (whole / chain).

| # | Category | PDB | node:accession | Title | res / chains / atoms | FF, water, T, ensemble | window ns | rep | RMSD Å (drift) | max C vs 98 | max C vs v6 | max C vs dev. set | Selection (deposit numbering) |
|---|---|---|---|---|---|---|---:|---:|---|---|---|---|---|
| 1 | antibody | 4ETQ | inr:A00LI | Vaccinia virus D8L IMV envelope protein in complex with F… | 664 / 3 / 10270 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 2.64 (+0.37) | 0.52 / 0.37 | 0.32 / 0.37 | 0.52 / 0.37 | A:2–220; L:2–213; X:3–235 |
| 2 | antibody | 5O14 | inr:A00LR | Co-crystal structure of a cross-reactive bactericidal hum… | 676 / 3 / 10203 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 3.46 (+0.38) | 0.55 / 0.65 | 0.55 / 0.36 | 0.56 / 0.65 | B:14–255; D:1–212; C:1–222 |
| 3 | antibody | 5X0T | inr:A00LW | Crystal structure of CD147 C2 domain in complex with Fab… | 506 / 3 / 7662 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 2.93 (+0.00) | 0.54 / 0.40 | 0.35 / 0.42 | 0.54 / 0.42 | A:21–235; B:21–233; E:25–102 |
| 4 | nucleic | 2AF1 | mmb:A017K | Structure of the DNA coiled-coil formed by d(CGATATATATAT) | 24 / 2 / 764 | n.r., TIP3P, 300 K, None | 1 | 1 | 3.44 (+0.91) | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | A:1–12,1–12 |
| 5 | nucleic | 4F6N | mmb:A01E2 | Crystal structure of Kaiso zinc finger DNA binding protei… | 38 / 2 / 1203 | n.r., TIP3P, 300 K, None | 1 | 1 | 3.13 (+0.02) | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | E:20–38; D:1–19 |
| 6 | nucleic | 1VTN | mmb:A01DQ | CO-CRYSTAL STRUCTURE OF THE HNF-3/FORK HEAD DNA-RECOGNITI… | 26 / 2 / 824 | n.r., TIP3P, 300 K, None | 1 | 1 | 2.27 (+0.02) | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | A:1–13; B:21–33 |
| 7 | nucleic | 1A0A | mmb:A01DD | PHOSPHATE SYSTEM POSITIVE REGULATORY PROTEIN PHO4/DNA COM… | 34 / 2 / 1076 | n.r., TIP3P, 300 K, None | 1 | 1 | 2.41 (+0.12) | 0.00 / 0.00 | 0.00 / 0.00 | 0.09 / 0.00 | D:1–17; C:1–17 |
| 8 | ligand | 2PQL | cin:A00BY | Crystal Structure of Anopheles gambiae D7R4-tryptamine co… | 144 / 1 / 2393 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1 | 1 | 2.09 (-0.03) | 0.12 / 0.10 | 0.12 / 0.08 | 0.22 / 0.20 | A:1–144 |
| 9 | ligand | 3G19 | cin:A00HP | The structure of the Caulobacter crescentus clpS protease… | 84 / 1 / 1431 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1 | 1 | 2.23 (+0.19) | 0.12 / 0.10 | 0.09 / 0.07 | 0.27 / 0.24 | A:36–119 |
| 10 | ligand | 1KJR | cin:A00IF | Crystal Structure of the human galectin-3 CRD in complex… | 138 / 1 / 2298 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1 | 1 | 1.44 (+0.08) | 0.15 / 0.12 | 0.10 / 0.08 | 0.29 / 0.18 | A:113–250 |
| 11 | ligand | 5I7X | cin:A00E2 | BRD9 in complex with Cpd2 (N,N-dimethyl-3-(6-methyl-7-oxo… | 100 / 1 / 1678 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1 | 1 | 3.16 (+0.69) | 0.16 / 0.12 | 0.11 / 0.08 | 0.26 / 0.33 | A:23–122 |
| 12 | nanobody | 6IR2 | mmb:A0598 | Crystal structure of red fluorescent protein mCherry comp… | 124 / 1 / 1852 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1 | 3 | 1.50 (+0.18) | 0.48 / 0.48 | 0.50 / 0.50 | 0.67 / 0.59 | B:16–139 |
| 13 | nanobody | 6X05 | mmb:A059P | Nup133 (aa55-481) from S. cerevisiae bound by VHH-SAN4 | 120 / 1 / 1831 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1 | 3 | 2.16 (+0.27) | 0.38 / 0.36 | 0.40 / 0.40 | 0.53 / 0.41 | K:3–122 |
| 14 | nanobody | 6B73 | mmb:A058W | Crystal Structure of a nanobody-stabilized active state o… | 121 / 1 / 1821 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1 | 3 | 2.66 (+0.34) | 0.44 / 0.38 | 0.41 / 0.41 | 0.58 / 0.46 | C:4–124 |
| 15 | complex | 3O6Q | inr:A005M | The Structure of SpoIISA and SpoIISB, a Toxin - Antitoxin… | 376 / 4 / 6194 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 2.45 (+0.34) | 0.18 / 0.15 | 0.10 / 0.12 | 0.28 / 0.32 | A:97–241; B:9–51; C:98–241; D:9–52 |
| 16 | complex | 4KT5 | inr:A007O | Structure of GrlR-GrlA complex | 317 / 3 / 5142 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 3.36 (+0.42) | 0.16 / 0.14 | 0.11 / 0.08 | 0.27 / 0.28 | A:-2–112; B:1–114; C:9–96 |
| 17 | complex | 6B12 | inr:A00AI | Structure of Tne2 in complex with Tni2 | 272 / 2 / 4265 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 2.02 (+0.10) | 0.16 / 0.25 | 0.11 / 0.10 | 0.28 / 0.25 | A:290–408; B:1–153 |
| 18 | complex | 5GY2 | inr:A00BJ | Crystal structure of a complex between Bacillus subtilis… | 611 / 2 / 9512 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 2.73 (+0.52) | 0.18 / 0.29 | 0.21 / 0.19 | 0.32 / 0.29 | A:23–464; C:54–222 |
| 19 | soluble_charmm | 1HOE | bsc:A02N0 | CRYSTAL STRUCTURE DETERMINATION, REFINEMENT AND THE MOLEC… | 74 / 1 / 1076 | CHARMM36m, TIP3P, 300 K, None | 1 | 3 | 3.45 (+1.64) | 0.21 / 0.12 | 0.11 / 0.07 | 0.30 / 0.17 | A:1–74 |
| 20 | soluble_charmm | 5N76 | bsc:A03TC | Crystal structure of the apo-form of the CO dehydrogenase… | 66 / 1 / 1005 | CHARMM36m, TIP3P, 300 K, None | 1 | 3 | 3.47 (+0.36) | 0.22 / 0.14 | 0.17 / 0.12 | 0.38 / 0.25 | B:1–66 |
| 21 | soluble_charmm | 7ONN | bsc:A040V | Crystal structure of PBP3 transpeptidase domain from E. c… | 410 / 1 / 6191 | CHARMM36m, TIP3P, 300 K, None | 1 | 3 | 2.72 (+0.47) | 0.18 / 0.19 | 0.15 / 0.13 | 0.33 / 0.25 | A:68–570 |
| 22 | soluble_charmm | 2X9O | bsc:A035Q | STRUCTURE OF 15, 16- DIHYDROBILIVERDIN:FERREDOXIN OXIDORE… | 244 / 1 / 3871 | CHARMM36m, TIP3P, 300 K, None | 1 | 3 | 3.80 (+0.84) | 0.14 / 0.14 | 0.12 / 0.25 | 0.32 / 0.25 | A:-7–236 |
| 23 | soluble_charmm | 2FP1 | bsc:A02YH | Secreted Chorismate Mutase from Mycobacterium tuberculosis | 166 / 1 / 2564 | CHARMM36m, TIP3P, 300 K, None | 1 | 3 | 2.58 (+0.15) | 0.13 / 0.10 | 0.11 / 0.07 | 0.33 / 0.24 | A:34–199 |
| 24 | soluble_charmm | 1D4T | bsc:A02L6 | CRYSTAL STRUCTURE OF THE XLP PROTEIN SAP IN COMPLEX WITH… | 104 / 1 / 1653 | CHARMM36m, TIP3P, 300 K, None | 1 | 3 | 2.16 (-0.09) | 0.19 / 0.13 | 0.16 / 0.12 | 0.33 / 0.24 | A:1–104 |
| 25 | soluble_amber | 1PNE | mmb:A00U8 | CRYSTALLIZATION AND STRUCTURE DETERMINATION OF BOVINE PRO… | 139 / 1 / 2097 | Amber Parm99, TIP3P, 300 K, NPT | 1 | 1 | 2.85 (+1.06) | 0.16 / 0.14 | 0.10 / 0.10 | 0.29 / 0.21 | A:1–139 |
| 26 | soluble_amber | 1A5D | mmb:A004D | GAMMAE CRYSTALLIN FROM RAT LENS | 173 / 1 / 2849 | Amber Parm99, TIP3P, 300 K, NPT | 1 | 1 | 1.93 (+0.31) | 0.11 / 0.08 | 0.08 / 0.10 | 0.23 / 0.15 | A:1–174 |
| 27 | soluble_amber | 1HP9 | mmb:A00JB | kappa-Hefutoxins: a novel Class of Potassium Channel Toxi… | 22 / 1 / 337 | Amber Parm99, TIP3P, 300 K, NPT | 1 | 1 | 2.63 (+0.36) | 0.20 / 0.00 | 0.10 / 0.00 | 0.20 / 0.00 | A:1–22 |
| 28 | soluble_amber | 1EDG | mmb:A00DP | SINGLE CRYSTAL STRUCTURE DETERMINATION OF THE CATALYTIC D… | 380 / 1 / 5937 | Amber Parm99, TIP3P, 300 K, NPT | 1 | 1 | 2.87 (+0.61) | 0.13 / 0.12 | 0.12 / 0.15 | 0.26 / 0.20 | A:1–380 |
| 29 | soluble_amber | 1CS6 | mmb:A00AF | N-TERMINAL FRAGMENT OF AXONIN-1 FROM CHICKEN | 382 / 1 / 5900 | Amber Parm99, TIP3P, 300 K, NPT | 1 | 1 | 2.16 (+0.22) | 0.16 / 0.16 | 0.15 / 0.27 | 0.34 / 0.27 | A:7–388 |
| 30 | soluble_amber | 1CEX | mmb:A008J | STRUCTURE OF CUTINASE | 197 / 1 / 2867 | Amber Parm99, TIP3P, 300 K, NPT | 1 | 1 | 2.45 (+0.35) | 0.15 / 0.25 | 0.15 / 0.10 | 0.32 / 0.33 | A:17–213 |

| rank | Category | PDB | node:accession | Title | res / chains / atoms | FF, water, T, ensemble | window ns | rep | RMSD Å (drift) | max C vs 98 | max C vs v6 | max C vs dev. set | Selection (deposit numbering) |
|---|---|---|---|---|---|---|---:|---:|---|---|---|---|---|
| 1 | antibody | 3MJ9 | inr:A00L9 | Crystal structure of JAML in complex with the stimulatory… | 656 / 3 / 9989 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 2.77 (-0.12) | 0.34 / 0.43 | 0.30 / 0.35 | 0.39 / 0.43 | A:8–236; L:2–212; H:1–228 |
| 2 | antibody | 5C7X | inr:A00LN | Crystal structure of MOR04357, a neutralizing anti-human… | 540 / 3 / 8118 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 2.79 (+0.44) | 0.68 / 0.69 | 0.55 / 0.50 | 0.68 / 0.69 | B:9–124; L:1–208; H:1–214 |
| 3 | antibody | 6A77 | inr:A00LZ | Crystal structure of the fifth immunoglobulin domain (Ig5… | 519 / 3 / 7778 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 2.42 (+0.41) | 0.49 / 0.38 | 0.42 / 0.37 | 0.49 / 0.41 | A:7–97; L:1–211; H:-1–217 |
| 1 | nucleic | 2STW | mmb:A01DY | SOLUTION NMR STRUCTURE OF THE HUMAN ETS1/DNA COMPLEX, RES… | 34 / 2 / 1076 | n.r., TIP3P, 300 K, None | 1 | 1 | 2.13 (+0.02) | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | C:18–34; B:1–17 |
| 2 | nucleic | 1R4I | mmb:A01DP | Crystal Structure of Androgen Receptor DNA-Binding Domain… | 36 / 2 / 1142 | n.r., TIP3P, 300 K, None | 1 | 1 | 3.16 (+0.06) | 0.17 / 0.00 | 0.00 / 0.00 | 0.17 / 0.00 | C:1–18; D:19–36 |
| 3 | nucleic | 1YO5 | mmb:A01DR | Analysis of the 2.0A crystal structure of the protein-DNA… | 26 / 2 / 824 | n.r., TIP3P, 300 K, None | 1 | 1 | 2.08 (-0.23) | 0.12 / 0.00 | 0.00 / 0.00 | 0.12 / 0.00 | B:1–13; A:1–13 |
| 1 | ligand | 3QXV | cin:A00E1 | Structure of an Anti-Methotrexate CDR1-4 Graft VHH Antibo… | 123 / 1 / 1908 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1 | 1 | 1.80 (+0.25) | 0.47 / 0.47 | 0.45 / 0.45 | 0.66 / 0.59 | A:4–131 |
| 2 | ligand | 5EQ1 | cin:A00IS | Crystal structure of the human BRPF1 bromodomain in compl… | 112 / 1 / 1891 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1 | 1 | 1.89 (-0.11) | 0.14 / 0.14 | 0.19 / 0.14 | 0.32 / 0.19 | A:628–739 |
| 3 | ligand | 3KIV | cin:A000G | RECOMBINANT KRINGLE IV-10/M66 VARIANT OF HUMAN APOLIPOPRO… | 79 / 1 / 1228 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1 | 1 | 3.03 (+1.43) | 0.21 / 0.21 | 0.05 / 0.04 | 0.30 / 0.22 | A:0–80 |
| 1 | nanobody | 7OMM | mmb:A05AQ | Cryo-EM structure of N. gonorhoeae LptDE in complex with… | 118 / 1 / 1811 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1 | 3 | 2.16 (+0.09) | 0.52 / 0.52 | 0.53 / 0.53 | 0.69 / 0.67 | C:5–122 |
| 2 | nanobody | 7A4D | mmb:A059U | Crystal structure of the APH coiled-coil in complex with… | 113 / 1 / 1702 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1 | 2 | 2.53 (+0.02) | 0.44 / 0.41 | 0.48 / 0.48 | 0.66 / 0.57 | C:3–115 |
| 3 | nanobody | 7APJ | mmb:A059V | Structure of autoinhibited Akt1 reveals mechanism of PIP3… | 114 / 1 / 1745 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1 | 2 | 1.71 (-0.10) | 0.41 / 0.39 | 0.47 / 0.47 | 0.68 / 0.54 | B:3–116 |
| 1 | complex | 2D10 | inr:A002T | Crystal structure of the Radixin FERM domain complexed wi… | 315 / 2 / 5295 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 3.68 (+0.65) | 0.17 / 0.14 | 0.11 / 0.11 | 0.26 / 0.18 | A:3–297; E:339–358 |
| 2 | complex | 1I51 | inr:A000Y | CRYSTAL STRUCTURE OF CASPASE-7 COMPLEXED WITH XIAP | 498 / 6 / 7884 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 2.04 (+0.06) | 0.14 / 0.13 | 0.10 / 0.10 | 0.27 / 0.33 | A:58–196; B:212–303; C:58–196; D:212–303; E:135–152; F:135–152 |
| 3 | complex | 1KAC | inr:A0018 | KNOB DOMAIN FROM ADENOVIRUS SEROTYPE 12 IN COMPLEX WITH D… | 309 / 2 / 4718 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 3.15 (+0.21) | 0.15 / 0.12 | 0.13 / 0.13 | 0.32 / 0.21 | A:403–587; B:23–146 |
| 1 | soluble_charmm | 1KPT | bsc:A02OH | STRUCTURE AND FUNCTION OF A VIRALLY ENCODED FUNGAL TOXIN… | 105 / 1 / 1491 | CHARMM36m, TIP3P, 300 K, None | 1 | 3 | 1.56 (+0.33) | 0.16 / 0.10 | 0.12 / 0.15 | 0.26 / 0.20 | A:1–105 |
| 2 | soluble_charmm | 2PEF | bsc:A032C | Crystal Structure of a Thermophilic Serpin, Tengpin, in t… | 373 / 1 / 5949 | CHARMM36m, TIP3P, 300 K, None | 1 | 3 | 2.54 (+0.62) | 0.16 / 0.18 | 0.14 / 0.25 | 0.26 / 0.25 | A:51–423 |
| 3 | soluble_charmm | 2PV4 | bsc:A032U | CRYSTAL STRUCTURE OF AN UNCHARACTERIZED PROTEIN FROM DUF3… | 145 / 1 / 2290 | CHARMM36m, TIP3P, 300 K, None | 1 | 3 | 3.21 (+0.42) | 0.17 / 0.14 | 0.15 / 0.08 | 0.30 / 0.25 | A:0–144 |
| 1 | soluble_amber | 1QIB | mmb:A00XJ | CRYSTAL STRUCTURE OF GELATINASE A CATALYTIC DOMAIN | 161 / 1 / 2456 | Amber Parm99, TIP3P, 300 K, NPT | 1 | 1 | 2.73 (+0.73) | 0.19 / 0.19 | 0.09 / 0.08 | 0.36 / 0.33 | A:88–250 |
| 2 | soluble_amber | 1AH0 | mmb:A000K | PIG ALDOSE REDUCTASE COMPLEXED WITH SORBINIL | 315 / 1 / 5045 | Amber Parm99, TIP3P, 300 K, NPT | 1 | 1 | 1.90 (+0.43) | 0.15 / 0.14 | 0.12 / 0.16 | 0.26 / 0.33 | A:1–315 |
| 3 | soluble_amber | 1KRN | mmb:A00RW | STRUCTURE OF KRINGLE 4 AT 4C TEMPERATURE AND 1.67 ANGSTRO… | 79 / 1 / 1201 | Amber Parm99, TIP3P, 300 K, NPT | 1 | 1 | 1.75 (+0.20) | 0.20 / 0.20 | 0.08 / 0.03 | 0.25 / 0.20 | A:65–143 |

## Part 3 — building the 30 contracts

Same integrity rules as Part 1. Everything was produced by
`scripts/build_test_tasks.py --set v7`, which runs v6's derivation unchanged.
- Bundles were fetched into `/data1/rkp00079/rku00161/references/<node>_<accession>`.
- The mmCIF deposits went into `benchmarks/mddatabench/_deposits` (30 new
  files).
- Calibration used the cast window (1 ns; 2.5 ns on inr) at slack 4, with at
  most 4 workers.
- Drafts were built and audited before the dataset was written. The final
  prompts are byte-identical to the audited drafts, and the contracts differ
  from them only in `md_calibration`.

### 3.1 Replacements

Eight picks, and three reserves taken for them, could not be stated precisely
by the builder. Each was replaced by the next reserve of its category,
strictly in order.
- 2AF1 and 1PNE are v6's known cases. v7's own drafts of them (`999_*` in
  `build/audit_draft.json`) give v6's audit findings again.
- 7ONN was found by the build-missing classifier of the test suite (below).
- All others were found by v7's drafts, the contract audit and the Rg check
  below.

The reasons are in `scripts/heldout_sets.py` (`V7.not_statable`) and in
`build/build_report.json`.

| slot | replaced | by | why |
|---|---|---|---|
| ligand 2 | 3G19 | **3QXV** | The reference `LIG` is the deposit's Leu-Leu-Leu tripeptide (polymer chain C), which MDDB flattened into one residue, as for the cast's 042. No non-polymer component has its formula, so the ligand bullet cannot name it, and the builder has no sentence for a kept peptide chain. The draft stopped: "reference LIG matches deposit components none by heavy-atom formula". |
| ligand 3 | 1KJR | **5EQ1** | The reference `LIG` (C22H28F4N2O12) is one residue made of three deposit components: the NAG–GAL of branched entity B and the BEK tetrafluorobenzamide bonded to it. No single component matches. |
| complex 1 | 3O6Q | **2D10** | The deposit bonds two inter-chain disulfides, A:Cys161–B:Cys9 and C:Cys161–D:Cys9, that the reference leaves reduced. The builder states disulfide differences only within one chain (`inter-chain disulfide (65, 146) cannot be stated`). |
| complex 3 | 6B12 | **1I51** | The deposit holds two copies of the complex: Tne2 A with Tni2 C, and Tne2 D with Tni2 B. The builder pairs A with B, which are 15 Å apart (audit: `deposit_polymer_chains_do_not_contact`; selection Rg 28.8 Å against the reference's 19.1 Å). It picks each chain's twin on its own and has no contact-based choice; choosing by hand would make the contract hand-written (the cast's 029 did so). |
| nucleic 1 | 2AF1 | **2STW** | v6's case: a symmetry-mate duplex (audit: 12 selected sites against 24 in the reference). |
| antibody 1 | 4ETQ | 3MJ9 → 5C7X → 6A77 → **none** | **4ETQ.** The deposit holds two Fab–antigen complexes (H+L+C and A+B+X). The builder selects A, L and X, chains of both copies: L is 43 Å from X, and the selection's Rg is 47.6 Å against the reference's 31.9 Å. The audit passed it, because some selected pair does touch. |
| | | | **3MJ9.** The heavy chain's Kabat insertion codes are mapped out of order, so the prompt swaps residues 82 and 82A as two "substitutions" on a chain that matches SEQRES exactly. Its substitution and glycosylation sentences name no chain, and the audit finds 8 built residues the prompt does not state. |
| | | | **5C7X.** The same insertion-code swap, at 52–52C. The selection mixes two copies (Rg 32.3 Å against 28.7 Å), the disulfide sentences contradict each other (L Cys23 is both bonded and free), and the audit flags it. |
| | | | **6A77.** The reference leaves out four unobserved CH1-loop residues of chain H (SEQRES 137–140) and bonds across the gap. The builder writes that as "135–136 omitted and joined"; the audit counts 523 selected sites against 519. |
| | | | **No antibody reserve is left**, so the slot goes to soluble (rule 1.8). It is the seventh moved slot over all moved slots, so it goes to ATLAS. |
| ATLAS 3 | 7ONN | **1KPT** | The deposit numbers its unobserved Gly-Gly-Gly-Ala linker 225–228 (REMARK 465; the author numbering jumps from 203 to 229). The builder told the agent to build "residues 68, 69, 204, 205, 227, 228, 570", so two of the sites it names do not exist in the deposit. The audit compares site counts only and passed it. |
| ATLAS 7 | (the antibody slot) | **2PEF** | A moved slot is one more pick of its category. `plan()` resolves a category's own picks first, so 7ONN took ATLAS reserve 1 and the moved slot reserve 2. |
| MoDEL 1 | 1PNE | **1QIB** | v6's case: a kept N-terminal ACE cap (audit: `reference_cap_unnamed`). |

`plan()` gained the branch that moves a slot to soluble when a category's
reserves run out. v6 never reached it (`test_v6_plan_reproduces_tasks_101_to_130`).

**Two checks the audit lacks.**
- **Build-site numbers.** The audit counts the residues a prompt asks to build,
  but never checks that each named number exists in the deposit.
  - `test_build_missing_classification.py` places every build site in the
    deposit's polymer scheme, and it reported 7ONN's 204 and 205 as
    "unclassified".
  - Every other v7 build site is placed: 140, 146, 149, 151 and 152 build at a
    terminus, and 154 builds internally.
- **Copy mixing.** `audit_task_contract` flags a multi-chain selection only when no selected pair
  touches. A selection that mixes the chains of two copies passes as long as
  one pair touches, as 4ETQ's did.
- The drafts were therefore also compared on heavy-atom Rg, deposit selection
  against reference. Every built multi-chain task agrees within 0.7 Å, except
  2STW: 18.9 Å against 17.4 Å.
  - 2STW is an NMR DNA duplex. The backbone RMSD between deposit and reference
    is 3.0 Å, where 1A0A and 1VTN give 2.5 and 2.8 Å.
  - Its 8.9 % gap is inside the range of the cast's NMR/NAFlex references
    (056 2L1G 11.2 %, 050 1J46 7.4 %).
- Over all 55 multi-chain tasks of the dataset
  (`build/multichain_geometry_all.json`), no cast or v6 protein complex shows
  a gap of the 4ETQ (49 %) or 6B12 (51 %) kind.
- Making either check a finding of the audit would be a change to
  `mddatabench/`. That is left for later, because the running campaign imports
  the scorer from this checkout.

### 3.2 The 30 tasks

Composition: **ligand 4, complex 4, nucleic 4, nanobody 3, antibody 2, ATLAS 7,
MoDEL 6. Membrane 0 and metal 0 (no candidate), antibody 2 of 3 (reserves
exhausted).**

"held-out" is the leave-one-replica-out rejected fraction at slack 4, with the
fraction without slack in brackets, computed as for v6 3.3; the code
reproduces v6's 117, 121 and 123 values.

| task | PDB | node:accession | selection (deposit numbering) | rep | window ns | windows | held-out max rejected, slack 4 (no slack) | headroom < 4 | prompt carries |
|---|---|---|---|---:|---:|---:|---|---|---|
| 131_ligand_2pql | 2PQL | cin:A00BY | A:1–144 | 1 | 1 | 100 | — | — | ligand TSS (+1) |
| 132_ligand_3qxv | 3QXV | cin:A00E1 | A:4–131 | 1 | 1 | 100 | — | — | ligand MTX (-2); excl SO4; SMILES declared (MTX) |
| 133_ligand_5eq1 | 5EQ1 | cin:A00IS | A:628–739 | 1 | 1 | 100 | — | — | ligand BEA (0); excl NO3 |
| 134_ligand_5i7x | 5I7X | cin:A00E2 | A:23–122 | 1 | 1 | 100 | — | — | ligand 67B (0) |
| 135_complex_2d10 | 2D10 | inr:A002T | A:3–297; E:339–358 | 1 | 2.5 | 100 | — | — | — |
| 136_complex_4kt5 | 4KT5 | inr:A007O | A:-2–112; B:1–114; C:9–96 | 1 | 2.5 | 100 | — | — | excl PG4; modres MSE×3 |
| 137_complex_1i51 | 1I51 | inr:A000Y | A:58–196; B:212–303; C:58–196; D:212–303; E:135–152; F:135–152 | 1 | 2.5 | 100 | — | — | — |
| 138_complex_5gy2 | 5GY2 | inr:A00BJ | A:23–464; C:54–222 | 1 | 2.5 | 100 | — | — | excl NAG PG4 |
| 139_nucleic_2stw | 2STW | mmb:A01DY | C:18–34; B:1–17 | 1 | 1 | 100 | — | — | — |
| 140_nucleic_4f6n | 4F6N | mmb:A01E2 | E:20–38; D:1–19 | 1 | 1 | 100 | — | — | excl GOL; build E:1; modres 5CM×4 |
| 141_nucleic_1vtn | 1VTN | mmb:A01DQ | A:1–13; B:21–33 | 1 | 1 | 100 | — | — | — |
| 142_nucleic_1a0a | 1A0A | mmb:A01DD | D:1–17; C:1–17 | 1 | 1 | 100 | — | — | — |
| 143_nanobody_6ir2 | 6IR2 | mmb:A0598 | B:16–139 | 3 | 1 | 102 | 0.00 (0.09) | — | — |
| 144_nanobody_6x05 | 6X05 | mmb:A059P | K:3–122 | 3 | 1 | 102 | 0.00 (0.26) | — | — |
| 145_nanobody_6b73 | 6B73 | mmb:A058W | C:4–124 | 3 | 1 | 102 | 0.00 (0.47) | — | — |
| 146_antibody_5o14 | 5O14 | inr:A00LR | B:14–255; D:1–212; C:1–222 | 3 | 2.5 | 102 | 0.00 (0.71) | — | excl CL; build B:12 |
| 147_antibody_5x0t | 5X0T | inr:A00LW | A:21–235; B:21–233; E:25–102 | 3 | 2.5 | 102 | 0.21 (0.62) | radius | Rg demoted |
| 148_soluble_1hoe | 1HOE | bsc:A02N0 | A:1–74 | 3 | 1 | 102 | 0.00 (0.24) | — | — |
| 149_soluble_5n76 | 5N76 | bsc:A03TC | F:1–66 | 3 | 1 | 102 | 0.00 (0.15) | — | build F:7 |
| 150_soluble_1kpt | 1KPT | bsc:A02OH | A:1–105 | 3 | 1 | 102 | 0.00 (0.24) | — | — |
| 151_soluble_2x9o | 2X9O | bsc:A035Q | A:-7–236 | 3 | 1 | 102 | 0.00 (0.15) | — | excl BLA; build A:11; modres MSE×2 |
| 152_soluble_2fp1 | 2FP1 | bsc:A02YH | A:34–199 | 3 | 1 | 102 | 0.00 (0.18) | — | build A:1 |
| 153_soluble_1d4t | 1D4T | bsc:A02L6 | A:1–104 | 3 | 1 | 102 | 0.00 (0.18) | — | — |
| 154_soluble_2pef | 2PEF | bsc:A032C | A:51–423 | 3 | 1 | 102 | 0.00 (0.50) | — | build A:7 |
| 155_soluble_1qib | 1QIB | mmb:A00XJ | A:88–250 | 1 | 1 | 100 | — | — | excl CA ZN |
| 156_soluble_1a5d | 1A5D | mmb:A004D | A:1–174 | 1 | 1 | 100 | — | — | — |
| 157_soluble_1hp9 | 1HP9 | mmb:A00JB | A:1–22 | 1 | 1 | 100 | — | — | — |
| 158_soluble_1edg | 1EDG | mmb:A00DP | A:1–380 | 1 | 1 | 100 | — | — | — |
| 159_soluble_1cs6 | 1CS6 | mmb:A00AF | A:7–388 | 1 | 1 | 100 | — | — | excl GOL; HIP 134, 186 |
| 160_soluble_1cex | 1CEX | mmb:A008J | A:17–213 | 1 | 1 | 100 | — | — | — |

## Part 4 — verification

- **Contract audit.**
  - `audit_task_cast` over all 158 tasks: 156 clean
    (`build/audit_dataset_after.json`). Every one of the 30 v7 tasks is clean.
  - The two findings are the cast's own, as before the build: 028 1DFJ's
    unstated ACE, and 036 1CEB's older ligand wording.
  - The audit of the drafts (`build/audit_draft.json`) is what found 3MJ9,
    5C7X and 6A77, and showed 2AF1 and 1PNE again. The Rg comparison of 3.1
    found 4ETQ, and the build-missing classifier found 7ONN.
- **Ligand declarations and bound ions.**
  - 132 3QXV is the one v7 task whose contract atoms include a non-polymer
    residue: methotrexate's glutamate part is named like a backbone.
    - Its declaration is the reference's own `LIG` at −2:
      `CN(Cc1cnc2nc(N)nc(N)c2n1)c1ccc(C(=O)N[C@@H](CCC(=O)[O-])C(=O)[O-])cc1`.
    - It is the CCD MTX, L-glutamate stereo included.
  - No v7 task has a bound solvent cation: the rule applied to all 158 changes
    114 alone.
  - `test_contract_ligand_declarations.py` and `test_bound_ions.py` iterate
    over every task directory, so they cover 131–160.
    - The reproduction test now runs every test-split task with a ligand
      (v6's five and v7's four).
    - The bound-ion test now requires each contract to carry exactly what the
      rule finds.
- **Idempotence of the dataset scripts.**
  - `apply_dataset_v05.py` changes 0 of 158.
  - `apply_nonpolymer_audit.py` would have rewritten two prompts. It now
    changes 0 of 158 (`test_the_shipped_dataset_is_a_fixed_point`).
    - **114** (v6): its audit row was written before v0.6.1 and still lists
      K as unaddressed, so the script re-added the K exclusion that v0.6.1
      replaced by `bound_ions`. This was broken since 0df2aaa, before any v7
      work. The script now leaves a component the task keeps in `bound_ions`.
    - **138** (v7): the builder names a sugar that sits on no glycosylation
      site together with the rest ("NAG and PG4"), where this step expects
      sugars left out. An existing exclusion sentence whose list holds every
      name now counts as present.
    - Neither changes a task file.
- **Calibration, held out.**
  - 12 v7 tasks have three replicas: nanobody 3, antibody 2, ATLAS 7. At
    slack 4, 11 reject nothing.
  - 147 5X0T rejects 0.21 of its windows, all on the radius of gyration (it
    needs slack 16). That check's adversarial headroom is 2.81 window SD, so it
    is **demoted to a diagnostic**, as in the cast's 078/097 and v6's 106. No
    other v7 check is below a headroom of 4.
  - The other 18 tasks are single-replica (cin, NAFlex, MoDEL, and Dynarepo,
    whose `mdcount` is null).
- **Harness.** A dry `init_experiment`, init only, put 148_soluble_1hoe ×
  {cli_skill_sif, cli_sif, sif_only} into `testset-v7-20261101/init-dry/experiment`.
  - It used v6's stub MDClaw checkout and the no-MDClaw runtime image, and
    `run_experiment` was never called.
  - It gave 3 attempts and `dataset_id` MDDataBench-v0.7.
  - Each `task_prompt.md` is byte-identical to the task's `prompt.md`, and no
    workspace file names an MDDB host or the accession.
  - No harness code reads `split`, so `test_v7` needs no change.

### 4.1 Reading the 30 prompts

I read every prompt the way a careful human would, looking for anything
ambiguous or wrong of the kind 114's was (a prompt telling the agent to drop
ions the reference kept). None asks for a system different from its
reference. These points remain, most important first.

1. **136 4KT5: three chain-less MSE sentences in a three-chain system.**
   - "Residue 1 / 3 / 30 is deposited as **MSE** … Simulate the unmodified
     residue." The deposit has MSE at residues 1, 3 and 30 of *both* chain A
     and chain B (the two GrlR copies), and chains A and B share those numbers.
   - The contract's `modified_residues_reverted` lists chain A's only, because
     `_task_builder.modified_residues` de-duplicates MODRES records by residue
     number, whatever the chain.
   - Read chain-less, the sentences cover both chains, which is what the
     reference did (MET everywhere). A careful reader will still ask "which
     chain?".
   - The cast's 019, 020 and 022 use the same chain-less form, and agents
     revert every MSE anyway. Left as built.
2. **151 2X9O "Simulate 15, PDB entry 2X9O".** `molecule_name` cuts the
   entity description, "15,16-dihydrobiliverdin:ferredoxin oxidoreductase", at
   the first comma. (The replaced 7ONN had the same problem: "Peptidoglycan D".)
   No check reads the name, but the first sentence reads as wrong. A fix belongs in `_task_builder` (not
   touched; see 4.3).
3. **155 1QIB.** The MMP-2 catalytic domain is simulated without its catalytic
   zinc, its structural zinc and its calcium ions ("The deposit's **CA** and
   **ZN** are not part of the reference"). This is what MoDEL did, and the
   reference is stable (2.73 Å), but the system is chemically unusual. It is
   the same kind of case as v6's 1AJJ.
4. **140 4F6N.**
   - The Kaiso–DNA structure's four 5-methylcytosines are simulated as plain
     cytosine. The prompt says so precisely, but the methylation is what the
     deposit is about.
   - Its 5CM sentences also name no chain. The two strands' numbering is
     disjoint (D 1–19, E 20–38), so they are unambiguous.
   - "Chain E does not resolve residue 20; the range runs through them, so
     build them" is the builder's standard wording, applied to a 5′-terminal
     nucleotide.
   - The molecule name is "DNA in complex with DNA".
5. **133 5EQ1 ligand BEA, net charge 0.** The CCD entry is the protonated
   cation (C9H8N3S, formal charge +1). The reference carries 7 hydrogens, the
   neutral 5-methyl-1,2,4-triazolo[3,4-b]benzothiazole (tricyclazole). So 0 is
   the reference's state and the expected one at pH 7, but a reader who checks
   the CCD sees +1. 131 2PQL's tryptamine (+1, CCD 0) and 132 3QXV's
   methotrexate (−2, CCD 0) are the usual direction.
6. **138 5GY2.**
   - "The deposit's **NAG** and **PG4** are not part of the reference" covers
     glycans that are N-linked to TLR5b chain A (Asn63, 89, 228, and a NAG–NAG
     on Asn346 under chain label E).
   - Because the deposit has no MODRES glycosylation records, the prompt does
     not use the cast's glycan sentence ("Residue N (ASN) carries an N-linked
     glycan…"). It is still precise: leave the sugars out.
   - The reference relabels its first polymer from A to B at residue 372. It
     is one continuous chain, and the audit is clean.
7. **First-sentence names omit a partner.** `molecule_name` names the first two
   polymer entities, as for v6's 118:
   - 146 5O14 names the Fab chains but not the antigen (chain B);
   - 147 5X0T names basigin and the light chain, not the heavy chain;
   - 137 1I51 names XIAP and caspase-7 p11, not p20.
   The chain list that follows is complete in every case.
8. **NMR entries 139 2STW and 157 1HP9.** No model is named, as in the cast's
   17 NMR tasks; both deposits hold one model. 2STW is an ETS1–DNA complex
   simulated as free DNA.
9. **132 3QXV** is a CDR-grafted VHH with methotrexate, in the ligand category
   by its collection (cin `ligate`). The author numbering skips 114–118, so
   "residues 4–131" holds 123 residues. This is exact, and there is nothing to
   build.
10. **Builds.** Six tasks ask for residues the reference built, and every one
    is stated:
    - 146 5O14 B: 12 (a loop and the N-terminus);
    - 149 5N76 F: 7;
    - 154 2PEF A: 7, an internal loop 385–391;
    - 151 2X9O A: 11, including six N-terminal tag residues −7…−2;
    - 152 2FP1 A: 1;
    - 140 4F6N E: 1.
11. **Unchanged cast conventions**, kept as v6 did:
    - "neutral pH; ionisation states of the side chains are your choice" on
      DNA-only systems;
    - ATLAS's unrecorded ensemble is stated as NPT at 1 bar.

### 4.2 Tests

- **`pytest tests/` in `mdclaw.sif`**, with `MDDATABENCH_BUNDLE_ROOT` set and the
  checkout as the working directory: **2702 passed, 4 failed**
  (`testset-v7-20261101/build/pytest_mdclaw.txt`).
  - The 4 are the known pre-existing ones: 029's bundle delta ×2, and
    `test_source_overlay` image mode ×2 in `mdclaw.sif`.
  - An earlier run from `/tmp` gave 66 failures, and all the extra 62 were the
    working directory. The harness tests resolve `benchmarks/mddatabench`
    relative to the cwd, as `init_experiment` and `list_benchmark_tasks` do.
    That run also showed the two gaps fixed above: the build-missing fixture
    lacked v7's six building tasks, and 7ONN's unplaceable sites.
- **New or changed tests.**
  - `test_heldout_sets.py` (18):
    - v6 is the default, and `configure()` switches every parameter;
    - the v6 plan reproduces 101–130 and its two replacements;
    - the v7 plan numbers 131–160 in dispatch order;
    - `finalize` is idempotent and never downgrades, and bumps an older id
      once;
    - `load_cast` reads only the set's splits;
    - the caps come from the 98;
    - the mdclaw mentions are reproduced from each set's pinned commit,
      locations included;
    - a category out of reserves hands its slot to soluble.
  - `test_apply_nonpolymer_audit.py` (+3): a bound cation is never excluded; a
    covering exclusion sentence counts as present; the shipped dataset is a
    fixed point.
  - `test_contract_ligand_declarations.py`: the reproduction test runs over
    every test-split task with a ligand.
  - `test_bound_ions.py`: each contract carries exactly what the rule finds.
  - `test_build_missing_classification.py` and its fixture: v7's six building
    tasks.
  - `test_boundary_contract_cast.py`: the task count is dataset.json's.
  - `test_build_test_tasks.py`: the cast is every non-test split.
- `ruff check mddatabench/ tests/` and the changed scripts: clean.

### 4.3 What was not possible, and what I am unsure of

- **The anchor decision (Part 1, change 2) moves 19 of the 30 picks.** I read
  "the anchors are the cast tasks of the same axis" as "the MDDB tasks MDClaw
  was developed against", and since 2026-11-01 those include v6. Taking the
  98 alone is the other reading, and its result is kept in
  `selected_anchors98.json`. If the coordinator prefers it, the build would
  have to be redone from that record.
- **Antibody fills 2 of 3, and the next two Dynabench antibody candidates were
  never looked at.** The rule stops at 3 reserves.
  - All four replacements in this category (4ETQ, 3MJ9, 5C7X, 6A77) failed
    for builder reasons: copy mixing, and Kabat insertion codes.
  - A builder that chose twin chains by contact, and kept insertion-code order,
    would have stated most of them. Both are `_task_builder` changes, and v6's
    rule says a pick the builder cannot state takes the reserve rather than an
    ad hoc builder change. I followed that.
- **The audit's two blind spots** (3.1).
  - It does not catch a selection that mixes chains of two copies when one
    selected pair touches. I checked by Rg and found no such case among the
    shipped 128.
  - It does not check that a build site the prompt names exists in the
    deposit. The build-missing classifier does, but only as a test, and only
    for tasks with builds.
  - Both belong in `mddatabench/contract_audit.py`. That is left for when no
    campaign imports the scorer from this checkout; `test-v6-sifonly` does at
    the time of writing.
- **An incident during the build.** A cleanup glob (`tasks/1[3-6][0-9]_*`)
  also matched v6's `130_soluble_1c2a`.
  - Its `task.json` and `prompt.md` were absent from the main checkout for
    about one minute, from just before 04:48:48 to 04:49:38 host time on
    2026-11-01.
  - They were restored byte-identical from git, and every tracked task file
    equals HEAD.
  - `test-v6-sifonly` reads task files from this checkout when it scores. A
    130 attempt scored in that minute would have failed to read its contract.
    I did not read `runs/` to check.
- **Ligand charges** were derived as the cast's and v6's were (CCD formal
  charge + reference H − CCD H): 131 TSS +1, 132 MTX −2, 133 BEA 0, 134 67B 0.
  The cast's confirmation through MDClaw's Dimorphite-DL path is MDClaw code,
  and was not run.
- **Positive control.** As for v6, an MDClaw-free positive control would need
  MD, which the rules exclude.
- **oxf** was unreachable on both days. If it now holds eligible all-atom
  systems, neither set saw them.
- **Sealing is by convention only.** The 30 contracts and prompts are committed
  in the same tree as everything else, and nothing in the harness refuses to
  run split `test_v7`. They are not pushed.

## Part 5 — the membrane supplement, split `test_v7_membrane` (rule written 2026-11-02, before it was applied)

test-v7 has no membrane task (2.2). All 55 membrane projects were eliminated by
receptors already among the tasks, the size cap, and GPCR–G-protein complexes
whose Gβ1, Gγ2 and scFv16 chains match external entries that the mdclaw checkout
only mentions (6OT0, 6XBL). The user asked for **one** membrane task, to
supplement test-v7. It is task 161, split `test_v7_membrane`, dataset v0.7.1.
It is chosen by the rule below, which is fixed before any candidate is verified.
Tasks 1–160 do not change, and test-v7's own rule above does not change.

Integrity is as in Part 1, and nobody runs the task here: no MDClaw, pi, agent,
`run_experiment` or MD on a candidate, and no campaign result under `runs*` is
read to choose. Nothing is written under `/data1/rkp00048`. Work directory:
`/data1/rkp00079/rku00161/testset-v7m-20261103`. Pool: test-v7's
`selection/eligible.json` (listing of 2026-11-01), nothing fetched anew.

### 5.1 The rule (pre-registered)

1. **Candidates.** The membrane projects of the pool (Part 1: node mmb,
   collections ebrains/mcns, `LIPIRES` ≥ 20, `PROTRES` > 0) that are not among
   the 158 tasks, and whose PDB ID is not among the 158 tasks or MDPrepBench
   (MDStudyBench S01 has no PDB ID, so it is compared by sequence only). The
   withdrawn 038 and 061 and the development task 1EDN keep their place beside
   the 158, as in Part 1; that is stricter than naming the 158 alone.
2. **Distinctness.** 3-mers, the Ig V-domain cut, and chains of ≥ 30 residues,
   as in Part 1.
   - **Hard members** are the 158 tasks, 038, 061, 1EDN, MDPrepBench and
     MDStudyBench. Each chain must have containment < 0.70 against every chain
     of every hard member, and the whole system < 0.70 against every hard
     member. There is no exemption here: a G-protein chain that matches a task
     fails.
   - **Mention-only members** are the entries the mdclaw checkout mentions and
     MDPrepBench does not contain. The mentions are read from the git tree of
     `6524d3e`, the same pin as v7; the checkout's HEAD is scanned as well, and
     a difference is recorded. A candidate whose own PDB ID is mentioned is
     **out**.
   - **Exemption (a recorded relaxation of v6/v7).** Against mention-only
     members only, a candidate chain is not compared when it is shared
     machinery: a heterotrimeric G-protein subunit or scFv16, the way Ig
     constant domains are not compared. A chain is recognised by the deposit
     entity it aligns to, whose description must name a G-protein subunit
     (`guanine nucleotide[- ]binding`, or a stated Gα/Gβ/Gγ or mini-G) or
     scFv16. Every exempted chain is listed in the result. No other chain is
     exempt: a receptor, a channel, a toxin, a Fab or a nanobody that matches a
     mention still fails.
   - The whole-system comparison with a mention-only member is made on the
     candidate's non-exempt chains.
3. **Size.** Polymer residues ≤ 1700 (the cast maximum is 1698) and reference
   atoms ≤ 120,000. v6 and v7 capped atoms at the cast maximum, 91650 (008
   6I53), so this is **a recorded relaxation**. The pick's size is reported
   against the cast's largest membrane task.
4. **Standard eligibility, as v6/v7** (`verify_candidates.verify` and
   `content_check`):
   - last-third RMSD ≤ 4.0 Å from MDDB's `rmsds`, strictly;
   - SEQRES verification and `selection()`;
   - the residue rule;
   - a current RCSB entry;
   - the bilayer present on the reference (≥ 20 lipid residues);
   - distinctness again, on the reference's own sequences;
   - a buildable force field: `FF` is CHARMM36-family, as for all 15 membrane
     tasks so far, or one `buildable_force_field` names, and every lipid of the
     reference is one the builder can state (`_task_builder.LIPIDS`) and the
     scorer can decompose (`composition.LIPID_COMPONENTS`).
   Frames and windows are as the pool states them.
5. **Order.** Ascending maximum chain containment against the tasks, farthest
   first. The key is the largest containment of any chain ≥ 30 residues (Ig: V
   domain) against any chain of the 158 tasks, on MDDB's `PROTSEQ`; ties go to
   the smaller accession. The pick is the first candidate that passes
   verification, build, contract audit and review. Every candidate tried is
   recorded with its reason. Verification continues down the list until there
   is the pick plus at least 3 further candidates that pass step 4, counted as
   distinct PDB IDs. Those are not built; they are the reserves, in order.

Review (step 5) is the extra checks the test-v6 defects ask for, each answered
in 5.5 from the reference's coordinates and metadata:
- which ions, lipids, ligands, toxins or Fabs were in the simulation, and
  whether the prompt states them; a bound ion or ligand the prompt excludes is
  tested on the reference trajectory, as for 114 and 155;
- for a homo-oligomer, that the chains are copies of one assembly and not a
  symmetry mate or a copy mix, and author and label chain IDs;
- that the bilayer sentence matches the reference and the scorer's membrane
  check can pass on the reference's numbers;
- that a correct submission can satisfy every scored check;
- whether 1 ns fits `md_time_limit` 00:20:00 on one GB200 GPU, reasoned from
  the atom count.

### 5.2 Result of the rule: no candidate passes

Applied by `scripts/select_membrane_supplement.py`. Records are under
`testset-v7m-20261103/selection/`: `candidates.json` (the funnel),
`selection_log.json` (every candidate tried), and `all_steps_record.json` and
`oversize_stability.json` (every step for every project past step 2, size
ignored; a record, which chooses nothing).

| Step | Removed | Left |
|---|---:|---:|
| membrane projects of the pool | | 55 |
| already one of the 158 tasks | 15 | 40 |
| distinctness against a task (0.89–1.00: β2AR, MT1, 5-HT2A, A2A, M2, GABA-A) | 17 | 23 |
| size: 13 over 120,000 atoms, one (6CNJ) over 1700 residues | 14 | **9** |
| own PDB ID mentioned in mdclaw | 0 | 9 |
| stability, or SEQRES verification | **9** | **0** |

The nine, in rule order. Every one fails step 4:

| rank | PDB | node:accession | system | order key (max chain vs tasks) | res / atoms | last-third RMSD Å (drift) | why it fails |
|---:|---|---|---|---:|---|---:|---|
| 1 | 7K48 | mmb:A0258 | NavAb/Nav1.7-VS2A chimera + m3-huwentoxin-IV | 0.129 | 1048 / 117324 | 8.372 | unstable |
| 2 | 6VXO | mmb:A023Q | NaChBac-Nav1.7VSDII chimera | 0.148 | 904 / 105688 | 4.175 (+0.58) | unstable |
| 3 | 6W6O | mmb:A023X | NaChBac-Nav1.7VSDII + huwentoxin-IV | 0.148 | 1044 / 107294 | 5.545 | unstable |
| 4 | 6J8H | mmb:A024C | Nav1.7 | 0.250 | 1140 / 117692 | 4.012 (+0.46) | unstable, by 0.012 Å |
| 5 | 7E2Z | mmb:A02JU | 5-HT1A–Gi, aripiprazole | 0.256 | 870 / 75443 | 4.404 | unstable |
| 6 | 7E2Y | mmb:A0252 | 5-HT1A–Gi, serotonin | 0.262 | 868 / 74495 | 4.588 | unstable |
| 7 | 6OIJ | mmb:A023W | M1–G11 | 0.344 | 916 / 76291 | 5.889 | unstable |
| 8 | 6K42 | mmb:A024F | α2B–Gi1 | 0.539 | 883 / 75776 | 4.685 | unexplained chain F, and unstable |
| 9 | 7CMU | mmb:A024W | D3–Gi | 0.594 | 892 / 80521 | 4.072 (+0.47) | unstable |

- **No pick and no reserve exist under the rule as written.** The 4.0 Å cut has
  been strict in both sets (437D at 4.08 Å and 1UTG at 4.032 Å are out), so
  6J8H at 4.012 Å is out too. The rule is not changed here: a threshold moved
  after the candidates' values are known is no longer pre-registered, so any
  change is the user's decision.
- The nine fail on stability, not on sequence. The exemption of step 2 reaches
  five of them (7E2Z, 7E2Y, 6OIJ, 6K42, 7CMU), whose Gα, Gβ and Gγ chains have
  containment 1.00 against the mentions 6OT0 and 6XBL, and it made no difference
  to the outcome.
- `6524d3e` and the checkout's HEAD (`ca0ec66`) agree on every candidate: no
  candidate's PDB ID is new at HEAD.
- The scan also shows that the list of 16 systems given with the request was
  right on sequence: every one has no chain near a task (maxima 0.13–0.59).
  Seven of them are over the size cap of step 3.

### 5.3 What is left to decide

Nothing below is the rule. It is measured so that the decision can be made
with the numbers in hand. `all_steps_record.json` holds every step of 5.1 for
all 23 projects past step 2, size ignored.

| Change (one at a time) | What passes step 4 | First in rule order |
|---|---|---|
| Atom cap raised to any value ≥ 126,711, up to no cap at all | **7DTD alone** | 7DTD; no reserve |
| RMSD cut 4.02 Å, atoms ≤ 120,000 | 6J8H | 6J8H; no reserve |
| RMSD cut 4.1 Å | 6J8H, 7CMU | 6J8H; 1 reserve |
| RMSD cut 4.2 Å | 6VXO, 6J8H, 7CMU | 6VXO; 2 reserves |
| RMSD cut 4.6 Å | adds 7E2Z, 7E2Y | 6VXO; 4 reserves |

- **7DTD** (mmb:A0251, human Nav1.1 α; 1138 residues, 126,711 atoms) is the only
  project of the whole membrane pool past step 2 that passes every quality gate
  of step 4: RMSD 3.877 Å (drift +0.225), every chain contiguous on SEQRES,
  largest chain containment 0.25 against the tasks. It is 6,711 atoms (5.6 %)
  over the cap of step 3.
- Of the 14 projects over the size cap, only 7DTD passes stability; 6CNJ, the
  one over the residue cap alone, is at 4.279 Å, and the others at 5.35–15.7 Å.
- The size cap is a cost limit and the RMSD cut a validity limit: above it
  "the reference has left the deposited fold". So the atom cap is the smaller
  departure from v6/v7, and it is the one a proposal was built for.
- That proposal is on the local branch `v7m-7dtd-proposal`, in the worktree
  `../MDDataBench-worktrees/v7m-7dtd-proposal`, and is **not** on main. Its
  build and verification are written up on that branch, Parts 5.4 and 5.5.
- Main carries the `v7m` set and the selection script, but no task 161: dataset
  v0.7 and its 158 tasks are unchanged.

## Reproduce

```bash
cd /data1/rkp00079/rku00161/MDDataBench
S="apptainer exec --no-home --bind /data1/rkp00079 --pwd /tmp --env PYTHONPATH=$PWD --env TMPDIR=<private dir> /data1/rkp00079/mdclaw.sif python"
PYTHONPATH=$PWD python3 scripts/scan_mddb_pool.py --set v7 --workers 4   # pool + counts (fresh listing)
PYTHONPATH=$PWD python3 scripts/verify_candidates.py --set v7 --validate-cast
PYTHONPATH=$PWD python3 scripts/select_test_set.py --set v7                # selected.json
PYTHONPATH=$PWD python3 scripts/select_test_set.py --set v7 --anchors cast --out-suffix _anchors98
$S scripts/build_test_tasks.py --set v7 fetch
$S scripts/build_test_tasks.py --set v7 calibrate --workers 4
$S scripts/build_test_tasks.py --set v7 build --draft <dir> --extra 2AF1,1PNE   # drafts for the audit
$S scripts/build_test_tasks.py --set v7 build
$S scripts/build_test_tasks.py --set v7 finalize
```

- The work directory `/data1/rkp00079/rku00161/testset-v7-20261101` holds:
  - the caches;
  - `selection/` (`selected.json`, `selection_log.json`, `pool_counts.json`,
    `eligible.json`, `selected_anchors98.json`, `builder_validation_on_cast.json`);
  - `build/` (`build_report.json`, the audits, `multichain_geometry_*.json`,
    `calibration_summary.txt`, the pytest logs, `deposits-not-built/`);
  - `calibration/` (and `calibration-unused/` for the 6 picks that were not
    built);
  - `init-dry/` and `v6-rerun/` (the copy of v6's inputs the `--set v6` rerun
    used).
- A rerun of the selection reads the listing cache, so it makes no network
  request except to nodes that failed.
