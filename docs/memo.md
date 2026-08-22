# Working Memo

Running record for MDDataBench: what was run, what the numbers were, what was
decided, and why. Newest entries go at the top. Append as work continues; do
not rewrite past entries when a later finding contradicts them — add the
correction and say what it overturns.

The entries below the extraction were written in
[matsunagalab/mdclaw](https://github.com/matsunagalab/mdclaw)'s `docs/memo.md`
before this repository existed and are copied here verbatim. They refer to
paths as they were at the time: `benchmarks/mddatabench/scripts/*.py` are now
package modules under `mddatabench/`, and
`docs/research/db_derived_benchmark_validation.md` is now
`docs/validation-design.md`. The originals stay in mdclaw.

---

## 2026-08-22 (2) — 金属サイト: ベンチが MDClaw のバグを名指しし、両者を直した

D03 の `residue_atom_counts` が挙げた 3 残基を追ったところ、参照・提出・採点器の三方に問題があった。

**参照の亜鉛は非結合 12-6 で、我々と同一パラメータ.** MDDB は全プロジェクトに `topology.prmtop` を
配っており、このリポジトリはそれを取得していなかった。読むと `type Zn2+, charge +2.0, rmin 1.271 A,
bonds 0`、つまり結合モデルではない。**我々が構築する系とパラメータまで一致する** (sigma 0.2265 nm)。
残基名も CYM 3 / HIP 1 / HIE 10 / CYS 5 で PDB からの推測と完全一致し、S-S はゼロ。

**Cys4 亜鉛サイトは参照でも我々でも壊れている.** Zn-SG を全長で測ると:

| | 脱プロトン化 (CYM) | 中性 (CYS) |
|---|---|---|
| 参照 1 us | 2.00-2.06 A (sd 0.07) | 平均 5.4-6.8 A、最大 13.6 A |
| 我々 1 ns | 2.02-2.04 A | 平均 5.0-12.0 A |

参照は 4 本中 2 本しか脱プロトン化しておらず、残り 2 本は外れる。さらに D01/D02 では亜鉛が
**GLN191:OE1 に 1.75 A まで寄って再配位している**。単に半開きなのではなく組み替わっている。
我々は propka まかせで CYM が 1 本だけ、保持も 1 本。非結合 12-6 イオンは電荷が引きつける数の
チオラートしか保持しない、という一点で両者の差が説明できる。

**MDClaw は亜鉛配位 Cys 2 本を互いのジスルフィドにしていた.** 6W9C 鎖 C の SG(192)-SG(224) は
3.00 A で、距離判定の 3.0 A 窓の内側。`system.xml` に実結合 (0.2038 nm, k=138909) が入り、本番中に
2.04 A まで引き寄せられてサイトが化学的に破壊された。全鎖で見ると偽陽性は 4 件あり、そのうち
`A270-B270`/`A270-C270` は結晶接触ではなく **3 鎖の Cys270 が共有する第 2 の亜鉛 (C:ZN401) の配位子**
だった。金属ガード (同一金属の 2 配位子を結ばない) と原子価ガード (1 硫黄 1 ジスルフィド) で
偽陽性 4 件 → 0 件、BPTI の実ジスルフィド 3 本 (2.01-2.03 A) は保持。閾値 3.5 A は実測 (6W9C 鎖 A の
Zn-S 3.21 A) から決めた。

**MDClaw のプロトン化は金属を見ていなかった.** `protonation.py` に `ZN`/`metal` の語がゼロ。
split が protein と ion を分けるため pdb2pqr は金属を見られない。構造全体が見える `prepare_complex`
側で検出し、**Cys 配位子のみ CYM を割り当てる** (His はどちらの窒素が配位するかで互変異性が決まるので
報告のみ)。サイト成立条件は「側鎖ドナー 2 本以上、最近接 2.9 A 以内」。実測で 4OW0 の 4 本すべてが
CYM になった。`guardrail_codes.py` の `# --- metals ---` は見出しだけで中身が空だったので、
配位子を残したまま金属が選択から落ちる場合の警告も入れた。

**採点器の期待値をトポロジーから読むようにした.** 参照は prmtop の結合リスト、提出は
`system.xml` の HarmonicBondForce + constraint。CONECT はメタデータで、実測すると本数が違う
(D01 で System 135523 本 対 topology 91993 本)。金属配位残基は**プロトン化のみ** carve-out し、
identity 比較は残す。配位が走行中維持されたかは weight 0.0 の新カテゴリ `diagnostic` で報告のみ。

**negative controls: subspace 検定が機能していない.** 5 つの負のベースラインはすべて正しく落ちるが、
**本物の実行も落ちる**。しかも `anm_ensemble` の RMSIP 0.749 が実 MD の 0.704 を**上回る**。
ダイナミクスを持たないモデルが実 MD より高得点である以上、この検定は 312 残基系で何も判別していない。
`anm_ensemble` が正しく落ちているのもクロックのおかげで、subspace はクロックが捕まえないものを
何も捕まえていない。参照は 10 ps 間隔 100002 フレーム = 1 us なので 1 ns 窓が 1000 本取れる。
窓分布による自己較正へ移行すべき (ただし窓は独立ではない)。

**レビューで見つかった、自分で入れた欠陥.** codex に MDClaw を、pi (kimi-k3) に MDDataBench を
レビューさせた (codex は MDDataBench 側でフィルタにより応答不能)。重いものだけ:

- 挿入ブロックのインデントで既存の警告処理が `for` ループに取り込まれ、split 失敗時に未定義変数参照
- 全鎖のプロトン化状態を各単鎖ファイルに渡していた (多量体で必ず失敗)
- 金属の生存判定を元素名だけで見ており、同元素の金属が 2 つあり片方だけ残る場合に誤判定
- **「System を読んでいる」が実装と食い違い**、実際は PDB の CONECT + テンプレート推論を読んでいた
- `metal_atoms` のラベルが chain と挿入コードを落とし、多量体で金属サイトが dict キー衝突で消える
- `load_submission` が `_load_system` より先に無防備に deserialize し、壊れた提出で採点器が落ちる回帰
- 位置を「金属でも溶媒でもないもの」と否定形で定義しており、リガンド 1 個で全位置がずれる
- 原子価表の S 上限 2 は、スルホンアミド・硫酸・DMSO を誤って不合格にする

いずれも「単一鎖・単一金属でしか検証していない実装が一般入力で壊れる」という同一の型。
現行 3 タスクは全て単量体・単一亜鉛なので、テストで塞いだ (MDClaw 8 件、MDDataBench 5 件を新規追加)。

## 2026-08-22 — 新タスク D01-D03 (PLpro) でベンチを端から端まで通し、採点器の 3 つの欠陥を潰した

MDDB から配列アラインメントで選び直した 3 タスク (6W9C / 6WRH / 4OW0、いずれも
papain-like protease、Amber ff14SB / TIP3P / 298 K / NPT、参照 1 µs) を solve して
採点した。SLURM 実測: min 約 18 s、eq 約 1 分、prod 約 4.5 分、系は 135696 / 141023 /
146299 原子。**採点が完走したのは今回が初めて**で、そこで壊れていたのは提出物ではなく
採点器だった。

**(a) CONECT が hybrid-36 で書かれている。** `submitted_disulfides` は CONECT の各欄を
`int()` で読み、失敗したら「malformed CONECT record」を返して S-S 判定そのものを捨てて
いた。実測すると D02 の topology は CONECT 136002 行のうち **64544 行が 10 進では 1 欄も
読めない**: PDB は通し番号が 99999 を超えると hybrid-36 に切り替わり (`A0000` = 100000)、
OpenMM はそれを忠実に書く。つまり**溶媒を入れた系では S-S 判定が必ず捨てられていた**。
3 タスク全滅の原因はこれ。`hy36decode` を入れて仕様の境界 (99999 / A0000 / ZZZZZ =
43770015 / a0000 / zzzzz = 87440031) で検証した。`MAX_PDB_SERIAL` は不要になったので削除。

**(b) precondition が「報告するだけ」で門番になっていなかった。** D01 は 311 残基しか
作れておらず参照 312 の contract 原子 3 個 (`312:N/CA/C`) が解決できない。
`contract_atoms_resolvable` は FAIL を記録するが処理は続き、`kabsch` に 933x3 のフレームと
936x3 の目標が渡って `ValueError: matmul` で**採点が落ちた**。原因は提出側にあるので
スキップではなく `subspace_beyond_structure_only_model` を「評価不能につき不合格」にした。

**(c) 採点対象のノードが軌道の祖先とは限らなかった。** `find_node` は「その種別で最後に
completed したノード」を選んでいた。d03-6wrh は completed な topo が 2 つあり min は
topo_002 から、d04-4ow0 は completed な prep が 2 つあり prod に繋がるのは prep_004 だけ。
今回はたまたま一致したが、一致を保証するものは何も無かった。`parent_node_ids` を prod から
遡る方式に変えた。

**(d) 不合格なのに詳細文が「一致」と言っていた。** モノマーが対応付かないと per-residue
比較は 1 度も走らないのに、`findings` が空なので「identical after canonicalising
protonation」「every residue matches」と出力されていた。`; not compared: no monomer
pairing` に変えた。

**採点結果 (修正後).**

| task | prep | md | 実質的な不一致 |
|---|---|---|---|
| D01 6W9C | 0.455 (5/11) | 0.750 (3/4) | 311 残基 (参照 312)、C 末端 1 残基欠落、余分な S-S 1 本 |
| D02 6WRH | 0.545 (6/11) | 0.750 (3/4) | 316 残基 (参照 312)、N 末端側に 4 残基余分 |
| D03 4OW0 | 0.818 (9/11) | 0.750 (3/4) | 配列・元素組成は完全一致。プロトン化のみ 3 残基相違 |

**D03 が示した本命の所見.** 配列・モノマー数・元素組成・S-S がすべて一致した上で、
`residue_atom_counts_match_reference` だけが 3 残基を挙げた:
参照 `CYM109`/`CYM187`/`HIP270` に対し提出は `CYS112`/`CYS190`/`HIE273` (番号は参照側が
3 大きいだけで位置は同じ)。**参照は Zn 配位 Cys をチオラート (CYM) として、ヒスチジン 1 個を
プロトン化 (HIP) として流している**のに、MDClaw の prep は中性 CYS と HIE を作る。
残基名ではなく原子数で採点する設計にした狙いがそのまま当たった形で、原子数差は
-1 -1 +1 = -1、全原子数 4862 対 4861 とも一致する。ヒスチジンの互変異性 (HID/HIE) は
設計どおり不可視のままで、これは検出されていない。

**subspace は 3 タスクとも不合格。** D02 RMSIP 0.495 対 null 0.779±0.027 (z = -10.5)、
D03 0.704 対 0.748±0.029 (z = -1.5)。注目すべきは**帰無分布そのものが 0.75 前後と高い**
ことで、旧タスク (76 残基ユビキチン) では 0.588 だった。312 残基の球状蛋白質では ANM が
参照部分空間をよく再現してしまう。1 ns の窓 1 本では参照 1 µs の主成分に届かないという
可能性と、系が大きいほど閾値が厳しくなるという性質の両方が効いており、判定規則の再検討が要る。

**参照バンドルの再取得は完全再現。** 3 バンドルとも `task.json` に記録した sha256 と
一致した (例 MCV1900209 `reference.pdb` = 6ee5006...)。

## 2026-08-21 (3) — prep を参照データ由来のモノマー単位チェックに置き換え、問題固有軸を消した

**prep の 7-8 チェックを、全タスク共通の 11 チェックに置き換えた。** 期待値はすべて参照バンドルから
導出され、curator が書いた定数はゼロになった。**D02 の `truncated_sidechains_completed` と
D03 の `disulfide_bonds_formed` を削除**し、全タスクで走る一般形に吸収した。3つの `task.json` の
prep ブロックは**完全に同一**になり、`mddatabench/_prep_checks.py` が唯一の出所になった。

**モノマー単位にした。** 骨格の幾何（ペプチド C-N / ホスホジエステル O3'-P が 2.0 A 以内）で
両側を連結ポリマー鎖に分割し、**正規化配列**で対応付けてから、各対の内部で残基ごとの検査を回す。
**chain ID は使わない。** MDClaw 自身が `chain_identity_map.json` に
"PDB chain IDs are MD compatibility labels and may be reused" と書いており、実際 **D03 の
`system.topology.pdb` は chain A/B/C を持つのに参照は A だけ**。多量体（適格プールの `MULTIMERIC`
充填率 12.6%、memo 2026-08-20 の調査で 254 件）を足した瞬間に、残基リストの順次 zip は静かにずれる。

**protonation は残基名ではなく原子数で採点する。** 名前は規約である、というのが実測で出た:

| ファイル | Cys1/3/11/15 の残基名 |
|---|---|
| 参照 `reference.pdb` | CYX |
| 提出 `merged.pdb` | CYX |
| 提出 `system.topology.pdb` | **CYS** |

**同じ提出・同じ物理で、どちらのファイルを読むかによって判定が変わる。** GROMACS は
HISD/HISE/HISH、CHARMM は HSD/HSE/HSP を使うのでエンジンを跨ぐとさらに壊れる。原子数なら規約に
依存せず、必要な性質をちょうど満たす: HID↔HIE は同一分子式なので**区別しない**（互変異性は
エージェントの自由）、HIP/ASH/GLH は +1 H、LYN/CYM/CYX は −1 H で**すべて検出する**。

**`total_atom_tolerance: 2` を撤廃した。** この許容は互変異性のために必要だと思われていたが、
**D02 は参照と逆の互変異性体（参照 HID / 提出 HIE）を選んで 1014/1014 で厳密一致した**。
守っていたものは何も無く、代わりにイオン化エラーを最大2個通していた。イオン化エラーは
ちょうど水素1個である。

**ジスルフィドは CONECT から、常時、ゼロを含めて判定する。** 期待ペアは参照自身の CYX 残基と
座標から導出する（`expected_pairs` の手書きは廃止）。観測ペアは提出トポロジーの CONECT から取る。
**`system.system.xml` からは取れない** — あれは原子名を持たないコンパイル済みオブジェクトで、
しかも HBonds と剛体水が結合を拘束に変えた後は結合リストとしても使えない:
**D03 の System は `HarmonicBondForce` 177 本に対し constraints 21451**。ParmEd で prmtop や
GROMACS top に戻そうとすると、まさにこの理由で失敗する（`'NoneType' object has no attribute 'used'` /
`Cannot determine SETTLE geometry`）。psf だけは書けるが psf はパラメータを持たない。
**ペア集合そのものを比較するので、余計なジスルフィドも落ちる** — 旧チェックは期待ペアが近いかしか
見ていなかったので、D01/D02 で誤って S-S を作った提出を素通りさせていた。

**エネルギーは読まずに再計算する。** runner の `minimization_report.json` は
`simulation_time_ns` と同じ種類の申告なので、提出された `system.xml` を scorer が自分で評価する。
ゲートは2つ: 単点エネルギーが有限で粒子あたりの絶対値が上限以下（上限 1e6 kJ/mol/particle は
MDPrepBench の `_MAX_ABS_PREP_ENERGY_PER_PARTICLE_KJ_MOL` をそのまま借りた）、そして
**最小化でエネルギーが下がったこと**。

| task | built | minimized | max force |
|---|---|---|---|
| D01 | +505918 (+16.14/atom) | −532908 (**−17.00**/atom) | 29789 → 1640 |
| D02 | +400844 (+11.30/atom) | −600622 (**−16.93**/atom) | 32418 → 1557 |
| D03 | +331474 (+15.31/atom) | −366799 (**−16.94**/atom) | 20729 → 2366 |

**−16.93〜−17.00 kJ/mol/atom は帯にしたくなるほど揃っているが、単一力場・単一水モデルの n=3 なので
diagnostic に留めた。** 「未較正の閾値では採点しない」という不変条件に従う。max force も同様。

**`contract_atoms_resolvable` を prep から外した。** 新カテゴリ `precondition`（weight 0、
報告のみ、prep/md の合計に入らない）に移した。これは「参照の契約原子が提出トポロジーに載るか」で、
**scorer が2つの系を対応づけられるかを測っており、エージェントの調製能力ではない**。

**新チェックが落ちるべきときに落ちることを変異テストで確認した**（D01/D03 の合格提出を壊した）:

| 変異 | 落としたチェック |
|---|---|
| HIP 化（水素1個追加） | 残基原子数、全原子数 |
| 側鎖の切り詰め（Lys の重原子3個削除） | 残基原子数、元素、全原子数 |
| 骨格 N を O と書く（総数は不変） | **元素のみ** — 総数では捕まらない |
| ペプチド結合を1本切る | モノマー数、配列、残基原子数 |
| S-S の CONECT を削除 | ジスルフィド |
| 偽の SG-SG CONECT を追加 | ジスルフィド |

3行目が元素別チェックの存在理由で、4行目がモノマー分割の存在理由。

**副産物のバグ修正。** 残基の区切りを `(chain, resseq, resname)` の変化だけで判定していたため、
**同じラベルを持つ2つの成分が1残基に融合していた**。chain ID が再利用されうる以上これは実在する
危険なので、**原子名の重複でも区切る**ようにした（1残基に同じ原子名は現れない）。合成 PDB の
ユニットテストで検出した。

**Rg (`radius_of_gyration_is_physical`) を削除した。これは 2026-08-19 の
「Rg は subspace テストと冗長ではない」という記録を、測定を認めたうえで覆すものである。**
測定自体は再現した。D01 の軌跡を一様スケールすると:

| 倍率 | RMSIP | H0 棄却 | Rg (nm) |
|---|---|---|---|
| 0.80 | **0.700** | される | 0.943 |
| 1.00 | **0.700** | される | 1.178 |
| 1.30 | **0.700** | される | 1.532 |
| 1.50 | **0.700** | される | 1.768 |

RMSIP は正準相関の集合で、正準相関は部分空間の**方向**しか見ない。一様スケーリングは固有ベクトルの
向きを変えないので原理的に不変であり、2026-08-19 の「Rg だけがコンパクトさを縛る」は正しい。
それでも削除したのは、**Rg が MD の性質ではなく初期構造の性質だから**である:

| task | 参照 | 調製直後 | 最小化後 | 本番平均 | 本番 SD | 旧・帯 |
|---|---|---|---|---|---|---|
| D01 | 1.1833 | 1.1616 | 1.1589 | 1.1784 | **0.0073** | 1.1-1.3 |
| D02 | 1.1377 | 1.1031 | 1.1148 | 1.1224 | **0.0075** | 0.95-1.15 |
| D03 | 0.9070 | 0.8549 | 0.8589 | 0.8223 | **0.0124** | 0.7-1.1 |

**1 ns で Rg は動かない。** 軌跡内の変動 SD は 0.007-0.012 nm、帯の幅は 0.2-0.4 nm で 20-30 倍。
調製直後と本番平均の差も 1.4-3.8% にすぎない。md の判定として置くのは誤った帰属であり、
prep に移すという案も出たが最終的に削除とした。**結果として、一様スケーリングの誤り
（単位取り違えなど）を捕まえるチェックは現在ゼロである** — 溶媒クロックも `total_MSD/(6D)` の比なので
スケール不変。これは意図した上での穴として記録しておく。`rg_mean_nm` は diagnostics に残した。

**`topology_loads_and_is_parameterized` も precondition に移した。** 実体は
`XmlSerializer.deserialize` してから `getNumParticles() > 0` を見るだけで、**force field の中身は
一切見ていない**。しかも判定すべき失敗が全部クラッシュになっていた:

| 提出 | 旧 | 新 |
|---|---|---|
| ファイルが途中で切れている | **`OpenMMException` で採点全体が停止** | prep 7/11 = 0.636 |
| 中身が空の System | **`ValueError` で停止** | prep 7/11 = 0.636 |
| `NonbondedForce` が無い | **`StopIteration` で停止** | prep 9/11 = 0.818 |

deserialize と force 取得を保護し、失敗を記録された不合格に変えた。`system.xml` に依存する prep の
4項目（force 適用・正味電荷・単点エネルギー・最小化）が落ち、`system.xml` を使わない7項目
（組成6件 + 水モデル）は採点され続ける。3行目は System 自体は読めるので結合項だけでエネルギーが
有限に出る。**力場が全く当たっていない系が 0.818 を取る**が、physical_validity クランプは
**入れないと決めた**（2026-08-21 の判断）。

**採点を prep / md で分離し、`weight` を実際に読むようにした。** 従来 `weight` は契約にあるだけで
scorer が一度も参照していなかった。`category_score = Σ(w × passed) / Σ(w)` とし、採点対象は
すべて w=1.0、precondition は w=0.0。**0 重みが自動的にどのスコアからも除外される**ので、
precondition の特別扱いがコードから消えた。Rg にだけ付いていた `weight: 0.5` は、なぜ半分かの
測定がどこにも無い未較正の閾値だったので、Rg ごと消えた。現在の内訳は **prep 11 / md 4 /
precondition 2**。

**テストを 19 → 32 に増やした（うち 5 件が `slow`）。** `test_composition.py` は合成 PDB で動くので
バンドルも OpenMM も要らず、CI の `-m "not slow"` に乗る。`test_scoring_robustness.py` は OpenMM を
使うので `slow`。この suite は **数値的な中身に自動テストが1つも無く**、`pyproject.toml` に `slow`
マーカーの定義があるのに該当テストが存在しないという状態だった。今回それを実体化した。

**再採点は D01/D02/D03 とも prep 11/11 = 1.000、md 4/4 = 1.000。** precondition 2件も通過（非採点）。
負のコントロールは3タスクとも `all_correct: true`。`ruff` clean、`pytest -m "not slow"` 27 passed、
`pytest` 全体 32 passed。

**溶媒側は依然として何も採点しない。** MDDB 全 4554 件を走査した結果、`SOL`/`SOLVATS`/`SOLVRES` は
**充填率 0.0%**。イオン個数と箱サイズが揃うのは適格 1940 件のうち **47 件**で、うち 46 件は
`COUNION = 1` の中和用対イオン1個。**本物の塩から濃度が導ける適格エントリは 1 件だけ**
（`seq014-2`, 0.155 M）。塩はあるが箱が無い適格エントリが 32 件（`bigna`/`ebrains`）あるが、
**箱が無ければ個数は物理量ではない**。仮に濃度を指定できても検証精度が足りない: packmol-memgen に
0.15 M を要求した3系は 0.146 / 0.118 / 0.130 M になった（中和対イオンが先に入る D02 が −21%、
D03 は**イオン1個が 0.008 M** に相当する量子化）。**塩濃度は採点しない。**

`BOXTYPE` は適格プールの 89.6% で埋まっており、**参照3件はすべて `Octahedral`、提出は cubic**。
照合可能だが採点しない — 周期像との距離が足りていれば箱形状は物理に影響せず、`FF: Parm99` と
同じ「記録するが不問」の扱いにする。

---

## 2026-08-21 (2) — dt は DCD ヘッダから取れる。同日 (1) の「1 ps 出力が事実上の提出要件」を撤回する

**同日のエントリ (1) が「クロックの単位はフレームで、1 ps 出力が事実上の提出要件」と結論したのを
撤回する。** 正しい修正は出力間隔を提出側に強いることではなく、**scorer が dt を DCD ヘッダから読むこと**。

**DCD は時刻情報を持っている。** 捨てているのは mdtraj であってフォーマットではない。
CHARMM 形式のヘッダは `DELTA` (積分ステップ、AKMA 単位、float32) と `NSAVC` (保存間隔ステップ数)
を持ち、積がフレーム間隔になる。今回の提出物を実測:

| file | DELTA | NSAVC | NSTEP | 間隔 |
|---|---|---|---|---|
| d01/prod_001 | 4.000 fs | 500 | 250000 | 2.0000 ps |
| d01/prod_002 | 4.000 fs | 250 | 250000 | 1.0000 ps |

**(1) で「メタデータだから申告の検証に使えない」と書いたのは誤り。** ヘッダを書くのは OpenMM で
あってエージェントではなく、想定攻撃は「走らせた量より多く申告する」であって「バイナリヘッダの偽造」
ではない。しかも**打ち切り攻撃はヘッダを正直に保ったままフレーム数だけ失う**ので、ヘッダ由来 dt は
打ち切りを落とす側に働く。(1) が代案として挙げた「外部の水の自己拡散係数を基準にする」案は、
存在しない脅威モデルへの過剰設計であり、水モデルごとの帯較正という新しい未較正閾値を持ち込むので
**採らない**。

**修正内容。** `execution.dcd_frame_interval_ps()` を足し、`elapsed_time_ps(..., dt_ps=)` で受ける。
`scoring` と `controls` の両方が渡す。ヘッダが読めない軌跡は **FAIL** にした
(黙って `traj.time` に落ちると単位が壊れたまま通ってしまうため)。

同一軌跡での前後比較 (D01, 主張 1000 ps):

| 提出 | フレーム | 間隔 | 旧 (`traj.time`) | 新 (ヘッダ) | 報告される D |
|---|---|---|---|---|---|
| prod_001 | 500 | 2 ps | 489 ps (0.49) **FAIL** | **977 ps (0.98) PASS** | 7.33e-5 -> 3.66e-5 |
| prod_002 | 1000 | 1 ps | 989 ps (0.99) PASS | 989 ps (0.99) PASS | 3.72e-5 -> 3.72e-5 |

**D が 7.33e-5 から 3.66e-5 に下がって prod_002 の 3.72e-5 と一致するのが、単位が直った証拠。**
同じ水が出力間隔で 2 倍拡散するはずがない。

**負のコントロールは D01/D02/D03 とも `all_correct: true`。** 検出力は落ちていない。
D01 の `truncated_100ps` は RMSIP 0.644 で構造のみ帰無 (max 0.588) を**超えており h0 は棄却される**
—— これを落としているのはクロックだけで、両方のチェックを残す理由がここでも再現した。

| task | real_full | trunc_100ps | trunc_10ps | anm | noise | duplicated |
|---|---|---|---|---|---|---|
| D01 | pass | fail (h0 通過, clock で落ちる) | fail | fail | fail | fail |
| D02 | pass | fail | fail | fail | fail | fail |
| D03 | pass | fail | fail | fail | fail | fail |

**再採点は 12/12, 13/13, 13/13 で変わらず**、クロックは 989 / 981 / 1017 ps。
`ruff` clean、`pytest -m "not slow"` 19 passed。

---

## 2026-08-21 — GB200 で D01-D03 を通し、溶媒クロックが **フレーム番号**を測っていることを見つけた

**MDClaw 0.6.8 / 1x NVIDIA GB200 (aarch64, CUDA 13.0) で D01-D03 を独立に解いた。**
ff14SB + TIP3P、cubic 15 A バッファ、0.15 M NaCl、HMR 4 fs、NVT 100 ps + NPT 200 ps、
1 ns NPT production。参照バンドルは solve 中一度も solver ワークスペースに置いていない。

| task | 系原子数 | prep | md | RMSIP | 構造のみ帰無 (max) | 余裕 | クロック | Rg (nm) |
|---|---|---|---|---|---|---|---|---|
| D01 1UBQ | 31355 | 7/7 | 5/5 | 0.700 | 0.588 | +0.112 | 989 / 1000 ps | 1.178 |
| D02 1CSP | 35469 | 8/8 | 5/5 | 0.707 | 0.637 | +0.070 | 981 / 1000 ps | 1.122 |
| D03 1EDN | 21656 | 8/8 | 5/5 | 0.779 | 0.766 | +0.013 | 1017 / 1000 ps | 0.822 |

**組成は 3 つとも無指示で参照と完全一致した。** D01 1231/602、D02 1014/521 (切り詰められた
4 側鎖を自動補完)、D03 328/171 (SSBOND 2 本を `pdb_ssbond+distance` で自動形成)。
2026-08-19 の検証を別ハードウェア・別 MDClaw バージョンで再現した形になる。

**RMSIP は 2026-08-19 の参照解 (0.717 / 0.703 / 0.828) と 0.01-0.05 しか違わない。**
D01 のレプリカ間 SD 0.010 に照らすと D01/D02 は同一、D03 の -0.049 はやや大きいが、
**D03 の余裕 +0.013 は 3 つの中で桁違いに狭い**。3M=189 の系で 1 ns 一本という設計上、
乱数シード次第で構造のみ帰無 (max 0.766) を割り込みうる位置にある。D03 は
レプリカを重ねるか production を伸ばさないと、pass/fail がシード依存になる。

**`elapsed_simulated_time@1` は ps ではなくフレーム番号を数えている。**
`scoring.py` は `md.load(traj.dcd, top=topology.pdb)` で読み、`execution.py` は
`dt = traj.time[1] - traj.time[0]` を使う。ところが **mdtraj の DCD リーダは時刻情報を持たず、
`time = arange(n_frames)` を返す**ので `dt` は出力間隔によらず常に 1。
`elapsed_ps = total_MSD / (6 D)`、`D` は `MSD` 対 `lag*dt` の傾き/6 なので、
測定値は `真の経過時間 x (1 ps / 実フレーム間隔)` にスケールする。

測定 (D01, 同一の 1 ns 軌跡を 2 通りに出力):

| 出力間隔 | フレーム数 | クロック | 比 | 報告される D |
|---|---|---|---|---|
| 2 ps | 500 | 489 ps | 0.49 -> **FAIL** | 7.33e-5 cm2/s |
| 1 ps | 1000 | 989 ps | 0.99 -> PASS | 3.72e-5 cm2/s |

**同じ物理、同じ長さ、出力間隔だけが違う。** 2 ps 出力は閾値 0.5 を 0.01 で割って落ちる。
報告される D が 2 倍に出ているのが症状で、これは D が実時間ではなくフレーム番号あたりで
測られているため。MDClaw の `run_production` の既定は `--output-frequency-ps 10.0` なので、
**既定のまま 1 ns を回した提出は 100 / 1000 ps と読まれて必ず落ちる**。
2026-08-19 の参照解が 1000/1000 ps を得ていたのは 1 ps 出力だったからで、
その依存関係はどこにも書かれていない。

閾値は正しく、破れているのは単位。直し方は `dt` を軌跡メタデータに頼らず与えること —
prod ノードの `metadata.output_frequency_ps` を読むのが最短で、`claimed / (n_frames-1)`
を使うと虚偽申告を検証できなくなるので不可。それまでは **1 ps 出力が事実上の提出要件**。

---

## 2026-08-20 — MDDB の系統調査と D03 (エンドセリン-1) の導入

**MDPrepBench と同じ種類の system variety を MDDB で埋められるか調べた。** 適格プールは
**1934 / 4554** (CC + Classical MD + 解析 5 種 + PDBID あり)。

**メタデータだけでは選べない、というのが最大の教訓。** `OTHRATS>0` かつ `PTM=Acetylation` は
金属タンパク質に見えるが実体は **ACE キャップ**だった。1CCR (シトクロム c) も 1JEB (ヘモグロビン) も
**ヘムが剥がされている**。2CBA に Zn が無かったのと同じで、**MoDEL は補因子と金属を全部落としている**。
使えるのは `RSNAME` (残基名リスト) で、そこから拾った候補は**全て structure.pdb を取得して実物確認した**。

| 軸 | 適格件数 | 代表 | 確認した非標準残基 |
|---|---|---|---|
| ジスルフィド | 677 | `A00EC` 1EDN | CYX x4 |
| 末端キャップ | 144 | `A007Z` 1CCR | ACE |
| セレノメチオニン | 31 | `A015F` 1WHZ | MSE x3 |
| **亜鉛 (金属保持)** | 139 | `MCV1900209` PLpro 6W9C | **ZN + CYM x3** |
| **リガンド結合** | 78 | `MCV1900211` PLpro + 3k | ZN + CYM + **S88** |
| 糖鎖 | 79 | `MCV1900112` 6VW1 | **NAG x5** + ZN + CYX + ACE/NMA |
| DNA + 対イオン | 126 | `A01MQ` 1ICK | **Na+ x32, Cl- x22** |
| RNA | 10 | `A01AU` 1Q9A | — |
| タンパク質-DNA + Mg | 26 | `A01FH` 1VTN | **MG** |
| 多量体 | 254 | `A007P` 1CDL | — |

**金属もリガンドも糖鎖も cv19 コレクションには残っている。** PLpro は apo (`MCV1900209`) と
リガンド結合 (`MCV1900211`) が揃っていて**比較ペアにもなる**。DNA の `FF-DNA-2023` シリーズは
同じ PDB を {OL15, OL21, ParmBSC1, Tumuc1} x {OPC, TIP3P} の 8 通りで回した系統比較で、
**イオンごと寄託されている** (MoDEL は水もイオンも剥がすので照合できなかった)。
FOXO3/FOXA3 は rep0-rep5 の**レプリカ付き**で、参照側にレプリカがあるのはここだけ。

**埋まらない軸は 4 つ**: 膜系 (CC の実バイアレイヤは SARS-CoV-2 ウイルス膜 10 件のみ)、陰溶媒、
変異体、リン酸化 (PTM は Acetylation / Glycosilation のみ)。

**D03 = `A00EC` (1EDN, エンドセリン-1) を導入した。** 21 残基 / 328 原子 / 重原子 171。
RCSB の SSBOND は Cys1-Cys15 と Cys3-Cys11、参照では 4 つとも CYX。
**328 原子 (SS 2 本) 対 332 原子 (還元型) という等式を参照自身が与える**ので、D02 の 505+16=521 と
同じく正解をキュレータが決めなくてよい。SG-SG 距離で帰属する専用チェックも足した。

**MDClaw は 13/13 (prep 8/8, md 5/5)。** ジスルフィドを**無指示で 2 本とも形成**した
(`disulfide_bonds.json` に `pdb_ssbond+distance`, Cys1-Cys15 が 2.04 Å, confidence high)。
RMSIP 0.828。

**小さい系ほど余裕が狭い。** 3M=189 なのでランダム帰無だけで sqrt(10/189)=0.230、
構造のみ帰無は 0.602 +/- 0.067 (最大 0.766)。余裕は **+0.062** で D01 の +0.129 より狭い。
100 ps 切り詰めは 0.807 で構造のみ帰無を超えてしまい、**時計だけが捕まえる** (D01 と同じ)。

**GPU 競合で production が遅延した。** GPU 3 が他ジョブで 99% 占有されており、10 分の
ツール制限でスクリプトごと落ちて `prod_001` が `running` のまま孤児化した。空いている GPU 5 で
`prod_002` を作り直して完走。

**孤児ノードが scorer/controls のバグを露出させた。** `run_negative_controls` が
`prod_*/artifacts/*.dcd` を glob して先頭を取っていたため孤児の `prod_001` を掴み、
scorer (最新 completed = `prod_002`) と**別の軌道を採点していた** (0.818 対 0.828)。
両方 `find_node` を共有するよう修正。**2 つのツールの数値を突き合わせる習慣が、これで 2 件目のバグを捕まえた**
(1 件目は原子インデックスをファイル行番号で数えていた件)。

---

## 2026-08-20 — MDDataBench を別リポジトリに切り出した

MDPrepBench / MDStudyBench と同じ形で 独立したリポジトリに切り出した。
mdclaw 側の `benchmarks/mddatabench/` と `docs/research/db_derived_benchmark_validation.md` は削除済み
(どちらも git 未追跡だったので履歴操作は不要)。**本エントリより前の 8/18-8/19 の各エントリが参照している
`docs/research/db_derived_benchmark_validation.md` は、いまは `MDDataBench/docs/validation-design.md` にある。**
過去エントリは規約どおり書き換えていないので、参照を辿るときはここを見ること。

**構成は MDPrepBench に合わせた。** hatchling + `mddatabench` コンソールスクリプト、
`mddatabench.TOOLS` を signature 由来のフラグでディスパッチする `__main__.py`、
`benchmarks/mddatabench/tasks/`、`tests/`、`.github/workflows/ci.yml`、MIT LICENSE、
CLAUDE.md と AGENTS.md の同一二枚。スクリプト群はパッケージモジュールに移した
(`subspace_test.py` -> `subspace.py`、`execution_check.py` -> `execution.py`、
`fetch_reference.py` -> `reference.py`、`score_submission.py` -> `scoring.py`、
`negative_controls.py` -> `controls.py`)。argparse の `main()` は全部ライブラリ関数に直して
`cli.py` の TOOLS から呼ぶ形にした。

**CLI は 4 つ**: `list_benchmark_tasks` / `fetch_benchmark_reference` /
`score_benchmark_submission` / `run_benchmark_negative_controls`。

**動作確認**: ruff clean、fast テスト 14 本 passed (0.62 s)、
`mddatabench score_benchmark_submission` で D01 が **prep 7/7 md 5/5 = 12/12 を 6.2 秒**。

**テストに入れた不変条件**: ライセンスが CC 系であること、bundle の SHA-256 が 3 ファイル分揃っていること、
全チェックが `prep`/`md` のどちらかに分類され `check_type` が `@1` 付きであること、md 側が
構造のみ帰無検定と時計の両方を持つこと、そして **prompt が accession / MDDB / MoDEL / DOI を漏らさず、
かつ PDB ID と採点対象の条件 (水モデル・温度・アンサンブル) は述べていること、`rmsip` を含まないこと**。
最後のはプロンプト最小化とリーク防止を機械的に守らせるためのもの。

初期コミット 29 ファイル / 328 KB、データは 0 バイト。GitHub remote は未作成 (ユーザ判断待ち)。

---

## 2026-08-19 — 検定を ANM 帰無に一本化、Rg の役割が判明、3 レプリカを測定、SIF の BLAS バグを発見

**検定を 1 本に絞った (ユーザ指示「H0 か ANM かに絞ったほうがいい」).** ANM 帰無 (cutoff 7.0-20.0 A の 27 点、
平均 0.517 SD 0.048 最大 0.588) はランダム帰無を包含する: 0.13 のものは 0.59 を超えられない。
実測 z は 本物の 1 ns +4.37 / 100 ps +2.26 / 10 ps -2.00 / ANM ensemble -0.05 (帰無のど真ん中) /
等方ノイズ -8.00。ランダム帰無はゲートから外し報告用の文脈に降格。負の対照 5 本すべて失敗、実 run のみ通過。

**Rg は冗長ではなかった。** 「Rg は意味なくない?」を実測で確かめたところ逆の結論になった。
**RMSIP はスケール不変**なので、軌道を一様に 1.3 倍しても RMSIP は 0.729 のまま変わらず (Rg は 1.14 -> 1.48)。
0.8 倍でも同様。進行性膨潤 (Rg 1.82) でも RMSIP は 0.711 でまだ通る。**Rg が振幅・コンパクトさを拘束する
唯一のチェック**であり、単位ミスや変性を捕まえる役割を独占している。バンドが緩い (結晶構造が満たす) のは事実だが
冗長とは別問題。

**3 レプリカの効果を実測 (seed 20260820/21 で 2 本追加).** 単独 0.729/0.743/0.717 -> 平均 0.730 **SD 0.010**、
レプリカ間 0.780/0.851/0.770 平均 0.801、3 本プール 0.764 (+0.034)。帰無最大からの余裕は +0.142 -> +0.176。
敵対側 (ANM ensemble 3 本) もプールで +0.022 稼ぐので、**利得は実在するが劇的ではない**。
本当に新しいのは**参照を使わないレプリカ間一致**で、これは `execution_validity` 軸に入る。
実務的含意: **SD 0.010 なのでエージェント間の 0.03 未満の差はノイズ。** レプリカ無しではこれが分からない。

**SIF の OpenBLAS がスレッド過剰生成で崩壊していた (プロジェクト全体に効く).**
scorer が 1 タスク 10 分超かかるので profile したところ `anm_null_distribution` が 528 秒。
Hessian 構築をベクトル化しても改善せず (結果は RMSIP=1.000000 で完全一致)、犯人は `np.linalg.eigh` だった。

| 環境 | `eigh(684x684)` |
|---|---|
| SIF、スレッド env 無し | **16.34 s** |
| SIF、`OMP_NUM_THREADS=1` | 0.12 s |
| SIF、`OMP_NUM_THREADS=8` | 0.07 s |
| ホスト python3 | 0.59 s |

`matmul` は 3.7 倍差なので LAPACK 固有。SIF の numpy は scipy-openblas を
`DYNAMIC_ARCH NO_AFFINITY MAX_THREADS=64` で積んでおり、32 コア機で上限未設定だと小問題が崩壊する。
**SIF 内で numpy を回すときは常に `OMP_NUM_THREADS` を渡すこと。**
`scripts/_threads.py` で `os.environ.setdefault` により numpy import 前に防御 (1 タスク 10 分超 -> 7.4 秒)。
恒久対応はコンテナか `bin/mdclaw` 側だが未着手。memory にも記録。

**最終スコア**: D01 prep 7/7 md 5/5 (12/12)、D02 prep 8/8 md 5/5 (13/13)、両タスク合計 13.5 秒。

---

## 2026-08-19 — MDDataBench の採点は甘すぎた。敵対的ベースラインで穴を 2 つ実測し、塞いだ

**「score が甘すぎないか」を議論でなく実測で確かめた結果、甘かった。** 落ちるべき提出を作って走らせたところ、
ランダム部分空間帰無だけでは 3 本が通ってしまった (D01 参照に対して):

| ベースライン | RMSIP | z | 当時の判定 |
|---|---|---|---|
| ANM 低振動モードからのサンプル (**MD ゼロ**) | 0.515 | 46 | **通過** |
| 本物の MD を 100 ps に切り詰め | 0.627 | 60 | **通過** |
| 本物の MD を 10 ps に切り詰め | 0.420 | 36 | **通過** |
| 結晶構造 + 等方ノイズ | 0.130 | -0.5 | 正しく失敗 |
| 最小化構造の複製 | 0.135 | 1.7 | 正しく失敗 |

つまり**「正しい分子か」は証明できていたが「実際に走らせたか」は証明できていなかった**。
`production_ran_for_one_nanosecond` がノード自身のメタデータを読むだけだったのも同根。

**修正 1: 構造のみの床 (ANM) を追加。** 結晶構造から組んだ弾性ネットワークが RMSIP 0.57 に達するので、
それを margin 0.05 付きで超えることを要求する。床はカットオフ最大化で取る (カットオフは攻撃者の自由変数)。

**修正 2: 経過時間を物理で検証。** 拡散係数は**強度量**で使えない (同じ軌道の 1 ns と 100 ps でどちらも
3.7e-5 cm^2/s)。**連続 unwrap した溶媒の総変位は示量量**で、999 ps から 989 ps、99 ps から 98 ps、
9 ps から 15 ps を復元した。溶媒が無い提出は計測不能で即失敗 = MD ゼロ提出に対する正しい判定。

修正後、5 本すべてが失敗し実 run だけが通る。**D01 の 100 ps は ANM 床を 0.005 差で超えてしまい、
時間検証だけが捕まえた** ので 2 つとも要る。恒久回帰として `scripts/negative_controls.py` を追加。

**採点を prep と md に分割 (ユーザ指示)。** 単一の数では「組み立てで落ちた」のか「シミュレーションで
落ちた」のかが言えない。ANM 提出と 10 ps 提出はどちらも **prep 満点・md 失敗**になり、帰属が機能する。
D01 prep 7/7 md 6/6、D02 prep 8/8 md 6/6。

**副産物のバグ 1 件.** `negative_controls.py` 初版が原子インデックスをファイル行番号で数えており
(トポロジにはヘッダ行がある)、real_full_run が 0.688 と出て scorer の 0.729 と食い違った。修正後一致。
**scorer と回帰ハーネスで同じ値が出ることを毎回突き合わせる**のが早期発見に効いた。

---

## 2026-08-19 — scorer 修正、D02 追加、プロンプト最小化

**scorer の偽 FAIL 2 件を修正。** `benchmarks/mddatabench/scripts/score_submission.py` として
実装し直した。ハードコードした `True` を廃し、全項目を artifact から再計算する。正しい所在は
`amber_metadata.json :: parameters.water_model` (+ `forcefield_provenance.openmm_xml`) と
prod ノードの `metadata.system_signature.ensemble`。**バロスタットは実行時に付与されるので
topo ノードの system.xml には無い。** 契約原子は生インデックスではなく (残基番号, 原子名) で対応付ける
(提出側トポロジは溶媒を含む)。D01 で 11/11 を再現。

**D02 を追加: MDDB `A00AJ` (MoDEL 1CSP、枯草菌 major cold-shock protein CspB)。**
MDPrepBench との交差を機械的に取った結果 (MDPrepBench 30 PDB 中、CC + Classical MD + 解析5種を
満たすのは 1UBQ / 1CSP / 2CBA / 1BNA)。**2CBA は見送った** — MoDEL の寄託に Zn が入っておらず
(HETATM ゼロ、apo)、触媒金属を捨てることを報酬にしてしまう。MDPrepBench P26 の趣旨と正反対になる。

D02 が D01 に足す能力は**側鎖補完**と**非ゼロ溶質電荷**。PDB 1CSP は Glu 3/21/36/66 の側鎖先端を
欠いており重原子 505、MDDB 参照は 521。**505 + 16 = 521 という等式を参照自身が与える**ので、
正解をキュレータが決めなくてよい。参照スケールは 201 原子 (67×3)、1 ns 窓どうし 0.687 ± 0.035、
帰無 sqrt(10/603)=0.129。

**プロンプトを最小化した (ユーザ指示)。** scorer が両側のサブスペースを自分で計算するので、
**エージェントに解析させる必要がそもそも無い**。解析契約・報告項目・鎖選択・互変異性体・箱形状・
側鎖補完の指示をすべて削除し、残したのは「PDB ID / TIP3P / 中性化 / 300 K / NPT / 1 ns 以上」だけ。
参照バンドルは**ソルバのワークスペースに一切置かない** (採点時に評価器が取得する) ので、
参照が漏れる経路が消えた。

**簡素プロンプトが解けることを実測で確認。** プロトネーションの指示ゼロで MDClaw は
1UBQ -> 602/1231、1CSP -> 521/1014 と参照組成に厳密一致し、1CSP の Glu 4 残基を無指示で補完した。
2 つの run は参照と**逆の**互変異性体を選んだが (1UBQ で HID、参照は HIE / 1CSP で HIE、参照は HID)、
重原子数は互変異性体に依らないので設計どおり通る。総原子数には ±2 の許容を入れた。

**採点結果**: D01 11/11 (RMSIP 0.729, z 72.4)、D02 12/12 (RMSIP 0.703, z 64.0)。
どちらも方向は復元、振幅は 2-6 倍小さいという同じ姿。ruff clean、リポジトリ内のデータは 0 バイト。

---

## 2026-08-19 — D01 を MDClaw で実際に解いて 11/11。試走が scorer の欠陥を 2 件出した

同日前エントリで作った MDDataBench D01 を、MDClaw 0.6.6 で最初から最後まで解いて採点した。
A6000 1 枚、1UBQ chain A -> ff14SB + TIP3P、cubic 15 Å、31355 原子、HMR 4 fs、
NVT 100 ps + NPT 200 ps、**1 ns NPT production が 2 分 29 秒**。

**結果 11/11 PASS.** 核となる検定は RMSIP=0.729、z=72.4、p<5e-5 で H0 棄却。
正準相関 10 本すべてが帰無 99 パーセンタイル超。Rg=1.1777 nm（参照 10 ns 平均 1.1807、
差 0.0030 は 1 ns 窓の SD 0.0102 の 1/3）。prep 出力は重原子 602 / 全 1231 / 76 残基 / HIE で
参照と完全一致した。

**設計の予測が当たった。** 固有値比 (own/ref) は [0.60, 0.35, 0.18, 0.18, 0.29, ...] で、
**方向は復元できるが振幅は 2-6 倍小さい**。τ(PC1)=1236 ps から予測したとおり 1 ns では
遅いモードの分散が出ない。RMSIP 0.729 は ANM 床 (0.47-0.62) を超え、参照自身の 1 ns 窓間
自己一致 0.760 ± 0.053 の 0.6σ 以内。**別力場 (ff14SB vs Parm99) の独立な 1 ns が、
参照自身の 1 ns 再現性と同じ水準に着地した。** 「H0 棄却は採点、定量一致は採点しない」
という設計判断が実測で正当化された。

**試走で出た scorer の欠陥 2 件（いずれも偽 FAIL）.**

1. water model を `amber_metadata.json` 直下で探したが実際は `parameters.water_model`
   (+ `forcefield_provenance.openmm_xml` に `amber/tip3p_standard.xml`)。
2. barostat を topo ノードの `system.xml` で探したが、**バロスタットは実行時に付与される**ので
   そこには無い。ensemble は prod ノードの `metadata.system_signature.ensemble` を読む。

さらに、参照の 228 契約原子は**生の原子インデックスではなく (残基番号, 原子名) で対応付ける**必要がある
（提出側トポロジは溶媒を含むのでインデックスが一致しない）。これらを `task.json` の
`scorer_field_map` に記録した。**artifact-as-truth を掲げても、artifact のどこに何があるかを
実走で確定しないと scorer は嘘をつく。**

`benchmarks/mddatabench/scripts/evaluate_submission.py` を追加。ruff clean。

---

## 2026-08-19 — MDDataBench D01 を作成: RMSIP による「無関係」帰無仮説の検定

`benchmarks/mddatabench/` を新設し、最初のタスク D01 (1 ns MD + 本質サブスペース一致) を実装・検証した。
参照は MDDB `A0142` (MoDEL 1UBQ、CC-BY 4.0、Amber Parm99 / TIP3P / 300 K / NPT / 10 ns)。

**採点の核: H0 =「2 つの本質サブスペースは無関係」を RMSIP で棄却する検定。**
ランダム直交フレームの Monte Carlo で帰無分布を作る (M=20000 で平均 0.1206 / SD 0.0083、
解析値 sqrt(D/3M)=0.1209 と一致)。**力場校正が不要**なので、rev.2 の「未校正の量に閾値を置かない」
規律を破らずに MD 部分を採点できる。実測 (D=10, 3M=684):

| 比較 | RMSIP | z | 棄却 |
|---|---|---|---|
| ランダム (負の対照) | 0.121 | 0.0 | **no** |
| ANM (構造のみ, 10 A) | 0.617 | 59.5 | yes |
| 座標系ズレ (大域回転) | 0.652 | 64.2 | yes |
| 1 ns 窓 vs 1 ns 窓 | 0.760 ± 0.053 | 81.8 | yes |
| 1 ns 窓 vs 全 10 ns | 0.794 ± 0.029 | 84.7 | yes |
| 10 ns から 500 フレーム | 0.969 | - | yes |

**この検定は妥当性ゲートであって品質スコアではない。** 構造だけから作った ANM も H0 を棄却するため、
「正しい分子を正しい契約で解析したか」は保証するが「サンプリングが収束したか」は保証しない。

**1 ns では上位モードを定量比較できないことが判明。** 参照の積分自己相関は PC1 1236 ps / PC2 1081 ps /
PC4 1660 ps で、**1 ns 中の独立標本は PC1 で 0.8 本**。10 ns の参照でも 8 本。Marchenko-Pastur は
q_eff = N/T_eff が 1 ns で 188、10 ns でも 38 となり適用不能 (PRL 103, 268101 (2009) の手法は
MP 上端ではなくバルクの準位間隔統計)。よって連続値 RMSIP は診断のみとし、校正データとして蓄積する。

**解析契約が必須であることの数値的裏付け.** MDDB は PCA の固有値と射影を配信するが**固有ベクトルは配信しない**
ため、scorer 側で再計算が必須。契約 `pca_backbone_subspace@1` (主鎖 N/CA/C 228 原子、参照構造への Kabsch
フィット + running mean 3 反復、D=10、Å) で公開固有値を -4.8% 〜 +3.4% で再現。摂動の効き方は
大域回転 -0.175 > 原子順序 -0.018 > 平行移動 0。なお Rg では標準原子量の質量加重が公開値と
+0.0024 nm 系統的にずれ、これは 1 ns 窓の SD 0.0102 nm の 24% に相当した。

**データは非同梱.** `scripts/fetch_reference.py` が MDDB から取得し provenance と SHA-256 を書く。
再取得でバイト一致を確認済み。`.gitignore` で取得物のコミットを禁止。solve 時は `mddbr.eu` を遮断、
RCSB は許可。プロンプトに accession を出さない。

**Rg を主観測量にする案は棄却した.** 正しく作れば誰でも 1.18 nm になり識別力がない。RMSIP は
0.12 (偶然) - 0.79 (1 ns 自己一致) - 1.0 と広いレンジを持つ。ruff clean、取得から検定まで通し検証済み。

---

## 2026-08-18 — 訂正: DB 由来ベンチ設計を MDDB 単独に変更、逐次ゲートと σ_FF 加算式を撤回

**同日の前エントリ「公開 MD DB (GPCRmd / MDDB) 由来ベンチの実測と検証層の設計」を訂正する。**
実測値そのものは概ね維持されるが、**供給源の選択と検証設計の中核 3 点が誤っていた**。
改訂版は `docs/research/db_derived_benchmark_validation.md` (rev.2)。

**方針変更 (ユーザ判断).** GPCRmd は RIKEN でのライセンス上の扱いが難しいため供給源から外した。**MDDB 単独**にする。

**独立レビューで判明した設計上の誤り 4 点** (cursor advisor pane, Opus 4.8, 読み取り専用で実施):

1. **`observable_fidelity` を「唯一の新規軸」としたのは誤り。** 軌道から観測量を再計算して
   自己申告値と突き合わせる primitive は既存: `MDPrepBench/mdprepbench/scoring.py:882-947` と
   `:1076-1124` (`_check_observable_recompute_consistency`)、
   `MDStudyBench/mdstudybench/scoring.py:1033-1075` (`direction_grounding`) と
   `:1078-1126` (`observable_recompute_consistency`)。新規なのは
   **DB の固定参照軌道をエージェント入力にする task mode と DB provenance 付き check contract** だけ。
2. **「軸 k は k-1 が通ったときのみ評価」という逐次ゲートは自己矛盾。** 物理妥当性に落ちた提出でも
   組成・自己申告値・主張整合性の診断は独立に可能で、それを捨てるのは掲げた目的 (原因帰属) を捨てること。
   **全軸を独立に評価し、`passed` / `failed` / `not_evaluable` / `not_attempted` を区別し、
   最終合否だけを非補償ゲートにする**に変更。
3. **`δ = k·sqrt(σ_rep² + σ_FF²)` を撤回。** この式は力場差が平均ゼロのランダム変動で、
   単一 σ_FF が系・観測量をまたいで転用可能であることを仮定する。実際は系依存の系統バイアスなので
   単一分散に畳めない。同様に「Δ なら力場オフセットが相殺される」も一般には成立しない
   (相殺は bias が両条件で同じ場合のみ)。
4. **旧 L4 を 2 軸に分割。** `observable_recompute` (selection/alignment/PBC/実装版の問題) と
   `ensemble_reproduction` (sampling/力場/初期条件/protocol の問題) は失敗原因が異なる。
   後者は matched-protocol / diagnostic-only / calibrated の 3 モードに分け、
   matched-protocol なら σ_FF は不要 (「σ_FF が測れなければ絶対値タスクを一切作らない」は強すぎた)。

**新規に見つかった scorer バグ.** `DeterministicCheck.capability` の明示 override
(`MDPrepBench/mdprepbench/models.py:291-306`) が capability profile 集計で無視される。
`CheckResult` (`models.py:1079-1085`) が capability を保持せず、`scoring.py:3662-3685` が常に
`DEFAULT_CHECK_CAPABILITY` を引くため。現行 P01-P40 は override 未使用なので今の得点には影響しないが、
自動生成タスクが capability を明示し始めると公開契約と実際の集計が食い違う。**タスク量産前に修正が必要。**

**MDDB 単独 + CC-BY 限定にした結果の実測 (定義つき).**

- ライセンス: CC-BY 4.0 が 4511、CC0 19、**CC 系でないものが 24** (AFL 3.0 が 9、Apache 2.0 が 5、
  MIT 4、LGPL 2、記載なし 4)。タスク生成はこの 24 件を除外する。
- **膜系の軸は実質失われた。** 実バイアレイヤ (`LIPIRES>=100`) は 30 件だが **20 件が非 CC**
  (CLC / Nav 5WEO / TARP / HCN / CTL1、および唯一の GPCR `OTRMG` `OTRMGb` も非 CC)。
  CC-BY の膜系は 10 件で全て SARS-CoV-2 のウイルス膜。
  **P18 膜系が全モデル失敗する既知の弱点を DB 由来タスクで補強する道は閉じた。** 膜系は手書きで扱う。
- **力場感度の測定源は MDDB 内に存在する。** 同一 PDB が複数力場で登録された群が **11、全て CC-BY**。
  `6VXX` が 6 力場、`6M0J` が 5、`1FZX` / `1ICK` / `1SK5` / `3GGI` が 4
  (OL15 / OL21 / ParmBSC1 / Tumuc1、各 2 entry) で、核酸 4 系は力場比較目的の study に見える。
  ただし同一 PDB でもリガンドパラメータ・プロトネーション・欠損ループ・イオン強度・ensemble・
  engine・軌道長・初期構造が交絡しうるため、**matched を確認するまで力場感度に帰属しない**。

**計数の定義の問題.** 前エントリの「脂質を含む 43 件」は定義なしで誤読を招く。
`LIPIRES>0` は 43、`LIPIRES>=100` は 30、`MEMBRANES` 非空は 10 で、どれを指すかで意味が変わる。
また `totalFrames` 296128391 は summary エンドポイントの集計値で、project 一覧の総和 287267536 とは
別の量である (3% 差)。**以後、計数は必ず定義とともに記す。**

**次の 4 手 (いずれも MD 不要).** (1) 核酸 4 系 16 entry の matched-protocol 検証、
(2) 解析契約レジストリの最小版 (観測量 1 つで MDDB 前計算値と自前再計算値のずれを測る)、
(3) `observable_recompute` タスク 10 本、(4) 上記 scorer バグの修正と回帰テスト。

---

## 2026-08-18 — 公開 MD DB (GPCRmd / MDDB) 由来ベンチの実測と検証層の設計

MDPrepBench / MDStudyBench を公開 MD データベースから自動生成できるかの調査。
設計は `docs/research/db_derived_benchmark_validation.md` に分離。ここには実測値と判断だけ残す。

**実測 (API / 公開ページを直接叩いた).**

- MDDB (`https://mmb.mddbr.eu/api/rest/v1/`, 無認証): 4554 projects / 14138 MD /
  296M frames / 33.6 TB。`LICENSE` は 4511 件が CC-BY 4.0。条件ベクトル
  (`FF` `TEMP` `WAT` `ENSEMBLE` `TIMESTEP` `LENGTH` `SOL` `NA` `CL` `MEMBRANES` `PDBIDS`) が機械可読。
  前計算解析が約 4500 系 × 10 種 (`rmsds` 4551 / `fluctuation` 4551 / `rgyr` 4551 / `sasa` 4552 /
  `pca` 4552 / `tmscores` 3285 / `hbonds` 2318 / `interactions` 2398、膜系は `apl` `thickness`
  `lipid-order` `mem-map`) で JSON 時系列としてそのまま取得できる。`mdcount>=2` が 1328 project
  (10 replicas が 605、6 が 271、8 が 160、9 が 152)。
- **MDDB に GPCR はほぼ無い。** 全 4554 中で脂質を含むのは 43 件のみ、うち GPCR は
  `OTRMG` / `OTRMGb` (ヒトオキシトシン受容体, 7RYC, Amber ff14SB, 3 replicas, LIPIRES=256) の 1 系だけ。
  残りは CLC (8-9 replicas)、Nav (5WEO)、TARP γ2/γ7、HCN、CTL1、SARS-CoV-2 spike/膜、
  および LIPIRES=1 の界面活性剤単分子系。膜系タスクで MDDB は GPCRmd の代替にならない。
- GPCRmd: API とファイル DL はログイン必須 (DL は 1 リクエスト 5 dynamics 上限) だが、
  **`/dynadb/dynamics/id/<id>/` の report ページは無認証で完全な条件表を返す**。
  ID 36 実測: 3REY.A / Inactive / TIP3P / POPC / Cl 191 mM, Na 159 mM /
  Water 22376, POPC 207, Cl 77, Na 64 / 100039 atoms / CHARMM36m / 4.0 fs / Replicates 3 / 1.5 µs。
  `/dynadb/datasets/` は無認証で 773 の view ID を Complex / Apoform ペアとして公開。
- **GPCRmd は CHARMM 一様ではない。** 実在 24 ID をサンプルして 12 件パースできたうち、
  1 件が ff19SB/lipid21/GAFF2 + AMBER PMEMD.CUDA (ID 2322)。CHARMM も 36 / 36m Feb2016 /
  May2015 / c36 Jul2021 と版が割れ、エンジンは ACEMD / ACEMD3 / GROMACS 2021.3 / PMEMD、
  膜は POPC 単一が 6 件で残り 4 件が混合 (DOPC/DPPC/DSPC/SDPC、POPC+CHL1、POPG+CO1+POPC)。
  Nature Methods 2020 のコアが一様なだけで、以後のコミュニティ投稿は多様化している。
- 24 ID 中 12 は report ページを取得できず (500 / no report)。773 は上限であって使える N ではない。
  8/24-8/28 は GPCRmd メンテナンス予定。

**既存ハーネスの状態 (grep で確認).**

- MDPrepBench: `check_type` は 24 種すべて**バージョン無し**。集計は重み付き平均 (補償的) +
  `_HARD_FAIL_CHECK_TYPES` クランプ。軸は `identity` / `physical_validity` / `fidelity` / `provenance`。
- MDStudyBench: `region_water_occupancy@1` 形式で**バージョン有り**。
  `grounded_correct = valid_execution AND claim_supported AND truth_agreement` の非補償 AND。
- **どちらにも solve 時のネットワーク遮断が無い** (`run.py` に該当制御なし)。
  参照 DB を使うベンチではこれが最大の穴で、エージェントが参照そのものを取得できると全層が同時に無効化される。

**判断.**

- 検証は 7 層 (`identity` / `physical_validity` / `composition_fidelity` / `execution_validity` /
  `observable_fidelity` / `claim_support` / `truth_agreement`) に分け、層をまたぐ補償はしない。
  外部 DB が要るのは 3 層だけで、残り 4 層は DB なしで先に固められる。
- 新規語彙は `observable_fidelity` の 1 つだけ。参照軌道を固定入力として渡す層で、**MD を走らせない**ので CI に載る。
- 力場一致は要件にしない。組成照合・参照軌道の再解析・ペア差分のいずれも参照の力場に依存しないため。
  「GPCRmd が CHARMM だから使いにくい」が効くのは絶対値を参照に合わせにいく設計だけで、それは採らない。
- 自前 MD と参照を絶対値で比べる層 (L4b) は σ_FF が測れる場合のみ作る。
  測定源は「GPCRmd 内で同一 PDB が CHARMM コアと Amber 投稿の両方に現れるペア」。無ければ作らない。

**次の 3 手 (いずれも MD 不要).** (1) MDDB の 1328 project から観測量ごとの σ_rep を算出、
(2) GPCRmd 773 ID をクロールして同一 PDB の力場違いペアを探索し L4b の可否を決める、
(3) `observable_fidelity` タスクを 10 本作る。
