# タスク 100 件 (2026-08-23 選定・訓練 70 / 評価 30)

MDDB の全 8 ノードを走査した 35602 プロジェクトから選定した。選定条件と各閾値の
根拠は `docs/memo.md` の 2026-08-22 (6)(7) と 2026-08-23 の項にある。

- **鎖:範囲** は参照配列を寄託の SEQRES に照合して復元したもの。プロンプトにはこれを書く。
- **RMSD** は MDDB の `rmsds` から取った参照軌道の後 1/3 平均 (Å)。4.0 Å 超は不採用。
- **rep** はレプリカ数。2 本以上あるものは較正の帯を全レプリカの窓から作る。
- 分割は参照配列の 3-mer 包含率 0.70 でクラスタリングし、クラスタ単位で行った。

## 膜 (14)

| # | 分割 | ノード:accession | PDB | 鎖:残基範囲 | 残基 | 力場 | 水 | T | 窓 | rep | RMSD | 内容 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T001 | **評価** | mmb:A023K | [6I53](https://www.rcsb.org/structure/6I53) | E:35-337 E:440-472 A:45-358+419-453(融合部60残基除去) … | 1698 | CHARMM36 | TIP3P | 310 | 1 ns | 1 | 3.49 | Cryo-EM structure of the human synaptic alpha1-beta3 |
| T002 | **評価** | mmb:A023M | [6ME3](https://www.rcsb.org/structure/6ME3) | A:14-211+213-496(融合部1残基除去) | 482 | CHARMM36 | TIP3P | 310 | 1 ns | 1 | 3.58 | XFEL crystal structure of human melatonin receptor M |
| T003 | **評価** | mmb:A023O | [6PS2](https://www.rcsb.org/structure/6PS2) | A:52-254+415-494(融合部160残基除去) | 283 | CHARMM36 | TIP3P | 310 | 1 ns | 1 | 2.55 | XFEL beta2 AR structure by ligand exchange from Timo |
| T004 | 訓練 | mmb:A01M3 | [5YC8](https://www.rcsb.org/structure/5YC8) | A:18-216 A:329-407 | 278 | CHARMM36 | TIP3P | 300 | 1 ns | 1 | 2.66 | Crystal structure of rationally thermostabilized M2  |
| T005 | 訓練 | mmb:A01M7 | [5ZK3](https://www.rcsb.org/structure/5ZK3) | A:20-216+331-407(融合部114残基除去) | 274 | CHARMM36 | TIP3P | 300 | 1 ns | 1 | 2.68 | Crystal structure of rationally thermostabilized M2  |
| T006 | 訓練 | mmb:A01M9 | [5ZK8](https://www.rcsb.org/structure/5ZK8) | A:20-216+332-407(融合部115残基除去) | 273 | CHARMM36 | TIP3P | 300 | 1 ns | 1 | 2.49 | Crystal structure of M2 muscarinic acetylcholine rec |
| T007 | 訓練 | mmb:A01MA | [5ZKB](https://www.rcsb.org/structure/5ZKB) | A:19-219 A:326-405 | 281 | CHARMM36 | TIP3P | 300 | 1 ns | 1 | 2.99 | Crystal structure of rationally thermostabilized M2  |
| T008 | 訓練 | mmb:A01MB | [6A93](https://www.rcsb.org/structure/6A93) | A:3-199+286-372(融合部86残基除去) | 284 | CHARMM36 | TIP3P | 300 | 1 ns | 1 | 2.32 | Crystal structure of 5-HT2AR in complex with risperi |
| T009 | 訓練 | mmb:A01MC | [6A94](https://www.rcsb.org/structure/6A94) | A:3-199+286-372(融合部86残基除去) | 284 | CHARMM36 | TIP3P | 300 | 1 ns | 1 | 2.60 | Crystal structure of 5-HT2AR in complex with zotepin |
| T010 | 訓練 | mmb:A023T | [6GT3](https://www.rcsb.org/structure/6GT3) | A:8-217 A:324-410 | 297 | CHARMM36 | TIP3P | 310 | 1 ns | 1 | 3.70 | Crystal Structure of the A2A-StaR2-bRIL562 in comple |
| T011 | 訓練 | mmb:A024E | [6JZH](https://www.rcsb.org/structure/6JZH) | A:24-233 A:340-429 | 300 | CHARMM36 | TIP3P | 310 | 1 ns | 1 | 3.43 | Structure of human A2A adenosine receptor in complex |
| T012 | 訓練 | mmb:A024G | [6KUX](https://www.rcsb.org/structure/6KUX) | A:10-154+164-208(融合部9残基除去) A:315-393 | 269 | CHARMM36 | TIP3P | 310 | 1 ns | 1 | 3.78 | Crystal structures of the alpha2A adrenergic recepto |
| T013 | 訓練 | mmb:A024H | [6KUY](https://www.rcsb.org/structure/6KUY) | A:14-153 A:164-208 A:315-393 | 264 | CHARMM36 | TIP3P | 310 | 1 ns | 1 | 3.71 | Crystal structure of the alpha2A adrenergic receptor |
| T014 | 訓練 | mmb:A023S | [6ZDV](https://www.rcsb.org/structure/6ZDV) | A:9-216+323-410(融合部106残基除去) | 296 | CHARMM36 | TIP3P | 310 | 1 ns | 1 | 3.68 | Crystal structure of stabilized A2A adenosine recept |

## 抗体-抗原 (10)

| # | 分割 | ノード:accession | PDB | 鎖:残基範囲 | 残基 | 力場 | 水 | T | 窓 | rep | RMSD | 内容 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T015 | **評価** | inr:A00KU | [1AHW](https://www.rcsb.org/structure/1AHW) | A:1-214 B:1-214 C:4-211 | 636 | CHARMM36m | TIP3P | 300 | 2.5 ns | 3 | 2.95 | A COMPLEX OF EXTRACELLULAR DOMAIN OF TISSUE FACTOR W |
| T016 | **評価** | inr:A00KY | [2DD8](https://www.rcsb.org/structure/2DD8) | H:2-221 L:1-212 S:5-196 | 624 | CHARMM36m | TIP3P | 300 | 2.5 ns | 3 | 2.48 | Crystal Structure of SARS-CoV Spike Receptor-Binding |
| T017 | **評価** | inr:A00L1 | [2VIS](https://www.rcsb.org/structure/2VIS) | A:1-210 B:1-221 C:16-282 | 698 | CHARMM36m | TIP3P | 300 | 2.5 ns | 3 | 3.13 | INFLUENZA VIRUS HEMAGGLUTININ, (ESCAPE) MUTANT WITH  |
| T018 | 訓練 | inr:A00MF | [1AY7](https://www.rcsb.org/structure/1AY7) | A:1-96 B:1-89 | 185 | CHARMM36m | TIP3P | 300 | 2.5 ns | 3 | 2.03 | RIBONUCLEASE SA COMPLEX WITH BARSTAR |
| T019 | 訓練 | inr:A00KV | [1DQJ](https://www.rcsb.org/structure/1DQJ) | A:1-214 B:1-210 C:1-129 | 553 | CHARMM36m | TIP3P | 300 | 2.5 ns | 3 | 3.59 | CRYSTAL STRUCTURE OF THE ANTI-LYSOZYME ANTIBODY HYHE |
| T020 | 訓練 | inr:A00KW | [1MLC](https://www.rcsb.org/structure/1MLC) | A:1-214 B:1-218 E:1-129 | 561 | CHARMM36m | TIP3P | 300 | 2.5 ns | 3 | 2.56 | MONOCLONAL ANTIBODY FAB D44.1 RAISED AGAINST CHICKEN |
| T021 | 訓練 | inr:A00L4 | [3EOA](https://www.rcsb.org/structure/3EOA) | L:1-214 H:1-220 I:1-179 | 613 | CHARMM36m | TIP3P | 300 | 2.5 ns | 3 | 2.92 | Crystal structure the Fab fragment of Efalizumab in  |
| T022 | 訓練 | inr:A00LC | [3RVW](https://www.rcsb.org/structure/3RVW) | A:1-222 C:1-211 D:1-222 | 655 | CHARMM36m | TIP3P | 300 | 2.5 ns | 3 | 2.84 |  |
| T023 | 訓練 | inr:A00LF | [3WD5](https://www.rcsb.org/structure/3WD5) | A:6-157 L:1-213 H:1-219 | 584 | CHARMM36m | TIP3P | 300 | 2.5 ns | 2 | 3.10 | Crystal structure of TNFalpha in complex with Adalim |
| T024 | 訓練 | inr:A00LO | [5CBA](https://www.rcsb.org/structure/5CBA) | A:1-127 B:1-112 E:11-71 | 300 | CHARMM36m | TIP3P | 300 | 2.5 ns | 3 | 2.43 | 3B4 in complex with CXCL13 - 3B4-CXCL13 |

## 蛋白-蛋白 (6)

| # | 分割 | ノード:accession | PDB | 鎖:残基範囲 | 残基 | 力場 | 水 | T | 窓 | rep | RMSD | 内容 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T025 | **評価** | inr:A000C | [1AVA](https://www.rcsb.org/structure/1AVA) | A:1-403 C:1-181 | 584 | CHARMM36m | TIP3P | 310 | 2.5 ns | 1 | 2.22 | AMY2/BASI PROTEIN-PROTEIN COMPLEX FROM BARLEY SEED |
| T026 | **評価** | inr:A000F | [1B6C](https://www.rcsb.org/structure/1B6C) | A:1-107 B:14-339 | 433 | CHARMM36m | TIP3P | 310 | 2.5 ns | 1 | 3.41 | CRYSTAL STRUCTURE OF THE CYTOPLASMIC DOMAIN OF THE T |
| T027 | 訓練 | inr:A000B | [1AKJ](https://www.rcsb.org/structure/1AKJ) | A:1-276 B:2-99 C:1-9 … | 611 | CHARMM36m | TIP3P | 310 | 2.5 ns | 1 | 2.54 | COMPLEX OF THE HUMAN MHC CLASS I GLYCOPROTEIN HLA-A2 |
| T028 | 訓練 | inr:A000H | [1DFJ](https://www.rcsb.org/structure/1DFJ) | E:1-124 I:2-457 | 580 | CHARMM36m | TIP3P | 310 | 2.5 ns | 1 | 2.82 | RIBONUCLEASE INHIBITOR COMPLEXED WITH RIBONUCLEASE A |
| T029 | 訓練 | inr:A000J | [1E3U](https://www.rcsb.org/structure/1E3U) | A:2-244 A:2-246 | 488 | CHARMM36m | TIP3P | 310 | 2.5 ns | 1 | 2.59 | MAD structure of OXA10 class D beta-lactamase |
| T030 | 訓練 | inr:A000R | [1FFW](https://www.rcsb.org/structure/1FFW) | A:1-128 B:36-103 | 196 | CHARMM36m | TIP3P | 310 | 2.5 ns | 1 | 2.93 | CHEY-BINDING DOMAIN OF CHEA IN COMPLEX WITH CHEY WIT |

## ナノボディ (5)

| # | 分割 | ノード:accession | PDB | 鎖:残基範囲 | 残基 | 力場 | 水 | T | 窓 | rep | RMSD | 内容 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T031 | **評価** | mmb:A02JY | [1KXV](https://www.rcsb.org/structure/1KXV) | C:2-120 | 119 | ff99SB-ILDN | TIP3P | 300 | 1 ns | 3 | 1.48 | Camelid VHH Domains in Complex with Porcine Pancreat |
| T032 | **評価** | mmb:A02JZ | [1XFP](https://www.rcsb.org/structure/1XFP) | A:2-132 | 131 | ff99SB-ILDN | TIP3P | 300 | 1 ns | 3 | 2.04 | Crystal structure of the CDR2 germline reversion mut |
| T033 | 訓練 | mmb:A057R | [3TPK](https://www.rcsb.org/structure/3TPK) | A:5-124 | 120 | ff99SB-ILDN | TIP3P | 300 | 1 ns | 3 | 2.21 | Crystal structure of the oligomer-specific KW1 antib |
| T034 | 訓練 | mmb:A057Y | [4KFZ](https://www.rcsb.org/structure/4KFZ) | C:6-128 | 123 | ff99SB-ILDN | TIP3P | 300 | 1 ns | 3 | 1.55 | Crystal structure of LMO2 and anti-LMO2 VH complex |
| T035 | 訓練 | mmb:A0594 | [6GWN](https://www.rcsb.org/structure/6GWN) | B:1-115 | 115 | ff99SB-ILDN | TIP3P | 300 | 1 ns | 3 | 1.83 | Crystal Structure of Stabilized Active Plasminogen A |

## リガンド (10)

| # | 分割 | ノード:accession | PDB | 鎖:残基範囲 | 残基 | 力場 | 水 | T | 窓 | rep | RMSD | 内容 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T036 | **評価** | cin:A0004 | [1CEB](https://www.rcsb.org/structure/1CEB) | A:3-82 | 80 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 1.85 | THE STRUCTURE OF THE NON-COVALENT COMPLEX OF RECOMBI |
| T037 | **評価** | cin:A0006 | [1G74](https://www.rcsb.org/structure/1G74) | A:1-131 | 131 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 2.80 | Toward changing specificity: adipocyte lipid binding |
| T038 | **評価** | cin:A0007 | [1IKT](https://www.rcsb.org/structure/1IKT) | A:6-120 | 115 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 1.41 | LIGANDED STEROL CARRIER PROTEIN TYPE 2 (SCP-2) LIKE  |
| T039 | 訓練 | cin:A000F | [3IKD](https://www.rcsb.org/structure/3IKD) | A:11-123 | 113 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 1.65 | Structure-Based Design of Novel PIN1 Inhibitors (I) |
| T040 | 訓練 | cin:A002A | [3N2U](https://www.rcsb.org/structure/3N2U) | A:1-158 | 158 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 2.41 | Crystal structure of the catalytic domain of human M |
| T041 | 訓練 | cin:A000I | [4ERF](https://www.rcsb.org/structure/4ERF) | A:4-95 | 92 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 2.59 | crystal structure of MDM2 (17-111) in complex with c |
| T042 | 訓練 | cin:A000J | [4MN3](https://www.rcsb.org/structure/4MN3) | A:1-56 | 56 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 2.61 | Chromodomain antagonists that target the polycomb-gr |
| T043 | 訓練 | cin:A000O | [5OD1](https://www.rcsb.org/structure/5OD1) | A:3-96 | 94 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 3.36 | Structure of the engineered metalloesterase MID1sc10 |
| T044 | 訓練 | cin:A000P | [5OH3](https://www.rcsb.org/structure/5OH3) | A:20-124 | 105 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 1.80 | Cereblon isoform 4 from Magnetospirillum gryphiswald |
| T045 | 訓練 | cin:A002C | [6J3O](https://www.rcsb.org/structure/6J3O) | A:35-140 | 106 | ff99SB-ILDN | TIP3P | 298 | 1 ns | 1 | 2.61 | Crystal structure of the human PCAF bromodomain in c |

## 核酸 (14)

| # | 分割 | ノード:accession | PDB | 鎖:残基範囲 | 残基 | 力場 | 水 | T | 窓 | rep | RMSD | 内容 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T046 | **評価** | mmb:A01DE | [1A66](https://www.rcsb.org/structure/1A66) | C:2-11 B:2-11 | 24 | 未記録 | TIP3P | 300 | 1 ns | 1 | 1.89 | SOLUTION NMR STRUCTURE OF THE CORE NFATC1/DNA COMPLE |
| T047 | **評価** | mmb:A017E | [1KX5](https://www.rcsb.org/structure/1KX5) | A:38-135 B:21-102 C:12-119 … | 764 | 未記録 | TIP3P | 298 | 1 ns | 1 | 2.44 | X-Ray Structure of the Nucleosome Core Particle, NCP |
| T048 | **評価** | mmb:A01A6 | [1NAJ](https://www.rcsb.org/structure/1NAJ) | A:2-11 A:2-11 | 24 | 未記録 | TIP3P | 298 | 1 ns | 1 | 1.83 | High resolution NMR Structure Of DNA Dodecamer Deter |
| T049 | **評価** | mmb:A017Z | [2RN1](https://www.rcsb.org/structure/2RN1) | A:2-15 B:2-15 | 32 | 未記録 | TIP3P | 300 | 1 ns | 1 | 2.07 | Liquid crystal solution structure of the kissing com |
| T050 | 訓練 | mmb:A01DF | [1C7U](https://www.rcsb.org/structure/1C7U) | C:2-19 C:2-19 | 40 | 未記録 | TIP3P | 300 | 1 ns | 1 | 2.74 | Complex of the DNA binding core domain of the transc |
| T051 | 訓練 | mmb:A01DH | [1H9T](https://www.rcsb.org/structure/1H9T) | X:2-18 Y:2-18 | 38 | 未記録 | TIP3P | 300 | 1 ns | 1 | 2.41 | FADR, FATTY ACID RESPONSIVE TRANSCRIPTION FACTOR FRO |
| T052 | 訓練 | mmb:A01DJ | [1IV6](https://www.rcsb.org/structure/1IV6) | C:2-12 B:2-12 | 26 | 未記録 | TIP3P | 300 | 1 ns | 1 | 1.86 | Solution Structure of the DNA Complex of Human TRF1 |
| T053 | 訓練 | mmb:A01DO | [1QN5](https://www.rcsb.org/structure/1QN5) | D:2-13 C:2-13 | 28 | 未記録 | TIP3P | 300 | 1 ns | 1 | 2.12 | Crystal structure of the G(-26) Adenovirus major lat |
| T054 | 訓練 | mmb:A01DS | [1ZGW](https://www.rcsb.org/structure/1ZGW) | B:2-17 C:2-17 | 36 | 未記録 | TIP3P | 300 | 1 ns | 1 | 2.69 | NMR structure of E. Coli Ada protein in complex with |
| T055 | 訓練 | mmb:A01DT | [2HDC](https://www.rcsb.org/structure/2HDC) | B:2-16 C:2-16 | 34 | 未記録 | TIP3P | 300 | 1 ns | 1 | 2.61 | STRUCTURE OF TRANSCRIPTION FACTOR GENESIS/DNA COMPLE |
| T056 | 訓練 | mmb:A01DV | [2L1G](https://www.rcsb.org/structure/2L1G) | C:2-15 B:2-15 | 32 | 未記録 | TIP3P | 300 | 1 ns | 1 | 2.85 | RDC refined solution structure of the THAP zinc fing |
| T057 | 訓練 | mmb:A01DW | [2LT7](https://www.rcsb.org/structure/2LT7) | E:2-18 D:2-18 | 38 | 未記録 | TIP3P | 300 | 1 ns | 1 | 3.06 | Solution NMR structure of Kaiso zinc finger DNA bind |
| T058 | 訓練 | mmb:A01DX | [2OR1](https://www.rcsb.org/structure/2OR1) | A:2-19 B:3-20 | 40 | 未記録 | TIP3P | 300 | 1 ns | 1 | 2.77 | RECOGNITION OF A DNA OPERATOR BY THE REPRESSOR OF PH |
| T059 | 訓練 | mmb:A01DZ | [3F27](https://www.rcsb.org/structure/3F27) | B:2-15 A:2-15 | 32 | 未記録 | TIP3P | 300 | 1 ns | 1 | 2.42 | Structure of Sox17 Bound to DNA |

## 金属/CV19 (4)

| # | 分割 | ノード:accession | PDB | 鎖:残基範囲 | 残基 | 力場 | 水 | T | 窓 | rep | RMSD | 内容 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T060 | **評価** | mmb:MCV1900208 | [4OW0](https://www.rcsb.org/structure/4OW0) | A:4-315 | 312 | ff14SB | TIP3P | 298 | 1 ns | 1 | 3.24 | X-Ray Structural and Biological Evaluation of a Seri |
| T061 | 訓練 | mmb:MCV1900237 | [6M0J](https://www.rcsb.org/structure/6M0J) | A:1-339 E:85-208 | 463 | ff14SB | OPC | 300 | 1 ns | 1 | 1.66 | Crystal structure of SARS-CoV-2 spike receptor-bindi |
| T062 | 訓練 | mmb:MCV1900209 | [6W9C](https://www.rcsb.org/structure/6W9C) | A:4-315 | 312 | ff14SB | TIP3P | 298 | 1 ns | 1 | 2.46 | The crystal structure of papain-like protease of SAR |
| T063 | 訓練 | mmb:MCV1900210 | [6WRH](https://www.rcsb.org/structure/6WRH) | A:7-318(不一致1) | 312 | ff14SB | TIP3P | 298 | 1 ns | 1 | 2.54 | The crystal structure of Papain-Like Protease of SAR |

## ATLAS (24)

| # | 分割 | ノード:accession | PDB | 鎖:残基範囲 | 残基 | 力場 | 水 | T | 窓 | rep | RMSD | 内容 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T064 | **評価** | bsc:A02K9 | [16PK](https://www.rcsb.org/structure/16PK) | A:1-415 | 415 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.90 | PHOSPHOGLYCERATE KINASE FROM TRYPANOSOMA BRUCEI BISU |
| T065 | **評価** | bsc:A02KA | [1A62](https://www.rcsb.org/structure/1A62) | A:1-130 | 130 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.99 | CRYSTAL STRUCTURE OF THE RNA-BINDING DOMAIN OF THE T |
| T066 | **評価** | bsc:A02KB | [1AB1](https://www.rcsb.org/structure/1AB1) | A:1-46 | 46 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 1.23 | SI FORM CRAMBIN |
| T067 | **評価** | bsc:A02KC | [1AF7](https://www.rcsb.org/structure/1AF7) | A:1-274 | 274 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 3.27 | CHER FROM SALMONELLA TYPHIMURIUM |
| T068 | **評価** | bsc:A02KE | [1AIL](https://www.rcsb.org/structure/1AIL) | A:1-73 | 73 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 3.93 | N-TERMINAL FRAGMENT OF NS1 PROTEIN FROM INFLUENZA A  |
| T069 | **評価** | bsc:A02KF | [1AOL](https://www.rcsb.org/structure/1AOL) | A:1-228 | 228 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 3.17 | FRIEND MURINE LEUKEMIA VIRUS RECEPTOR-BINDING DOMAIN |
| T070 | **評価** | bsc:A02KL | [1BGF](https://www.rcsb.org/structure/1BGF) | A:1-124 | 124 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 3.25 | STAT-4 N-DOMAIN |
| T071 | **評価** | bsc:A02KN | [1BQ8](https://www.rcsb.org/structure/1BQ8) | A:1-54 | 54 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.61 | Rubredoxin (Methionine Mutant) from Pyrococcus Furio |
| T072 | 訓練 | bsc:A02KQ | [1BXY](https://www.rcsb.org/structure/1BXY) | A:1-60 | 60 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.13 | CRYSTAL STRUCTURE OF RIBOSOMAL PROTEIN L30 FROM THER |
| T073 | 訓練 | bsc:A02KT | [1C1K](https://www.rcsb.org/structure/1C1K) | A:1-217 | 217 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.27 | BACTERIOPHAGE T4 GENE 59 HELICASE ASSEMBLY PROTEIN |
| T074 | 訓練 | bsc:A02KU | [1C52](https://www.rcsb.org/structure/1C52) | A:1-131 | 131 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.64 | THERMUS THERMOPHILUS CYTOCHROME-C552: A NEW HIGHLY T |
| T075 | 訓練 | bsc:A02KZ | [1CPQ](https://www.rcsb.org/structure/1CPQ) | A:1-129 | 129 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.22 | CYTOCHROME C' FROM RHODOPSEUDOMONAS CAPSULATA |
| T076 | 訓練 | bsc:A02L0 | [1CTF](https://www.rcsb.org/structure/1CTF) | A:1-74 | 74 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.25 | STRUCTURE OF THE C-TERMINAL DOMAIN OF THE RIBOSOMAL  |
| T077 | 訓練 | bsc:A02LF | [1DOW](https://www.rcsb.org/structure/1DOW) | A:1-205 | 205 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.74 | CRYSTAL STRUCTURE OF A CHIMERA OF BETA-CATENIN AND A |
| T078 | 訓練 | bsc:A02LG | [1DPT](https://www.rcsb.org/structure/1DPT) | A:1-117 | 117 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 4.00 | D-DOPACHROME TAUTOMERASE |
| T079 | 訓練 | bsc:A02LV | [1EWF](https://www.rcsb.org/structure/1EWF) | A:1-456 | 456 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 3.95 | THE 1.7 ANGSTROM CRYSTAL STRUCTURE OF BPI |
| T080 | 訓練 | bsc:A02LW | [1EZ3](https://www.rcsb.org/structure/1EZ3) | A:1-127 | 127 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 3.15 | CRYSTAL STRUCTURE OF THE NEURONAL T-SNARE SYNTAXIN-1 |
| T081 | 訓練 | bsc:A02M2 | [1FCZ](https://www.rcsb.org/structure/1FCZ) | A:1-235 | 235 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.01 | ISOTYPE SELECTIVITY OF THE HUMAN RETINOIC ACID NUCLE |
| T082 | 訓練 | bsc:A02M3 | [1FD3](https://www.rcsb.org/structure/1FD3) | A:1-41 | 41 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 1.91 | HUMAN BETA-DEFENSIN 2 |
| T083 | 訓練 | bsc:A02M5 | [1FK5](https://www.rcsb.org/structure/1FK5) | A:1-93 | 93 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.31 | STRUCTURAL BASIS OF NON-SPECIFIC LIPID BINDING IN MA |
| T084 | 訓練 | bsc:A02M6 | [1FM4](https://www.rcsb.org/structure/1FM4) | A:1-159 | 159 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.34 | CRYSTAL STRUCTURE OF THE BIRCH POLLEN ALLERGEN BET V |
| T085 | 訓練 | bsc:A02MF | [1G38](https://www.rcsb.org/structure/1G38) | A:1-393 | 393 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.88 | ADENINE-SPECIFIC METHYLTRANSFERASE M. TAQ I/DNA COMP |
| T086 | 訓練 | bsc:A02MH | [1G6G](https://www.rcsb.org/structure/1G6G) | A:1-127 | 127 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.12 | X-RAY STRUCTURE OF THE N-TERMINAL FHA DOMAIN FROM S. |
| T087 | 訓練 | bsc:A02MP | [1GQV](https://www.rcsb.org/structure/1GQV) | A:1-135 | 135 | CHARMM36m | TIP3P | 300 | 1 ns | 3 | 2.36 | Atomic Resolution (0.98A) Structure of Eosinophil-De |

## MoDEL (13)

| # | 分割 | ノード:accession | PDB | 鎖:残基範囲 | 残基 | 力場 | 水 | T | 窓 | rep | RMSD | 内容 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T088 | **評価** | mmb:A0001 | [12CA](https://www.rcsb.org/structure/12CA) | A:5-259 | 255 | Parm99 | TIP3P | 300 | 1 ns | 1 | 1.85 | ALTERING THE MOUTH OF A HYDROPHOBIC POCKET. STRUCTUR |
| T089 | **評価** | mmb:A000G | [1A1W](https://www.rcsb.org/structure/1A1W) | A:1-83 | 83 | Parm99 | TIP3P | 300 | 1 ns | 1 | 2.80 | FADD DEATH EFFECTOR DOMAIN, F25Y MUTANT, NMR MINIMIZ |
| T090 | **評価** | mmb:A000H | [1ANX](https://www.rcsb.org/structure/1ANX) | A:2-317 | 316 | Parm99 | TIP3P | 300 | 1 ns | 1 | 2.37 | THE CRYSTAL STRUCTURE OF A NEW HIGH-CALCIUM FORM OF  |
| T091 | **評価** | mmb:A000C | [1APO](https://www.rcsb.org/structure/1APO) | A:1-42 | 42 | Parm99 | TIP3P | 300 | 1 ns | 1 | 3.76 | THREE-DIMENSIONAL STRUCTURE OF THE APO FORM OF THE N |
| T092 | 訓練 | mmb:A000N | [1AA3](https://www.rcsb.org/structure/1AA3) | A:1-63 | 63 | Parm99 | TIP3P | 300 | 1 ns | 1 | 3.44 | C-TERMINAL DOMAIN OF THE E. COLI RECA, NMR, MINIMIZE |
| T093 | 訓練 | mmb:A0015 | [1AG4](https://www.rcsb.org/structure/1AG4) | A:1-103 | 103 | Parm99 | TIP3P | 300 | 1 ns | 1 | 3.35 | NMR STRUCTURE OF SPHERULIN 3A (S3A) FROM PHYSARUM PO |
| T094 | 訓練 | mmb:A001D | [1AH9](https://www.rcsb.org/structure/1AH9) | A:1-71 | 71 | Parm99 | TIP3P | 300 | 1 ns | 1 | 3.25 | THE STRUCTURE OF THE TRANSLATIONAL INITIATION FACTOR |
| T095 | 訓練 | mmb:A000J | [1ARD](https://www.rcsb.org/structure/1ARD) | A:1-29 | 29 | Parm99 | TIP3P | 300 | 1 ns | 1 | 3.32 | STRUCTURES OF DNA-BINDING MUTANT ZINC FINGER DOMAINS |
| T096 | 訓練 | mmb:A001N | [1AY7](https://www.rcsb.org/structure/1AY7) | A:1-96 B:1-89 | 185 | Parm99 | TIP3P | 300 | 1 ns | 1 | 1.84 | RIBONUCLEASE SA COMPLEX WITH BARSTAR |
| T097 | 訓練 | mmb:A00BS | [1DFW](https://www.rcsb.org/structure/1DFW) | A:1-25 | 25 | Parm99 | TIP3P | 300 | 1 ns | 1 | 3.69 | CONFORMATIONAL MAPPING OF THE N-TERMINAL SEGMENT OF  |
| T098 | 訓練 | mmb:A011R | [1TBA](https://www.rcsb.org/structure/1TBA) | A:1-67 B:1-180 | 247 | Parm99 | TIP3P | 300 | 1 ns | 1 | 3.93 | SOLUTION STRUCTURE OF A TBP-TAFII230 COMPLEX: PROTEI |
| T099 | 訓練 | mmb:A014L | [1VYC](https://www.rcsb.org/structure/1VYC) | A:1-65 | 65 | Parm99 | TIP3P | 300 | 1 ns | 1 | 3.41 | Neurotoxin from Bungarus candidus |
| T100 | 訓練 | mmb:A002J | [2AXF](https://www.rcsb.org/structure/2AXF) | A:1-276 B:1-99 C:1-10 | 385 | Parm99 | TIP3P | 300 | 1 ns | 1 | 2.66 | The Immunogenicity of a Viral Cytotoxic T Cell Epito |

