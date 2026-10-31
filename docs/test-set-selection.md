# Held-out test set: selection rule and result (2026-10-31)

Status: **selection fixed under rule v4; the 30 contracts are built (Part 3) as
tasks 101–130 of dataset v0.6, split `test`.** The 98 shipped tasks (69 train /
29 eval) were used to develop MDClaw, so these 30 are new systems, chosen to be
as diverse as possible and sequence-distinct from everything MDClaw was
developed or documented against. Nothing here is committed.

- Output: `/data1/rkp00079/rku00161/testset-20261031/selection/selected.json`
  (30 picks and 21 reserves, each with its verification record and the result of
  `selection()`); every attempt in greedy order, kept or dropped with its reason,
  is in `selection_log.json`.
- Code, runnable end to end: `scripts/scan_mddb_pool.py` →
  `scripts/select_test_set.py`, which calls `scripts/verify_candidates.py`.
  The commands are at the end of this page.

Part 1 is the rule as it now stands (v4). It was written down while the
procedure was applied. Section 1.10 lists every change made after a run, the
reason for it, and who decided it. Part 2 is the result.

## Part 1 — the rule (v4)

### 1.1 Integrity

- Inputs: MDDB metadata, MDDB reference files and analyses (`structure`,
  `rmsds`), RCSB deposits and entry metadata, and, for the exclusion set
  (1.4), the task lists of MDPrepBench and MDStudyBench and the text of the
  mdclaw checkout. Nothing else.
- No MDClaw, pi, agent, `run_experiment` / `init_experiment` or MD was run on
  any candidate, and no campaign result (`runs*`) was read. Nothing about how
  MDClaw performs influenced which systems entered the set.
- Every step is deterministic. Ties go to the smaller `(node, accession)`, API
  responses are cached under the work directory, and a rerun reproduces the
  same set.

### 1.2 Population and eligibility

All eight nodes were asked directly (`/projects?limit=100&page=N`); seven
answered. The global API is not a superset of the nodes, so it was not used as
the source. The filters are those of `docs/memo.md` 2026-08-22 (5)–(7) and
2026-08-23, applied in this order. Absence written as a string (`"none"`,
`"No"`) is read as absence, never through `bool()`.

| Filter | Remaining | mmb | cin | bsc | inr | jsc | rpbs | ufl |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all projects (7 nodes answered) | 34778 | 9372 | 7598 | 5491 | 930 | 5406 | 10 | 5971 |
| `METHOD == "Classical MD"` | 34312 | 8943 | 7597 | 5491 | 930 | 5406 | 2 | 5943 |
| all-atom (`CG_SELECTION` absent, no Martini/SIRAH) | 30801 | 5432 | 7597 | 5491 | 930 | 5406 | 2 | 5943 |
| PDB ID present | 25509 | 2575 | 5167 | 5491 | 928 | 5405 | 0 | 5943 |
| water TIP3P/OPC/OPC3/TIP4P-Ew/SPC/E | 25383 | 2449 | 5167 | 5491 | 928 | 5405 | 0 | 5943 |
| numeric `TEMP` | 20392 | 2417 | 214 | 5491 | 928 | 5405 | 0 | 5937 |
| topology prmtop/tpr/psf/top | 11415 | 2178 | 214 | 2150 | 928 | 8 | 0 | 5937 |
| `fluctuation` + `rgyr` analyses | 11388 | 2162 | 213 | 2149 | 928 | 8 | 0 | 5928 |
| ≥ 10 windows × ≥ 25 frames (1 ns; 2.5 ns on inr, frames from the `rmsds` length) | 10883 | 1885 | 213 | 1938 | 922 | 0 | 0 | 5925 |
| exactly one PDB ID | 10879 | 1881 | 213 | 1938 | 922 | 0 | 0 | 5925 |
| open licence (CC BY / CC0 / Apache / MIT; none only on inr) | **10866** | 1880 | 201 | 1938 | 922 | 0 | 0 | 5925 |

Notes on the population:

- **oxf did not answer** (TCP connect timed out on every attempt on 2026-10-31).
  Per memo (6), its 9108 projects are MemProtMD coarse-grained runs, 7 GLIC runs
  at 200 ps per frame, and 93 enhanced-sampling lipid boxes. All of them fail a
  filter above, so the eligible pool is unaffected unless oxf has changed since.
- One bsc listing entry is an error object (`A002M`: "missing metadata").
- mmb + cin + bsc after the window filter is **4036, exactly the count memo (6)
  recorded in August**. This checks the filter implementation.
- **ufl answers now** (it returned HTTP 500 in August). It has 5925 eligible
  protein–ligand complexes (Amber ff19SB + GAFF2, TIP3P, 310 K, 10 ns, 20 ps per
  frame). None of the 98 comes from this collection, so it is not used (1.3).
- 12 cin ligate projects carry no licence string and are excluded. Only inr may
  lack a licence (the Dynabench precedent in `CLAUDE.md`).

### 1.3 Categories

Each eligible project belongs to at most one category pool. A category means
what the corresponding axis of the 98 means: the node and collection it was
drawn from. Content is read from MDDB metadata and checked again on the
reference structure.

| Category | Pool definition | Quota |
|---|---|---:|
| membrane | mmb `ebrains`/`mcns`, ≥ 20 lipid residues (`LIPIRES`) and protein | 4 |
| antibody | inr `dynabench` with a heavy **and** a light Ig V domain and ≥ 1 non-Ig (antigen) chain | 3 |
| complex | inr `dynarepo`, ≥ 2 protein chains, no Ig chain | 4 |
| nanobody | mmb `nanobodies` | 3 |
| ligand | cin `ligate` | 4 |
| nucleic | mmb `bigna` (NAFlex) with DNA or RNA | 4 |
| metal | any node: the reference keeps a metal ion (`RSNAME` ∩ {ZN, MG, CA, CAL, FE, CU, MN, CO, NI, CD, …}) bound to the polymer | 2 |
| soluble_charmm | bsc `atlas` (CHARMM36m) | 3 |
| soluble_amber | mmb `model` (MoDEL, Parm99) | 3 |

When several apply, precedence is bilayer → membrane, then DNA/RNA → nucleic,
then kept metal → metal, then the collections. A bilayer or nucleic acid
outside the listed collections is left out.

Ig V domains are recognised by sequence: Cys22 … `W[VFYIL][RQKH]` in the first
55 residues, and a J-region motif, `WGxG` (heavy, VHH) or `FGxG` (light),
starting at residue 85–140. On the 98 this finds every Fab chain and every VHH,
and nothing else.

Dynabench entries whose only antibody is a single-domain one, and Dynabench's
non-Ig complexes, fit neither axis, so they are not used. The antibody axis of
the 98 is heavy+light Fab/Fv complexes in 9 of its 10 tasks, and the complex
axis is Dynarepo.

### 1.4 Sequence distinctness and the development set

**The development set** is everything MDClaw was developed or documented
against:

- the 98 shipped tasks;
- 038 (1IKT) and 061 (6M0J), withdrawn on 2026-08-30 but used in development;
- D03 = mmb `A00EC` (1EDN, endothelin-1), the 2026-08-20 development task,
  which was solved end to end with MDClaw (memo 2026-08-20, 2026-08-21);
- **MDPrepBench**'s 40 tasks, which use 30 PDB IDs. These were read, read-only,
  from `/data1/rkp00048/rku00208/MDPrepBench/benchmarks/mdprepbench/tasks/*`;
- **MDStudyBench**'s one task, S01: T4 lysozyme C54T/C97A/L99A. It names no PDB
  entry, so its `reference_sequence` is used, fetched from
  `raw.githubusercontent.com/matsunagalab/MDStudyBench/main`;
- **every PDB entry mentioned in the mdclaw checkout**: 171 entries
  (`/home/rku00161/mdclaw` at `ac0e328`, under `skills/`, `tests/`,
  `examples/` and `docs/`).
  - These are found as whole 4-character tokens, case-insensitively, in text
    files only (binaries are skipped), and kept when RCSB has the entry.
  - Every token was then checked by reading its context. Nineteen tokens that
    matched a current entry are not PDB mentions, and they are listed in the
    script (`MDCLAW_NOT_PDB`) with their reasons: numbers such as `1e10` or
    `6.5e11`, `10th`, `13px`, `30GB`, `4amu`, a URL-encoded `%2Fps`, a hash and
    a UUID fragment, the synthetic fixture names `1sol` and `2mem`, and the
    placeholder `2xyz`.
  - `job_4m3j_B` in the hpc-run skill is counted as a mention of 4M3J.
  - The list, with one location for each entry, is stored in
    `selected.json` → `development_set`.

The cast and the withdrawn and development tasks are compared through their
MDDB reference sequences. The external entries (MDPrepBench and the mdclaw
mentions) are compared through their deposits' full entity sequences, since
they have no MDDB reference; this is a conservative choice.

Sequences of candidates are the reference's own one-letter sequences, read
from the reference `structure.pdb`. For screening the pool, MDDB's
`PROTSEQ`/`NUCLSEQ` are used; they give the same maxima, within 0.02, as the
structure on all 51 picks and reserves. k-mers never cross a chain boundary or
a backbone break, carry their polymer type (an RNA `ACG` is not a protein
`ACG`), and never contain `X`. Protein chains use **3-mers**; DNA and RNA
chains use **6-mers** (decision 1 below).
`containment(a, b) = |K(a) ∩ K(b)| / min(|K(a)|, |K(b)|)`.

1. **Whole system**: containment < 0.70 against every member of the
   development set, and between any two of the 30 and the reserves.
2. **Chain level**: every chain of ≥ 30 residues has containment < 0.70
   against every chain of the development set.
   - Immunoglobulin chains (Fab heavy and light chains, VHH) are compared
     through their V domain only, on both sides. The V domain runs from residue
     1 to 10 residues after the start of the J motif (`WGQGTxVTVSS` /
     `FGxGTKLEIK`): 108 residues for a kappa light chain, 113–131 for heavy
     chains and VHHs in the 98.
3. **No PDB ID shared** with the development set.

**Nucleotide 6-mers** (decided by the coordinator on 2026-10-31, after a run of
the literal rule).

- With 3-mers, every 3-mer is common over a 4-letter alphabet (there are only
  64). The 294 nt of the nucleosome 1KX5 carry nearly all of them. So under
  3-mers, 9 of the 12 DNA-only references in the 98 are "the same system" as
  1KX5 (containment 0.70–1.00), 11 of its 14 nucleic references have a partner
  at ≥ 0.70, and any new DNA duplex would be the same system too.
- A nucleotide 6-mer carries 12 bits, about as much as a protein 3-mer's
  3·log2 20 ≈ 13. With 6-mers, the largest containment between two nucleic
  references of the 98 is 0.111.
- The memo's own clustering also rules out nucleotide 3-mers. Memo 2026-08-23
  reports a largest cluster of 4 at 0.70; nucleotide 3-mers give an 11-member
  DNA cluster on the 98, while 6-mers, or protein k-mers alone, give 4. Its
  exact counts (93 clusters, 10 VHH) cannot be reproduced, because they were
  computed on a candidate set that no longer exists (the final 98 have 5 VHH).
- The literal-rule run is kept as `selected_literal_nucleic_k3.json`, a v3-era
  record.

### 1.5 Size caps

A candidate may not exceed the largest task of the same axis among the 98,
either in reference atoms (`SYSTATS`) or in polymer residues
(`PROTRES + DNARES + RNARES`). When `PROTRES` is missing, as for 8 MoDEL
entries, MDDB's sequence lengths are used. **The same cap applies to membrane
as to every other category** (decision 4 below; the extra ≤ 700-residue cap of
v1–v3 is gone).

| Axis | max atoms | max residues |
|---|---:|---:|
| membrane | 91650 | 1698 |
| antibody | 10528 | 698 |
| complex | 9693 | 611 |
| nanobody | 1869 | 131 |
| ligand | 2465 | 158 |
| nucleic | 21822 | 1058 |
| metal | 4897 | 312 |
| soluble_charmm | 7205 | 456 |
| soluble_amber | 6147 | 385 |

### 1.6 Verification of one candidate (`verify_candidates.verify`)

1. **Reference chains.** Polymer chains are read from MDDB's `structure.pdb`
   and split where the backbone breaks (`composition.split_monomers`, as the
   scorer does). So a fusion construct the reference ligated is one chain, and
   two pieces it kept apart are two.
2. **Residue identity (decision 5).** Every residue of a reference polymer must
   be one of:
   - a standard amino acid or nucleotide;
   - a named ionisation, tautomer or bonding variant of one (HID/HIE/HIP,
     HSD/HSE/HSP, CYX, CYM, ASH, GLH, LYN, ARN, TYM, NLN/OLS/OLT, terminal
     nucleotide names) — a deposited modified residue that the reference
     reverted to its parent is covered here, because the reference then uses
     the parent's name;
   - at a chain end only, a force-field terminal cap (ACE, NME, NMA, NHE, NH2).

   A reference that keeps any other residue in a polymer is **rejected**: MSE
   kept as MSE, HYP, or 2OUE's 2'-O-methyl-A `MRA` and N1-protonated `RAP`.
   Residues outside a polymer (ligands, lipids, ions) are not polymer residues.
3. **Alignment to SEQRES.** Each chain is aligned **by sequence** to the
   deposit's SEQRES; SEQRES positions of unknown residues are kept as an `X`
   wildcard. The outcomes are those of memo 2026-08-23:
   - contiguous match (`SEQRES に連続一致`); when several deposit chains match,
     the one with the most observed residues inside the span comes first;
   - two spans with a removed insert (`SEQRES に 2 区間 (融合部除去)`); the
     placement with the fewest removed residues is used;
   - approximate contiguous match with at most max(2, 2 %) substitutions
     (`詳細` / `差分`);
   - unexplained (`説明不能`) → **reject**.
4. **Selection.** The record is passed to
   `_task_builder.selection(record, deposit)`. If it refuses (a deposit chain
   that does not place on its own SEQRES), the candidate is rejected. A
   candidate with no PDB-format deposit at RCSB is also rejected.
5. **Stability**, from MDDB's `rmsds` (first-frame reference, first group). The
   last-third mean must be ≤ **4.0 Å**, applied strictly (437D, at 4.08 Å, is
   out). The drift (last-third mean − first-third mean) is recorded. A
   candidate with no `rmsds` analysis is rejected. This measurement reproduces
   the values recorded for the 98 (12CA 1.85, 16PK 2.90).
6. **Category content**, checked on the reference:
   - membrane: ≥ 20 lipid residues;
   - antibody: a heavy and a light V domain, and an antigen;
   - complex: ≥ 2 protein chains and no Ig;
   - nanobody: a V domain;
   - ligand: a small-molecule residue;
   - nucleic: a DNA or RNA chain;
   - metal: an ion within 3.5 Å of a polymer N, O or S;
   - soluble: one protein chain.
7. **Distinctness again.** The three sequence rules of 1.4 are re-applied on the
   structure's own sequences.

**Check against the 98.** The original record script was never committed, so
the record builder written here was checked against the 98: their shipped
selections were rebuilt from the cached bundles.
- 93 give identical per-chain ranges.
- 4 give the same ranges on a SEQRES-identical twin chain: 029 1E3U, 034 4KFZ,
  062 6W9C and 080 1EZ3. The shipped tasks chose the twin by the depositor's
  chain name or by the contacting assembly, which is a build-step decision.
- 1 differs: 008 6I53, a pentamer of two-piece subunits. The builder puts both
  33-residue β3 pieces on deposit chain E, instead of one on E and one on B
  (`selection/builder_validation_on_cast.json`).
None of the picks has that shape.

### 1.7 Diversity: deterministic greedy farthest-point

The distance between two systems is the equal-weight mean of these components,
each in [0, 1]:

- sequence: 1 − whole-system containment;
- size: |ln residues_a − ln residues_b| / ln 10, capped at 1;
- chains: |n_a − n_b| / 3, capped at 1;
- class: 0 if the deposits' primary PDB keyword (the text before the first `/`,
  `,` or `(`) is the same, else 1;
- temperature: |ΔT| / 20 K, capped at 1;
- force field: 0 if identical, else 1;
- experimental method: 0 if identical, else 1;
- preparation features: the Jaccard distance between the deposits' flag sets
  {multi-chain deposit, unmodelled residues, non-polymer components,
  disulfides, modified residues, chimeric (fusion) entity, NMR};
- category-specific components, used only between two systems of the same
  category:
  - nucleic kind (DNA / RNA / protein+DNA …);
  - ligand size: |ln ratio| of ligand atoms from `SYSTATS − PROTATS`, capped;
  - membrane lipid species (Jaccard);
  - metal species (Jaccard).

How picks are made:
- **Anchors.** Within a category, the anchors are the tasks of the same axis
  among the 98. The external development entries are not anchors.
- **Seed and later picks.** The seed is the candidate with the largest minimum
  distance to the anchors. Each later pick is the candidate with the largest
  minimum distance to the anchors plus the picks so far. Ties go to the smaller
  `(node, accession)`.
- **Lazy verification.** A pick is verified only when it is reached (1.6). If
  it fails, it is dropped and the step repeats. A dropped candidate never
  influenced an earlier pick, so this gives exactly the result of verifying the
  whole pool first.
- **Category order.** Categories are processed **scarcest pool first**, by pool
  size after the pre-filters. soluble_charmm and soluble_amber come last
  because they receive any slot another category cannot fill. Moved slots
  alternate between them over all moved slots, ATLAS first.
- **Rule 1 across categories.** The whole-system rule between test picks is
  applied against every earlier pick, in any category.

### 1.8 Reserves

After the 30 picks, each category's greedy sequence is continued to give an
ordered list of 3 reserves. Each reserve satisfies every rule against all 30
picks and all earlier reserves. A rejected pick is replaced by the first
remaining reserve of its category, strictly in order. If a category has no
reserve left, its slot goes to soluble, as in 1.7.

### 1.9 Decisions of 2026-10-31 (coordinator)

1. Nucleotide 6-mers accepted (4-letter alphabet; protein chains stay on
   3-mers).
2. The v2/v3 changes are accepted: the wider exclusion set, the narrowed
   category definitions, scarcest category first, obsolete entries out,
   internal modified residues written as X, and the strict 4.0 Å cut.
3. The exclusion set is widened to MDPrepBench, MDStudyBench and every PDB
   entry the mdclaw checkout documents, with the same distinctness tests (1.4).
4. Membrane takes the same size cap as every other category (no ≤ 700-residue
   cap); it is refilled with the same greedy, and unfilled slots go to soluble.
5. A reference that keeps a non-standard polymer residue is rejected (1.6
   step 2), for picks and reserves alike.
6. 2AF1 stays provisionally. Whether its symmetry duplex can be stated
   precisely in a prompt is decided at build time; if not, the nucleic reserve
   is taken in order.
7. Terminal caps (ACE, NME, NMA, NHE, NH2) are allowed in a reference polymer
   at chain ends only (1.6 step 2), so 1PNE stays in the selection. Membrane 1
   and metal 1 stand as the rule's outcome, and 8DP0 stays out. The 30 in
   `selected.json` are final, and reserves are taken strictly in order.

Building the contracts (Part 3) then replaced two picks by their category's
next reserve, under the build rule that a case `build_prompt` cannot state
precisely takes the reserve: 2AF1 → 1JE8 and 1PNE → 1J7A (3.2).

### 1.10 Rule history

Each change below altered the rule, not a specific outcome, and none of them
used anything about MDClaw. The earlier outputs are kept in `selection/`.

- **v1** (`selected_v1_quota_order.json`) processed categories in quota order,
  admitted Dynabench single-domain-antibody and non-Ig complexes, and dropped
  modified residues inside a chain.
  - The complex step picked 1PPE (trypsin–inhibitor). That made all four
    trypsin–Ca metal candidates fail rule 1, so metal filled 1 of 2.
  - The farthest-point step filled "antibody" with three VHH–antigen complexes
    and "complex" with four Dynabench complexes.
- **v2** (`selected_v2_with_obsolete.json`):
  - categories processed scarcest first;
  - the antibody and complex definitions narrowed to the meaning of the axes;
  - an unknown residue inside a chain written `X` (it had cut 2OUE's strands
    and produced a spurious approximate match);
  - 1EDN excluded as a development task;
  - a missing `PROTRES` falling back to the sequence lengths.
- **v3** (`selected_v3_before_coordinator_rules.json`): obsolete RCSB entries
  excluded. There are 12 among the fetched entries, 10 of them in the pools
  (e.g. 2MM1 → 3RGK, 7UW7 → 9BKS). RCSB's data API does not serve them, so an
  agent cannot look them up there, and their missing keywords, method and flags
  read as maximal distance: 7UW7 had become the ATLAS seed and 2MM1 the MoDEL
  seed. One task among the 98, 022 3RVW, is itself obsolete; as an anchor it
  only loses its class and method features.
- **v4** (current): the decisions of 1.9.

## Part 2 — the result (v4)

### 2.1 Category pools

The pre-filters of 1.2–1.5 applied to the 10866 eligible projects. The
development set has 287 members: 101 from the cast (the 98, 038, 061 and D03)
and 186 external (185 deposit PDB IDs from MDPrepBench ∪ the mdclaw mentions,
plus MDStudyBench S01). Sequences are MDDB's metadata sequences.

| Pool step | membrane | antibody | complex | nanobody | ligand | nucleic | metal | soluble_charmm | soluble_amber |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| categorised | 55 | 39 | 407 | 220 | 193 | 56 | 13 | 1938 | 1530 |
| PDB ID not in the development set | 41 | 30 | 399 | 211 | 185 | 38 | 8 | 1911 | 1502 |
| atoms and polymer residues within the category's largest cast task | 22 | 21 | 337 | 175 | 135 | 38 | 8 | 1722 | 1418 |
| whole-system containment < 0.70 vs the development set (MDDB sequences) | 2 | 18 | 293 | 128 | 95 | 35 | 4 | 1699 | 1364 |
| every chain >= 30 residues < 0.70 vs every development-set chain (Ig: V domain) | 1 | 16 | 289 | 128 | 95 | 35 | 4 | 1695 | 1359 |
| deposit is a current RCSB entry (not obsolete) | 1 | 16 | 289 | 128 | 95 | 35 | 4 | 1694 | 1350 |

**30 picks: membrane 1, antibody 3, complex 4, nanobody 3, ligand 4, nucleic 4,
metal 1, soluble_charmm 5, soluble_amber 5.**

- Every pick was verified, satisfies all three sequence rules against the
  development set, and gave a result from `selection(record, deposit)`; that
  result is stored in `selected.json`, and rerunning `selection()` on the
  stored records reproduces it.
- 115 picks were attempted in greedy order: 30 kept, 21 kept as reserves, and
  64 dropped (`selection_log.json`):
  - 42 unstable references (last-third RMSD > 4.0 Å, up to 120 Å);
  - 14 with a reference chain unexplained against SEQRES — 1Q9A, the six 1VTN
    and four 2UZK replicas, 2OR1, and the Dynabench entries 4DW2 and 4M5Z.
    1Q9A, 1VTN and 2UZK are systems memo (5) also rejected by hand;
  - 3 that keep a non-standard polymer residue: 2OUE (MRA, RAP), 1JLP (HYP)
    and 1OUO (MSE);
  - 3 that are not a single chain;
  - 1 whose metal is not bound;
  - 1 without an `rmsds` analysis.

**Membrane: 1 of 4. Its 3 slots moved to soluble (ATLAS, MoDEL, ATLAS).**

- 22 of the 41 membrane projects not in the development set fit the cap.
- 10 of the 22 are receptors already among the 98 with another ligand: β2AR
  6PS0, 6PS5, 6E67, 6KR8; MT1 6ME2, 6ME5, 6PS8; 5-HT2A 6WGT, 6WH4; A2A 6PS7
  (whole-system containment 0.89–1.00).
- 10 more are GPCR–G-protein complexes that the dropped 700-residue cap used to
  exclude: 6OIJ, 6K42, 6NI3, 6OIK, 7CMU, 7DHI, 7DHR, 7E2Y, 7E2Z and 7BZ2. They
  share their Gβ1, Gγ2 and scFv16 chains with 6OT0 and 6XBL, which the mdclaw
  checkout documents (chain containment 1.00). Several also contain a receptor
  that is among the 98.
- 6QFA (GABA-A) is 0.97 against 6I53.
- The only distinct membrane system is the D2 receptor 7DFP.
- No other node contributes an eligible bilayer. jsc's 8 `ebrains` entries with
  a topology have 100 ps frames and no lipids, and oxf was unreachable (per
  memo (6), its all-atom GLIC runs are at 200 ps per frame).
- **There is no membrane reserve.**

**Metal: 1 of 2. Its slot moved to soluble (MoDEL).**

- The pool has 8 projects: 6RNT ✓; 2BFR (its Ca is not bound); 2I3H (unstable,
  6.09 Å); 8CPA (no `rmsds`).
- The other four — 1V2J, 1K1J, 1K1L and 1K1M — are bovine trypsin–Ca, the
  protein of MDPrepBench's P04, which the mdclaw checkout also documents
  (3PWB; containment 0.91–0.92).
- **There is no metal reserve.**

The coordinator's widening of the exclusion set (decision 3) also removed:
- **1AAR** (ubiquitin, 1.00 against 1UBQ and 2K39);
- **8DP0**, a nanobody at whole-system 0.74 against 7KKL. 7KKL is the
  SARS-CoV-2 spike plus the nanobody mNb6, so this is the VHH framework and
  background against a 1300-residue deposit. Chain-level containment is 0.67,
  below the threshold; the rule as decided compares whole systems.

### 2.2 The 30

Column notes:
- `res / chains / atoms` are polymer residues, reference polymer chains and
  `SYSTATS`.
- `max C` is the largest containment (3-mer; 6-mer for nucleotides), whole
  system / any chain ≥ 30 residues, against the 98 and against the full
  development set.
- Ranges are the deposit's own author numbering, from `selection()`.
  "removed" is an insert the reference cut out; "build n" is the number of
  residues the reference built.

| # | Category | PDB | node:accession | Title | res / chains / atoms | FF, water, T, ensemble | window ns | rep | RMSD Å (drift) | max C vs 98 (whole / chain) | max C vs dev. set | Selection (deposit numbering) |
|---|---|---|---|---|---|---|---:|---:|---|---|---|---|
| 1 | membrane | 7DFP | mmb:A024X | Human dopamine D2 receptor in complex with spiperone | 254 / 2 / 50951 | CHARMM36, TIP3P, 310 K, NPT | 1.0 | 1 | 2.98 (+0.48) | 0.21 / 0.23 | 0.31 / 0.28 | A:35–216,364–442 90 removed |
| 2 | antibody | 3MXW | inr:A00LA | Crystal structure Sonic hedgehog bound to the 5E1 fab… | 585 / 3 / 8961 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 2.51 (+0.54) | 0.49 / 0.31 | 0.57 / 0.33 | A:39–191; L:1–212; H:1–214 |
| 3 | antibody | 5Y9J | inr:A00LX | BAFF in complex with belimumab | 577 / 3 / 8654 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 2.73 (+0.55) | 0.55 / 0.55 | 0.55 / 0.55 | L:2–211; H:2–224 build 5; A:142–285 |
| 4 | antibody | 3L5W | inr:A00L8 | Crystal structure of the complex between IL-13 and C836 FAB | 540 / 3 / 8200 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 3.30 (+1.01) | 0.57 / 0.54 | 0.61 / 0.54 | L:1–213; H:1–223; I:7–110 build 3 |
| 5 | complex | 1LJ2 | inr:A001D | Recognition of eIF4G by Rotavirus NSP3 reveals a basis… | 265 / 4 / 4321 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 3.51 (+0.77) | 0.16 / 0.16 | 0.26 / 0.33 | A:207–312; B:206–315; C:138–159; D:133–159 |
| 6 | complex | 4MQV | inr:A007Y | Crystal complex of Rpa32c and Smarcal1 N-terminus | 91 / 2 / 1470 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 2.34 (+0.25) | 0.16 / 0.13 | 0.31 / 0.22 | A:204–268; B:5–30 |
| 7 | complex | 5SXP | inr:A009Z | STRUCTURAL BASIS FOR THE INTERACTION BETWEEN ITCH PRR… | 142 / 3 / 2263 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 3.39 (+0.26) | 0.18 / 0.16 | 0.34 / 0.27 | A:183–243; B:184–243; G:248–268 |
| 8 | complex | 3K1R | inr:A005C | Structure of harmonin NPDZ1 in complex with the SAM-PBM… | 266 / 2 / 4314 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 2.86 (-0.09) | 0.17 / 0.17 | 0.34 / 0.27 | A:1–192; B:388–461 |
| 9 | nanobody | 8IJZ | mmb:A05CE | anti-VEGF mutant | 123 / 1 / 1861 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1.0 | 2 | 2.04 (+0.14) | 0.48 / 0.46 | 0.64 / 0.53 | A:4–126 |
| 10 | nanobody | 6NI2 | mmb:A059A | Stabilized beta-arrestin 1-V2T subcomplex of a GPCR-G… | 113 / 1 / 1712 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1.0 | 3 | 3.93 (+0.52) | 0.45 / 0.40 | 0.66 / 0.57 | A:1–113 |
| 11 | nanobody | 7VNE | mmb:A05BH | Structure of the SARS-CoV-2 spike glycoprotein in… | 116 / 1 / 1736 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1.0 | 3 | 3.05 (+0.18) | 0.55 / 0.49 | 0.58 / 0.49 | W:2–117 |
| 12 | ligand | 4MRE | cin:A00DC | Crystal structure of the murine CD44 hyaluronan binding… | 150 / 1 / 2305 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1.0 | 1 | 2.92 (+0.38) | 0.11 / 0.11 | 0.31 / 0.24 | A:24–173 |
| 13 | ligand | 5YJ8 | cin:A000Y | Identification of a small molecule inhibitor for the… | 60 / 1 / 1000 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1.0 | 1 | 3.68 (+0.03) | 0.16 / 0.11 | 0.25 / 0.21 | A:549–608 |
| 14 | ligand | 3S0E | cin:A00AR | Apis mellifera OBP14 in complex with the odorant eugenol… | 119 / 1 / 1932 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1.0 | 1 | 3.01 (+0.41) | 0.16 / 0.14 | 0.32 / 0.22 | A:1–119 |
| 15 | ligand | 6MJ7 | cin:A0002 | Crystal structure of p62 ZZ domain in complex with free… | 54 / 1 / 806 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1.0 | 1 | 3.03 (+0.26) | 0.14 / 0.12 | 0.18 / 0.18 | A:118–171 |
| 16 | nucleic | 2AF1 | mmb:A017K | Structure of the DNA coiled-coil formed by d(CGATATATATAT) | 24 / 2 / 764 | n.r., TIP3P, 300 K, None | 1.0 | 1 | 3.44 (+0.91) | 0.00 / 0.00 | 0.00 / 0.00 | A:1–12,1–12 two copies on one deposit chain |
| 17 | nucleic | 1HLV | mmb:A017B | CRYSTAL STRUCTURE OF CENP-B(1-129) COMPLEXED WITH THE… | 42 / 2 / 1331 | n.r., SPCE, 298 K, None | 1.0 | 1 | 2.67 (-0.01) | 0.19 / 0.00 | 0.19 / 0.00 | C:1–21; B:1–21 |
| 18 | nucleic | 3JXC | mmb:A01E0 | Crystal structure of the P22 c2 repressor protein in… | 40 / 2 / 1274 | n.r., TIP3P, 300 K, None | 1.0 | 1 | 3.05 (+0.10) | 0.13 / 0.00 | 0.13 / 0.00 | A:21–40; B:1–20 |
| 19 | nucleic | 1JRN | mmb:A01DC | Orthorhombic form of Oxytricha telomeric DNA at 2.0A | 24 / 2 / 782 | n.r., TIP3P, 300 K, None | 1.0 | 1 | 1.17 (+0.31) | 0.14 / 0.00 | 0.14 / 0.00 | A:1001–1012; B:2001–2012 |
| 20 | metal | 6RNT | cin:A0008 | CRYSTAL STRUCTURE OF RIBONUCLEASE T1 COMPLEXED WITH… | 104 / 1 / 1495 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1.0 | 1 | 2.19 (+0.46) | 0.24 / 0.13 | 0.33 / 0.27 | A:1–104 ; metal CA105 |
| 21 | soluble_charmm | 2O6X | bsc:A0311 | Crystal Structure of ProCathepsin L1 from Fasciola hepatica | 310 / 1 / 4795 | CHARMM36m, TIP3P, 300 K, None | 1.0 | 3 | 2.37 (+0.08) | 0.14 / 0.25 | 0.24 / 0.33 | A:8–317 build 4 |
| 22 | soluble_charmm | 1J8R | bsc:A02NS | BINARY COMPLEX OF THE PAPG RECEPTOR-BINDING DOMAIN BOUND… | 196 / 1 / 3140 | CHARMM36m, TIP3P, 300 K, None | 1.0 | 3 | 2.17 (+0.36) | 0.17 / 0.10 | 0.24 / 0.24 | A:1–196 |
| 23 | soluble_charmm | 3LAE | bsc:A03DG | The crystal structure of a functionally unknown… | 81 / 1 / 1257 | CHARMM36m, TIP3P, 300 K, None | 1.0 | 3 | 2.17 (+0.19) | 0.18 / 0.13 | 0.29 / 0.22 | A:-2–78 |
| 24 | soluble_charmm | 2CWY | bsc:A02WZ | Crystal structure of conserved hypothetical protein,… | 94 / 1 / 1568 | CHARMM36m, TIP3P, 300 K, None | 1.0 | 3 | 2.20 (+0.17) | 0.21 / 0.17 | 0.33 / 0.22 | A:1–94 |
| 25 | soluble_charmm | 2P54 | bsc:A031Y | a crystal structure of PPAR alpha bound with SRC1… | 267 / 1 / 4282 | CHARMM36m, TIP3P, 300 K, None | 1.0 | 3 | 2.40 (+0.07) | 0.16 / 0.13 | 0.29 / 0.22 | A:202–468 |
| 26 | soluble_amber | 1PWT | mmb:A00W4 | THERMODYNAMIC ANALYSIS OF ALPHA-SPECTRIN SH3 AND TWO OF… | 61 / 1 / 1000 | Amber Parm99, TIP3P, 300 K, NPT | 1.0 | 1 | 3.10 (+0.47) | 0.19 / 0.12 | 0.34 / 0.25 | A:1–61 |
| 27 | soluble_amber | 1PNE | mmb:A00U8 | CRYSTALLIZATION AND STRUCTURE DETERMINATION OF BOVINE… | 139 / 1 / 2097 | Amber Parm99, TIP3P, 300 K, NPT | 1.0 | 1 | 2.85 (+1.06) | 0.16 / 0.14 | 0.29 / 0.21 | A:1–139 |
| 28 | soluble_amber | 1AJJ | mmb:A001O | LDL RECEPTOR LIGAND-BINDING MODULE 5, CALCIUM-COORDINATING | 37 / 1 / 513 | Amber Parm99, TIP3P, 300 K, NPT | 1.0 | 1 | 2.44 (+0.26) | 0.14 / 0.14 | 0.34 / 0.23 | A:4–40 |
| 29 | soluble_amber | 2CRO | mmb:A008D | STRUCTURE OF PHAGE 434 CRO PROTEIN AT 2.35 ANGSTROMS… | 65 / 1 / 1081 | Amber Parm99, TIP3P, 300 K, NPT | 1.0 | 1 | 1.91 (+0.33) | 0.19 / 0.11 | 0.37 / 0.24 | A:-1–63 |
| 30 | soluble_amber | 1C2A | mmb:A009E | CRYSTAL STRUCTURE OF BARLEY BBI | 120 / 1 / 1809 | Amber Parm99, TIP3P, 300 K, NPT | 1.0 | 1 | 3.77 (+0.67) | 0.12 / 0.10 | 0.22 / 0.12 | A:4–123 |

Across the 30:
- The largest whole-system containment between two picks is 0.51
  (3MXW–3L5W, two human Fab complexes that share constant domains). Next is
  0.43, between the nanobodies 8IJZ and 7VNE.
- Force fields: CHARMM36, CHARMM36m, ff99SB-ILDN, Parm99, and NAFlex
  (unrecorded). Waters: TIP3P and SPC/E (1HLV). Temperatures: 298, 300 and
  310 K. Windows: 1 ns, or 2.5 ns on inr. Replicas: 1–3.
- Licence strings are stored verbatim in `selected.json`: the CC BY 4.0
  wording for mmb, bsc and cin, `Apache License 2.0` for Dynarepo, and none for
  Dynabench (the CC BY-NC paper discrepancy noted in `CLAUDE.md` applies).

### 2.3 Reserves (ordered; take strictly in order within a category)

There is no membrane reserve and no metal reserve; a rejected 7DFP or 6RNT
sends its slot to soluble (1.8).

| rank | Category | PDB | node:accession | Title | res / chains / atoms | FF, water, T, ensemble | window ns | rep | RMSD Å (drift) | max C vs 98 (whole / chain) | max C vs dev. set | Selection (deposit numbering) |
|---|---|---|---|---|---|---|---:|---:|---|---|---|---|
| 1 | antibody | 4ETQ | inr:A00LI | Vaccinia virus D8L IMV envelope protein in complex with… | 664 / 3 / 10270 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 2.64 (+0.37) | 0.52 / 0.37 | 0.52 / 0.37 | A:2–220 build 3; L:2–213; X:3–235 build 7 |
| 2 | antibody | 5O14 | inr:A00LR | Co-crystal structure of a cross-reactive bactericidal… | 676 / 3 / 10203 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 3.46 (+0.38) | 0.55 / 0.65 | 0.56 / 0.65 | B:14–255 build 12; D:1–212; C:1–222 |
| 3 | antibody | 5X0T | inr:A00LW | Crystal structure of CD147 C2 domain in complex with Fab… | 506 / 3 / 7662 | CHARMM36m, TIP3P, 300 K, NPT | 2.5 | 3 | 2.93 (+0.00) | 0.54 / 0.40 | 0.54 / 0.40 | A:21–235; B:21–233; E:25–102 |
| 1 | complex | 3O6Q | inr:A005M | The Structure of SpoIISA and SpoIISB, a Toxin -… | 376 / 4 / 6194 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 2.45 (+0.34) | 0.18 / 0.15 | 0.28 / 0.32 | A:97–241; B:9–51; C:98–241; D:9–52 |
| 2 | complex | 4KT5 | inr:A007O | Structure of GrlR-GrlA complex | 317 / 3 / 5142 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 3.36 (+0.42) | 0.16 / 0.14 | 0.27 / 0.28 | A:-2–112; B:1–114; C:9–96 |
| 3 | complex | 6B12 | inr:A00AI | Structure of Tne2 in complex with Tni2 | 272 / 2 / 4265 | CHARMM36m, TIP3P, 310 K, NPT | 2.5 | 3 | 2.02 (+0.10) | 0.16 / 0.25 | 0.28 / 0.25 | A:290–408; B:1–153 |
| 1 | nanobody | 6IR2 | mmb:A0598 | Crystal structure of red fluorescent protein mCherry… | 124 / 1 / 1852 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1.0 | 3 | 1.50 (+0.18) | 0.48 / 0.48 | 0.67 / 0.59 | B:16–139 |
| 2 | nanobody | 6X05 | mmb:A059P | Nup133 (aa55-481) from S. cerevisiae bound by VHH-SAN4 | 120 / 1 / 1831 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1.0 | 3 | 2.16 (+0.27) | 0.38 / 0.36 | 0.53 / 0.41 | K:3–122 |
| 3 | nanobody | 6B73 | mmb:A058W | Crystal Structure of a nanobody-stabilized active state… | 121 / 1 / 1821 | Amber ff99SB-ILDN, TIP3P, 300 K, NPT | 1.0 | 3 | 2.66 (+0.34) | 0.44 / 0.38 | 0.58 / 0.46 | C:4–124 |
| 1 | ligand | 2PQL | cin:A00BY | Crystal Structure of Anopheles gambiae D7R4-tryptamine… | 144 / 1 / 2393 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1.0 | 1 | 2.09 (-0.03) | 0.12 / 0.10 | 0.22 / 0.20 | A:1–144 |
| 2 | ligand | 3G19 | cin:A00HP | The structure of the Caulobacter crescentus clpS… | 84 / 1 / 1431 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1.0 | 1 | 2.23 (+0.19) | 0.12 / 0.10 | 0.27 / 0.24 | A:36–119 |
| 3 | ligand | 1KJR | cin:A00IF | Crystal Structure of the human galectin-3 CRD in complex… | 138 / 1 / 2298 | Amber ff99SB-ILDN, TIP3P, 298 K, NPT | 1.0 | 1 | 1.44 (+0.08) | 0.15 / 0.12 | 0.29 / 0.18 | A:113–250 |
| 1 | nucleic | 1JE8 | mmb:A01DM | Two-Component response regulator NarL/DNA Complex: DNA… | 40 / 2 / 1268 | n.r., TIP3P, 300 K, None | 1.0 | 1 | 2.98 (+0.12) | 0.13 / 0.00 | 0.13 / 0.00 | C:1–20; D:21–40 |
| 2 | nucleic | 4F6N | mmb:A01E2 | Crystal structure of Kaiso zinc finger DNA binding… | 38 / 2 / 1203 | n.r., TIP3P, 300 K, None | 1.0 | 1 | 3.13 (+0.02) | 0.00 / 0.00 | 0.00 / 0.00 | E:20–38 build 1; D:1–19 |
| 3 | nucleic | 1VTN | mmb:A01DQ | CO-CRYSTAL STRUCTURE OF THE HNF-3/FORK HEAD… | 26 / 2 / 824 | n.r., TIP3P, 300 K, None | 1.0 | 1 | 2.27 (+0.02) | 0.00 / 0.00 | 0.00 / 0.00 | A:1–13; B:21–33 |
| 1 | soluble_charmm | 1HOE | bsc:A02N0 | CRYSTAL STRUCTURE DETERMINATION, REFINEMENT AND THE… | 74 / 1 / 1076 | CHARMM36m, TIP3P, 300 K, None | 1.0 | 3 | 3.45 (+1.64) | 0.21 / 0.12 | 0.30 / 0.17 | A:1–74 |
| 2 | soluble_charmm | 5N76 | bsc:A03TC | Crystal structure of the apo-form of the CO… | 66 / 1 / 1005 | CHARMM36m, TIP3P, 300 K, None | 1.0 | 3 | 3.47 (+0.36) | 0.22 / 0.14 | 0.38 / 0.25 | B:1–66 build 3 |
| 3 | soluble_charmm | 7ONN | bsc:A040V | Crystal structure of PBP3 transpeptidase domain from E.… | 410 / 1 / 6191 | CHARMM36m, TIP3P, 300 K, None | 1.0 | 3 | 2.72 (+0.47) | 0.18 / 0.19 | 0.33 / 0.25 | A:68–570 build 7 |
| 1 | soluble_amber | 1J7A | mmb:A00O3 | STRUCTURE OF THE ANABAENA FERREDOXIN D68K MUTANT | 98 / 1 / 1457 | Amber Parm99, TIP3P, 300 K, NPT | 1.0 | 1 | 3.16 (+1.16) | 0.19 / 0.11 | 0.39 / 0.33 | A:1–98 |
| 2 | soluble_amber | 1A5D | mmb:A004D | GAMMAE CRYSTALLIN FROM RAT LENS | 173 / 1 / 2849 | Amber Parm99, TIP3P, 300 K, NPT | 1.0 | 1 | 1.93 (+0.31) | 0.11 / 0.08 | 0.23 / 0.15 | A:1–174 |
| 3 | soluble_amber | 1HP9 | mmb:A00JB | kappa-Hefutoxins: a novel Class of Potassium Channel… | 22 / 1 / 337 | Amber Parm99, TIP3P, 300 K, NPT | 1.0 | 1 | 2.63 (+0.36) | 0.20 / 0.00 | 0.20 / 0.00 | A:1–22 |

### 2.4 For the build step

None of the following was a selection criterion; each is read from the records.

- **2AF1** (provisional, decision 6): the reference duplex is two copies of the
  deposit's single chain A, related by crystal symmetry. (An earlier version of
  this note compared it with 052 1NAJ; that was wrong: 1NAJ's deposit has two
  chains, A and B, and its prompt names both.) If the duplex cannot be stated
  precisely, take reserve 1JE8. It could not (3.2).
- **7DFP**: the reference holds deposit chain A as two polymers, 35–140 and
  148–216+364–442.
  - 141–147 are unresolved in the deposit and left unbuilt.
  - The 90-residue ICL3/fusion insert between 216 and 364 is removed, and 216
    is bonded to 364.
- **6MJ7**: the ligand is a free arginine. The deposit's two zinc ions of the
  ZZ domain are not in the reference.
- **1AJJ** (MoDEL) is a calcium-binding module simulated without its calcium,
  because MoDEL strips metals (cf. 1ARD among the 98).
- **1PNE**'s reference keeps the deposit's N-terminal ACE cap. A cap is
  allowed by 1.6 step 2.
- Residues the reference built: 5Y9J H 138–142, 3L5W I 23–25, 2O6X A 94–97.
- 1HLV uses SPC/E water.
- One diversity feature is imprecise for one system: ligand size comes from
  `SYSTATS − PROTATS`, which MDDB gets wrong for 3S0E (1 atom, where its
  reference `LIG`, eugenol, has 24). This affects only distances, not
  eligibility.

## Part 3 — building the 30 contracts (2026-10-31)

Same integrity rules as Parts 1–2. No MDClaw, pi, agent, MD or campaign result
was used. Everything below was produced by `scripts/build_test_tasks.py`, which
reads the three sources a cast contract is built from: MDDB metadata, the RCSB
deposit and the reference bundle.

### 3.1 How a contract is built

- **Numbering and names.** Tasks are numbered 101–130 in the template's dispatch
  order: membrane, ligand, metal, complex, nucleic, nanobody, antibody, then
  ATLAS and MoDEL. Within a category they follow the greedy pick order.
  Directory axis names are the cast's (`soluble` for both soluble axes);
  `task.json` carries `axis` `soluble_charmm` / `soluble_amber` and
  `split: "test"`.
- **Bundles** were fetched with `fetch_reference` into the harness bundle root
  (`/data1/rkp00079/rku00161/references/<node>_<accession>`, as `experiments.py`
  resolves it). Their SHA-256 values are recorded the way the cast records
  them. The mmCIF deposits went into `benchmarks/mddatabench/_deposits` (30 new
  files), as for the cast.
- **`selection`.**
  - The record of Part 1 is passed to `selection()`.
  - The depositor's named chain is used when it is a SEQRES twin (7VNE chain U,
    as `resolve_chain` does for the cast).
  - `effective_components` is written wherever a chain has several ranges or
    an omitted span, one component per reference backbone, as the 14 membrane
    contracts of the cast do.
  - `stated_protonation` is computed per reference polymer.
  - `modified_residues_reverted` holds the MODRES records inside the
    simulated ranges.
  - `excluded_components` lists the deposit's non-polymer components on the
    selected chains that the reference does not keep. They are read from the
    mmCIF, as the audit reads them: RCSB's PDB-format 1C52 calls its haem HEC
    and its mmCIF calls it HEM, and the cast follows the mmCIF.
  - Terminal caps the deposit carries and the reference lacks are named in the
    same exclusion sentence. The cast's 028 1DFJ leaves its ACE unsaid, and it
    is the one cast contract the audit reports a cap mismatch for.
  - `stated_disulfides` is computed with the contract audit's own functions:
    the deposit's struct_conn pairs against the reference topology's S–S
    bonds, in the prompt's construct frame and converted to deposit numbering.
- **`prompt.md`** comes only from `_task_builder.build_prompt`.
  - The builder gained one optional argument, `ligands`, which writes the
    ligand bullet the cast's ligand prompts have carried since 2026-08-25
    ("Include the **X** ligand bound to the protein, and treat it as having
    expected formal net charge **q** at pH 7"). Those bullets had been added
    outside the builder.
  - The ligand is the deposit component whose heavy-atom formula equals that
    of the reference `LIG`; the CCD formula is used when the deposit models the
    ligand only in part.
  - The charge is the CCD formal charge + (reference H − CCD H), the
    derivation memo 2026-08-25 records.
  - The structural-metal sentence names the ions the reference keeps bound.
  - New tests: `tests/test_benchmark/test_task_builder.py` (the bullet's
    wording; the builder writes 037's shipped prompt exactly; 060's shipped
    prompt is unchanged with and without the argument).
- **`md_calibration`.**
  - `calibration.calibrate` is run with the cast's window (1 ns; 2.5 ns on
    inr) and slack 4, pooled over every replica.
  - Then `slack_window_sd` per check, `slack_rationale`,
    `adversarial_headroom_note` (both verbatim from the cast) and `per_check`
    are added.
  - `per_check` holds each check's headroom, which is how far the degenerate
    baseline lands below the band in window SD (rank correlation 0, total
    fluctuation 0, radius of gyration 0.85 × the mean window Rg). It also holds
    the held-out requirement, the smallest slack at which every leave-one-out
    fold rejects nothing.
  - Requirements above 4 carry the cast's `held_out_note`, and the sweep runs
    over 0–6, 8, 10, 12 and 16, the values the cast records.
  - The code was rebuilt from the cast's numbers. It reproduces `per_check` of
    all 98 cast tasks exactly, which
    `tests/test_benchmark/test_build_test_tasks.py` checks.
  - **A defect found and fixed during the build:** the first calibration run
    left `window_ns` to `calibrate()`'s default of 100 frames at the
    reference's own step. That gives 10 ns on inr, 0.1 ns on MoDEL and
    0.1–0.2 ns on NAFlex. Those 16 calibrations were redone with the cast
    window. The 14 whose step is 10 ps were already at 1 ns and were reused.
- **`scoring`** is the block 96 cast tasks share, verbatim.
  - 078 and 097 differ only in that their radius-of-gyration check is demoted
    to a diagnostic (weight 0, `demoted_because`), because a structure
    compressed to 85 % lands inside the slack.
  - That is the one demotion the current cast carries. The rank-correlation
    demotions of 008 and 095 were dropped when the fluctuation-magnitude check
    moved to `@2` (fda021e, 2026-09-06), and those checks are scored.
  - The build applies the same rule: the radius-of-gyration check is demoted
    when its headroom is below 4.
- **`solve_time_network_policy`** is the cast's, with the deny list extended to
  every MDDB node host: `irb.mddbr.eu`, `mmb.mddbr.eu`, `oxford.mddbr.eu`,
  `jsc.mddbr.eu`, `rpbs.mddbr.eu` and `devmddb.rc.ufl.edu`, the last of which is
  not under `mddbr.eu`.
- **`license`** is recorded verbatim. The three Dynabench tasks return none and
  carry the cast's `license_note`.

**Check against the cast.** The same derivation, applied to the 98 shipped
tasks with the cast's own exclusion lists, gives (`build/regenerate_cast.json`):

- 76 prompts identical;
- 17 identical except the molecule name in the first sentence. The cast's
  multi-entity inr and MoDEL prompts name the deposit title, from generator
  inputs that were never committed; the builder's `molecule_name` names the
  first two polymer entities;
- 3 that differ for known cast-side reasons:
  - 008: the 6I53 twin-piece assignment of 1.6;
  - 012: 6ME3's prompt predates `effective_components`, so its join sentence
    sits before the omission sentence;
  - 036: older ligand wording, "Treat the **AMH** ligand as…";
- 029: the cast chose the contacting chains A + C by hand;
- 042: a seven-residue peptide that MDDB flattened into one `LIG`.

The derived ligand names and charges equal all eight cast ligand bullets, and
the derived exclusion lists equal the cast's except 074/075, where the
derivation reads HEC from the PDB-format file and the cast HEM from the mmCIF
(which is why the build reads the mmCIF).

### 3.2 Replacements

Both replacements are the next reserve of the slot's category, taken in order:

| slot | replaced | by | why |
|---|---|---|---|
| nucleic | 2AF1 | **1JE8** | The reference duplex is two copies of the deposit's single chain A; the second strand is generated by a crystallographic operation (REMARK 350 BIOMT). `build_prompt` can only write "chain A residues 1–12 and 1–12", which does not say that the second strand is a symmetry mate. The contract audit reports it too: "selection maps 12 polymer sites but the reference topology maps 24". |
| MoDEL | 1PNE | **1J7A** | The reference keeps the deposit's N-terminal ACE cap. That is allowed by decision 7, but `build_prompt` has no cap statement, and the audit reports "reference contains ACE at A:1, which the prompt never names". Adding a cap sentence for one task would be an ad hoc builder change. |

Both replacements pass every check of Parts 1–2. 1JE8 and 1J7A were the first
reserves of their categories.

### 3.3 The 30 tasks

| task | PDB | node:accession | selection (deposit numbering) | rep | window ns | windows | held-out max rejected, slack 4 (no slack) | headroom < 4 | prompt carries |
|---|---|---|---|---:|---:|---:|---|---|---|
| 101_membrane_7dfp | 7DFP | mmb:A024X | A:35–216,364–442 | 1 | 1 | 100 | — | — | excl SIP; 2 backbone components; bilayer DPPC |
| 102_ligand_4mre | 4MRE | cin:A00DC | A:24–173 | 1 | 1 | 100 | — | — | ligand 2C9 (0); excl DMS |
| 103_ligand_5yj8 | 5YJ8 | cin:A000Y | A:549–608 | 1 | 1 | 100 | — | total | ligand 8W9 (+1); excl SO4 |
| 104_ligand_3s0e | 3S0E | cin:A00AR | A:1–119 | 1 | 1 | 100 | — | — | ligand EOL (0) |
| 105_ligand_6mj7 | 6MJ7 | cin:A0002 | A:118–171 | 1 | 1 | 100 | — | — | ligand ARG (+1); excl DIO ZN |
| 106_metal_6rnt | 6RNT | cin:A0008 | A:1–104 | 1 | 1 | 100 | — | total, radius | ligand 2AM (-2); keeps calcium |
| 107_complex_1lj2 | 1LJ2 | inr:A001D | A:207–312; B:206–315; C:138–159; D:133–159 | 1 | 2.5 | 100 | — | — | excl AU |
| 108_complex_4mqv | 4MQV | inr:A007Y | A:204–268; B:5–30 | 1 | 2.5 | 100 | — | — | — |
| 109_complex_5sxp | 5SXP | inr:A009Z | A:183–243; B:184–243; G:248–268 | 1 | 2.5 | 100 | — | — | — |
| 110_complex_3k1r | 3K1R | inr:A005C | A:1–192; B:388–461 | 1 | 2.5 | 100 | — | — | — |
| 111_nucleic_1je8 | 1JE8 | mmb:A01DM | C:1–20; D:21–40 | 1 | 1 | 100 | — | — | — |
| 112_nucleic_1hlv | 1HLV | mmb:A017B | C:1–21; B:1–21 | 1 | 1 | 100 | — | rank | — |
| 113_nucleic_3jxc | 3JXC | mmb:A01E0 | A:21–40; B:1–20 | 1 | 1 | 100 | — | — | excl TL |
| 114_nucleic_1jrn | 1JRN | mmb:A01DC | A:1001–1012; B:2001–2012 | 1 | 1 | 100 | — | — | excl K |
| 115_nanobody_8ijz | 8IJZ | mmb:A05CE | A:4–126 | 2 | 1 | 100 | 0.00 (0.46) | — | — |
| 116_nanobody_6ni2 | 6NI2 | mmb:A059A | A:1–113 | 3 | 1 | 102 | 0.00 (0.15) | — | — |
| 117_nanobody_7vne | 7VNE | mmb:A05BH | U:2–117 | 3 | 1 | 102 | 0.03 (0.24) | — | — |
| 118_antibody_3mxw | 3MXW | inr:A00LA | A:39–191; L:1–212; H:1–214 | 3 | 2.5 | 102 | 0.00 (0.85) | — | excl CA SO4 ZN |
| 119_antibody_5y9j | 5Y9J | inr:A00LX | L:2–211; H:2–224; A:142–285 | 3 | 2.5 | 102 | 0.00 (0.74) | — | build H:5 |
| 120_antibody_3l5w | 3L5W | inr:A00L8 | L:1–213; H:1–223; I:7–110 | 3 | 2.5 | 102 | 0.00 (0.59) | — | build I:3 |
| 121_soluble_2o6x | 2O6X | bsc:A0311 | A:8–317 | 3 | 1 | 102 | 0.12 (0.91) | — | S–S formed 2, reduced 1; build A:4 |
| 122_soluble_1j8r | 1J8R | bsc:A02NS | A:1–196 | 3 | 1 | 102 | 0.00 (0.15) | — | HIP 162 |
| 123_soluble_3lae | 3LAE | bsc:A03DG | A:-2–78 | 3 | 1 | 102 | 0.03 (0.24) | — | excl EDO PO4 |
| 124_soluble_2cwy | 2CWY | bsc:A02WZ | A:1–94 | 3 | 1 | 102 | 0.00 (0.38) | — | — |
| 125_soluble_2p54 | 2P54 | bsc:A031Y | A:202–468 | 3 | 1 | 102 | 0.00 (0.24) | — | excl 735 |
| 126_soluble_1pwt | 1PWT | mmb:A00W4 | A:1–61 | 1 | 1 | 100 | — | — | — |
| 127_soluble_1j7a | 1J7A | mmb:A00O3 | A:1–98 | 1 | 1 | 100 | — | — | excl FES |
| 128_soluble_1ajj | 1AJJ | mmb:A001O | A:4–40 | 1 | 1 | 100 | — | — | excl CA SO4 |
| 129_soluble_2cro | 2CRO | mmb:A008D | A:-1–63 | 1 | 1 | 100 | — | — | — |
| 130_soluble_1c2a | 1C2A | mmb:A009E | A:4–123 | 1 | 1 | 100 | — | — | S–S formed 0, reduced 10 |

"headroom < 4" names the checks whose degenerate baseline lands inside the
slack. Of these, only the radius of gyration is demoted in `scoring`, as in
the cast. "held-out" is the leave-one-replica-out rejected fraction at slack 4,
with the fraction without slack in brackets. The prompts are in
`benchmarks/mddatabench/tasks/<id>/prompt.md`.

### 3.4 Verification

- **Contract audit.** `audit_task_cast` over all 128 tasks gives 126 clean.
  Every one of the 30 test tasks is clean. The two findings are the cast's own
  and were the same before the build (`build/audit_cast_before.json`,
  `audit_cast_after.json`): 028 1DFJ's unstated ACE cap, and 036 1CEB's older
  ligand wording. In the drafts, the audit was also what showed 2AF1 and 1PNE
  cannot be stated (3.2), and it found the two disulfide differences that 2O6X
  and 1C2A now state.
- **Idempotence of the dataset scripts.** Both apply scripts are idempotent on
  the 128-task dataset.
  - `apply_nonpolymer_audit.py` was rerun over the audit CSV, extended by 30
    rows computed from the build: it changed nothing, and `dataset_id` stays
    v0.6.
  - `apply_dataset_v05.py` changed 0 of 128.
  - Both scripts had a defect, fixed with a test each: they reset `dataset_id`
    to their own version whenever it differed, so a rerun on v0.6 would have
    downgraded it to v0.4 or v0.5 and appended their changelog line again. They
    now bump only from an older version.
- **Tests.** `pytest tests/` was run in both images with
  `MDDATABENCH_BUNDLE_ROOT` set, so the slow, bundle-dependent checks of the
  dataset ran too, over all 128 tasks.
  Each image has 4 failures and no others:
  - `mdclaw.sif`: 2017 passed, 4 failed;
  - `mddatabench-runtime-nomdclaw.sif`: 2013 passed, 4 skipped, 4 failed.

  None of the failures involves a test task or a changed file:
  - two `test_source_overlay` image-mode cases fail only in `mdclaw.sif`, whose
    `/opt/mdclaw` is the very prefix they bind, and pass in the runtime image;
  - two `test_sandbox` cases fail only in the runtime image (it cannot bind
    `/run`) and pass in `mdclaw.sif`;
  - `test_build_missing_classification[029_complex_1e3u]` (2 tests) fails in
    both: the bundle's delta is 3 against a recorded 2. It fails the same way
    at HEAD, with every change of this work stashed, and is skipped unless
    `MDDATABENCH_BUNDLE_ROOT` is set.

  Every test therefore passes in at least one of the two images, apart from
  the pre-existing 029 record. New and changed tests:
  - `test_build_test_tasks.py`: the per-check derivation is reproduced for all
    98 cast tasks, and the scoring block for 031/078/097/008;
  - the ligand-bullet tests in `test_task_builder.py`;
  - the no-downgrade tests of both apply scripts;
  - the build-missing fixture and expectations, extended by 119, 120 and 121
    (all internal builds);
  - `test_boundary_contract_cast.py` and `test_apply_dataset_v05.py`, now
    counting the 128 tasks dataset.json lists instead of a fixed 98.
- **Calibration, held out.**
  - 11 test tasks have two or more replicas: nanobody 3, antibody 3, ATLAS 5.
    Leaving one replica out and scoring its windows against the band of the
    rest, at the cast's slack of 4, 8 of the 11 reject nothing.
  - The three that reject something: 117 7VNE (1 of 34 windows), 123 3LAE
    (1 of 34) and 121 2O6X (4 of 34; its radius of gyration needs slack 5).
    Without slack the median rejected fraction is 0.38.
  - Three per-check requirements exceed 4 and carry the cast's `held_out_note`:
    117 total fluctuation 6, 121 radius of gyration 5, 123 total fluctuation 10.
  - The other 19 tasks are single-replica, so no held-out measurement exists.
    These are cin, mmb membrane / NAFlex / MoDEL, and Dynarepo, which lists
    three replicas in `mds` but leaves `mdcount` null, so — as for the cast's
    025–030 — the contract carries one replica and calibrates on replica 1.
  - Headroom below the slack:
    - 106 6RNT radius of gyration (−1.72 window SD): demoted to a diagnostic,
      as 078 and 097 are; its total fluctuation is also below (1.90);
    - 103 5YJ8 total fluctuation (3.67);
    - 112 1HLV rank correlation (3.82).

    The last three are recorded in `per_check` and stay scored, following the
    current cast (fda021e). The fluctuation magnitude is upper-limit-only, so
    the frozen baseline cannot pass it.
- **Positive control.** An MDClaw-free positive control through
  `score_portable_submission` was not possible without running MD:
  - The portable path needs an OpenMM `system.xml`, a minimised state, a
    trajectory of at least 1 ns with its solvent, and an energy file.
  - MDDB's references are solvent-stripped (MoDEL and ligate record SOL 0)
    and ship no OpenMM System.
  - Producing a trajectory is MD, which the rules exclude.

  The nearest available evidence covers each side. On the md side, the
  held-out folds above score independent reference runs against the band. On
  the prep side, the contract audit compares every prompt with its reference
  topology and deposit.
- **Harness.**
  - `list_benchmark_tasks` lists 128 tasks.
  - No code path reads `split`: `init_experiment`, `list_benchmark_tasks`,
    `collect_experiment` and `scripts/paper_figures.py` key on task IDs and
    axes. So `test` needs no change anywhere.
  - A dry `init_experiment`, init only, put 121_soluble_2o6x × {cli_skill_sif,
    cli_sif, sif_only} into `testset-20261031/init-dry/experiment`. It used a
    stub MDClaw checkout and the no-MDClaw runtime image, and `run_experiment`
    was never called.
  - It gave 3 attempts and `dataset_id` MDDataBench-v0.6. Each workspace's
    `task_prompt.md` is byte-identical to the task's `prompt.md`, and no
    workspace file mentions an MDDB host or the accession.

### 3.5 What was not possible, and what I am unsure of

- **Ligand charges** were derived as the cast's were (CCD formal charge +
  reference H − CCD H). The cast also ran each one through MDClaw's
  Dimorphite-DL path to confirm a matching protonation candidate exists; that
  is MDClaw code, so I did not do it. The charges are:
  - 102 2C9 0
  - 103 8W9 +1 (CCD 0, one extra H in the reference)
  - 104 EOL 0
  - 105 ARG +1
  - 106 2AM −2 (CCD 0, reference H 12 vs CCD 14: the phosphate dianion)
- **105 6MJ7's ligand is a free arginine**, which the deposit and the bullet
  name `ARG`, the same three letters as the amino acid. The prompt is precise
  ("the **ARG** ligand bound to the protein"), but an agent could misread it.
- **130 1C2A** is a Bowman–Birk inhibitor that MoDEL simulated with all ten of
  its disulfides reduced. The prompt states each reduced pair, so the task is
  precise, but the system is chemically unusual. **121 2O6X**'s reference
  likewise leaves the deposit's Cys253–Cys302 reduced.
- **Molecule names** in the first sentence follow `molecule_name`, which
  names the first two polymer entities. For multi-entity inr systems the cast
  used the deposit title instead, from inputs I could not reproduce
  (3.1, "Check against the cast"). No check reads the name.
- **Deny list:** only the test tasks carry the extended deny list. The cast's
  deny list lacks the oxf, jsc, rpbs, ufl, irb and mmb hosts; I left it as it
  is.
- **The audit CSV** `_audits/nonpolymer-20260914.csv` was extended in place
  with 30 rows, as asked, so the file name's date no longer describes all of
  its rows.
- **Not fixed (cast-side):** the cast's 028 (ACE unstated) and 036 (old
  ligand wording) audit findings, and the two cast tests that fail with
  bundles present (029, 3.4).

## Reproduce

```bash
cd /data1/rkp00079/rku00161/MDDataBench
W=/data1/rkp00079/rku00161/testset-20261031
PYTHONPATH=$PWD python3 scripts/scan_mddb_pool.py --workdir $W          # pool + counts
PYTHONPATH=$PWD python3 scripts/verify_candidates.py --workdir $W --validate-cast
PYTHONPATH=$PWD python3 scripts/select_test_set.py --workdir $W         # selected.json
# Part 3, inside the image (gemmi, scipy):
S="apptainer exec --no-home --bind /data1/rkp00079 --env PYTHONPATH=$PWD /data1/rkp00079/mdclaw.sif python"
$S scripts/build_test_tasks.py fetch       # bundles + mmCIF deposits
$S scripts/build_test_tasks.py calibrate   # windows, cached under $W/calibration
$S scripts/build_test_tasks.py build       # tasks/101-130/{task.json,prompt.md}
$S scripts/build_test_tasks.py regenerate  # the cast check of 3.1
python3 scripts/build_test_tasks.py finalize   # dataset.json + audit CSV rows
```

System python 3.12 with numpy is enough. Everything fetched is cached under
`$W/cache` (MDDB listings, structures and analyses; RCSB deposits and entry
metadata; MDStudyBench's task). A rerun therefore makes no network request
except for nodes that failed (oxf). It reads the mdclaw checkout and the
MDPrepBench task directory read-only.
