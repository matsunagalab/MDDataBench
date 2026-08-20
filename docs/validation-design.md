# DB 由来ベンチマークの検証設計

公開 MD データベースから prompt と正解を自動生成するベンチマークを作るとき、
**何をもって「正しい」とするか**の設計。対象は MDPrepBench / MDStudyBench の拡張で、
新規スイートの新設ではない。

**rev.2 (2026-08-18)** — 初版から次を変更した。

1. **供給源を MDDB 単独にした。** GPCRmd は RIKEN でのライセンス上の扱いが難しいため外した。
2. **逐次ゲートを撤回した。** 全軸を独立に評価し、最終合否だけをゲートする。
3. **`observable_fidelity` を「唯一の新規軸」とした記述を訂正した。** 再計算 primitive は既存。
4. **`δ = k·sqrt(σ_rep² + σ_FF²)` を撤回した。** 力場差は分散ではなく系統バイアス。
5. **旧 L4 を 2 軸に分割した。** 失敗原因が異なる。
6. **すべての計数に定義を付けた。** 「脂質を含む 43 件」のような定義なしの数を排除。

## 1. validation の目的は採点ではなく帰属

エージェントの数値が参照と食い違ったとき、原因は 5 つありうる。

1. 系の組み立てが違う
2. MD の走らせ方が違う
3. 解析の仕方が違う
4. 主張が自分の数値から出ていない
5. **何も間違っていない**（力場・サンプリングの差）

単一スコアはこれを区別できない。区別できない検証は、ベンチとしては動いても
ハーネスやスキルの改善には使えない。

**この目的からの帰結として、逐次ゲートにしてはならない。**
初版は「軸 k は k-1 が通ったときのみ評価」としたが、これは自己矛盾だった。
物理妥当性に落ちた提出でも「組成も違う」「自己申告値が捏造」「主張は自己データと整合」
という診断は独立に可能で、それを捨てるのは帰属を捨てることに等しい。

## 2. 診断軸

軸は「**何と照らすか**」で定義する。層ではなく**軸**である（順序関係を持たない）。

| 軸 | 照合先 | 判定 | 外部 DB | 既存実装 |
|----|--------|------|---------|----------|
| `identity` | 課題仕様 | 集合一致 | 不要 | MDPrepBench 軸 |
| `physical_validity` | 物理不変量 | 二値 | 不要 | MDPrepBench 軸 + hard-fail |
| `composition_fidelity` | **参照系の組成** | 許容幅つき数値一致 | **要** | MDPrepBench `fidelity` 軸の照合先を拡張 |
| `execution_validity` | 自分の実行証跡 | 不変量 | 不要 | MDStudyBench `valid_execution` |
| `observable_recompute` | **参照軌道の再解析** | 再計算一致 | **要** | primitive は既存（4 節） |
| `ensemble_reproduction` | **自前 MD と参照の統計** | 等価 / 診断値 | **要** | 無し |
| `claim_support` | 自分の数値 | 決定規則 | 不要 | MDStudyBench `claim_supported` |
| `truth_agreement` | **参照の結論** | 符号一致 | **要** | MDStudyBench `truth_agreement` |

外部 DB が要るのは 4 軸。残り 4 軸は DB なしで強化できる。
**DB 整備を待たずに検証の半分を先に固められる。**

`observable_recompute` と `ensemble_reproduction` を分けたのは失敗原因が違うため。
前者は selection / alignment / PBC / frame 範囲 / 実装版の問題、
後者は sampling / 力場 / 初期条件 / protocol 差の問題で、
同じ原因コードで報告してはいけない。

## 3. 評価規則

1. **実行可能な軸はすべて独立に評価し、軸別診断を保存する。**
2. **三値以上で区別する。** `passed` / `failed` / `not_evaluable`（前提 artifact が無い）/
   `not_attempted`（そのタスクでは課していない）。`failed` と `not_evaluable` を同じ 0 にしない。
3. **最終合否だけを非補償ゲートにする。** 軸間の依存関係グラフは合否判定にのみ使い、
   評価のスキップには使わない。
4. **軸内は重み付き部分点でよい。**

## 4. 既存ハーネスとの対応（訂正）

初版は `observable_fidelity` を「唯一の新規軸」と書いたが**誤り**だった。
軌道から観測量を再計算して自己申告値と突き合わせる実装は既にある。

- `MDPrepBench/mdprepbench/scoring.py:882-947` — reference / variant の 2 軌道をロードし
  block ごとに観測量を再計算、block spread から不確実性を算出
- `MDPrepBench/mdprepbench/scoring.py:1076-1124` — `_check_observable_recompute_consistency`
  （エージェントの報告値と再計算値を比較）
- `MDStudyBench/mdstudybench/scoring.py:1033-1075` — `direction_grounding`
- `MDStudyBench/mdstudybench/scoring.py:1078-1126` — `observable_recompute_consistency`

正確には次のとおり。

- **既存**: 観測量を軌道から再計算するという primitive と scorer 実装
- **未使用**: 現行 MDPrepBench P01-P40 はこれを使っていない
- **新規**: DB の固定参照軌道を**エージェントの入力**として渡す task mode と、
  DB provenance を持つ check contract

DB が変えるのは 3 点に整理される。

1. `composition_fidelity` の照合先を「課題仕様」から「実在の登録系」に上げる
2. `observable_recompute` を既存 primitive の上に task mode として立てる
3. `truth_agreement` の真値をキュレーションから機械生成に替える

## 5. 軸ごとの判定規則

統計が要るのは `ensemble_reproduction` と `truth_agreement` だけ。

### composition_fidelity

```
|x_agent − x_ref| / x_ref ≤ τ
```

τ は物理から決める。**τ を大きくしないと通らない量は採用しない。**

### observable_recompute

参照軌道を固定入力として渡し、指定した観測量を計算させる。正解は同じ軌道からの再計算。

**「同じ軌道なら数値誤差のみ」は成立しない。** alignment、PBC 処理、原子選択、
frame の discard が違えば、科学的に妥当な実装同士でも一致しない。したがって

- **解析契約を観測量ごとに完全に固定する**（selection 文字列、alignment 対象、
  periodic の扱い、discard 率、block 数、単位）
- 契約に版番号を付ける
- 契約が曖昧な観測量は採用しない

**この軸が測る価値のある対象は、まさにこの「契約の一致」である。**
MD を走らせないので CI に載る。

### ensemble_reproduction

3 つのモードを区別する。同じ軸でも要求する校正が違う。

| モード | 参照との関係 | 必要な校正 | 合否に使うか |
|--------|--------------|------------|--------------|
| matched-protocol | 力場・水・ensemble・温度・圧力・解析契約をすべて参照に揃える | σ_rep のみ | **使える** |
| diagnostic-only | 力場が異なる | 不要 | **使わない**（値だけ保存） |
| calibrated | 力場が異なる | 系・観測量クラスごとの感度測定 | 校正後に使える |

初版の「σ_FF が測れなければ絶対値タスクを一切作らない」は強すぎた。
matched-protocol なら力場をまたがないので σ_FF は不要である。

### truth_agreement

Δ の符号を見る。ただし**「力場オフセットはペア差分で相殺される」は一般には成立しない**。
相殺するのは bias が両条件で同じ場合だけで、リガンド相互作用・膜カップリング・
イオン結合・状態安定化への力場依存は条件依存である。したがって

- 参照力場をタスク条件として固定する、または
- 複数力場で符号が安定であることを確認したペアだけを採用する

符号は絶対値より頑健だが、力場非依存ではない。

## 6. σ の扱い

### 撤回した式

```
δ = k · sqrt(σ_rep² + σ_FF²)      ← 使わない
```

この式は次を暗黙に仮定する。

- replica 差と力場差が独立
- 力場差が平均ゼロのランダム変動
- 単一の σ_FF が系・観測量・状態をまたいで転用可能

実際の力場差は**系・リガンド状態・膜・観測量に依存する系統バイアス**であり、
単一分散に畳む根拠がない。

### σ_rep は使えるが条件がある

MDDB の `mdcount>=2` は replica 数を示すだけで、同一軌道長・同一 discard・
独立初期速度・同一解析契約を保証しない。replica exchange 等の特殊 protocol も
除外する必要がある。**σ_rep を出す前に protocol の同一性を検証する。**

### 力場感度が要る場合の代替

1. matched-protocol タスクに限定して σ_FF を回避する
2. project ごとの replica 分布と block bootstrap からタスク固有 margin を作る
3. 絶対平均ではなく profile 相関 / 順位 / 標準化効果量 / Wasserstein 距離で比較する
4. 診断値としてのみ保存し、校正が済むまで合否に入れない
5. 同一構造・同一 protocol を複数力場で自前生成する専用校正セットを作る
6. 正例・負例の両方を要求する（区別できるペアを区別し、同一条件 replica を同等と判定する）

## 7. 参照の強度と汚染

| 強度 | 参照が保証すること | 例 | 汚染耐性 |
|------|--------------------|-----|---------|
| 事実 | 組成 | 水 22376 分子 | 高 |
| 再計算 | 固定契約の出力 | RMSF プロファイル | 高 |
| 統計 | 分布の位置 | 平均 Rg | 中 |
| 主張 | 科学的結論 | 開状態で接触が増える | **低** |

汚染ゲートが必須なのは `truth_agreement` だけ。
`composition_fidelity` と `observable_recompute` は構造的に汚染に強い。

初版の「ネットワーク漏洩で全軸が同時に無効化される」は誇張だった。
DB 取得で直接汚染されるのは `composition_fidelity` / `observable_recompute` /
`ensemble_reproduction` / `truth_agreement` の 4 軸である。

## 8. ハーネス改善項目

| ID | 軸 | 内容 |
|----|----|------|
| H1 | 全軸 | **`check_type` にバージョンを付ける。** MDPrepBench の 24 種はすべて無バージョン。MDStudyBench は `region_water_occupancy@1` 形式。自動生成でタスクが増えると scorer 修正後に過去提出を再採点できない |
| H2 | 組成 / ensemble | **許容幅を literal から derived field へ。** `equivalence_margin: 0.1` を `{estimator, source, n, value}` に |
| H3 | DB 依存 4 軸 | **参照 provenance をタスク契約に固定。** accession + checksum + 取得日 + DB 版 + **ライセンス** |
| H4 | DB 依存 4 軸 | **solve 時に MDDB ドメインを遮断。** 現状どちらのハーネスにも該当制御が無い。RCSB は許可のまま `mddbr.eu` を default-deny |
| H5 | 全軸 | **prompt のリーク検査を生成器に。** accession / DOI / 著者名 / エントリ名 |
| H6 | 実行 | **実行検証は artifact を作った runtime と同じ runtime で走らせる。** 既知の症状（runner venv に openmm/mdtraj が無く正常 run が `openmm_artifact_inspection_failed` になる）はこの違反 |
| H7 | ensemble | **正例・負例の両方をコントロールに置く。** 区別できるペアを区別でき、かつ同一条件 replica を同等と判定できること |
| H8 | truth | **no-MD ベースラインをタスク生成のゲートに。** `study_literature_guess_no_md.py` が解けるタスクは emit しない |
| H9 | 報告 | **単一スコアに畳まない。軸別に、三値以上で出す** |
| **H10** | 集計 | **既存 scorer バグの修正。** `DeterministicCheck.capability` の明示 override (`MDPrepBench/mdprepbench/models.py:291-306`) が集計で無視される。`CheckResult` (`models.py:1079-1085`) が capability を保持せず、`scoring.py:3662-3685` が常に `DEFAULT_CHECK_CAPABILITY` を引くため。現行 P01-P40 は override を使っていないので今の得点には影響しないが、**自動生成タスクが capability を明示し始めると公開契約と実際の集計が食い違う。タスク量産前に直す** |
| **H11** | 全軸 | **解析契約レジストリ。** 観測量ごとに selection / alignment / periodic / discard / block 数 / 単位を版付きで固定する。`observable_recompute` はこれが無いと成立しない |

H4 / H9 / H10 / H11 が、現状の設計に最も欠けている。

## 9. MDDB 単独にした結果

GPCRmd を外し、CC-BY / CC0 に限定した後の供給量。計数の定義は付録に置く。

| 用途 | 使えるもの | 件数 |
|------|-----------|------|
| `observable_recompute` | 前計算解析を持つ project | **約 4500** |
| `composition_fidelity` | 組成メタデータを持つ project | 4554（`PDBIDS` ありは 1975） |
| σ_rep | `mdcount>=2` の project | 1328（要 protocol 同一性検証） |
| 力場感度 | 同一 PDB が複数力場で登録された群 | **11 群、全て CC-BY** |
| `truth_agreement` ペア | NAME から検出できたペア群 | 11 群 / 24 project（要人手確認） |
| **膜系** | CC-BY の実バイアレイヤ | **10（全て SARS-CoV-2 のウイルス膜）** |

**膜系の軸は実質失われた。** 実バイアレイヤ（`LIPIRES>=100`）は 30 件あるが、
うち 20 件が非 CC（AFL 3.0 / Apache 2.0 / MIT / LGPL / 記載なし）で、
唯一の GPCR である `OTRMG` / `OTRMGb` も非 CC である。
**MDPrepBench の既知の弱点（P18 膜系が全モデル失敗）を DB 由来タスクで補強する道は閉じた。**
膜系は従来どおり手書きタスクで扱う。

力場感度の候補として最も有望なのは核酸 4 系
（`1FZX` / `1ICK` / `1SK5` / `3GGI` × OL15 / OL21 / ParmBSC1 / Tumuc1、各 2 entry）で、
力場比較を目的に組まれた study に見える。ただし同一 PDB であっても
リガンドパラメータ・プロトネーション・欠損ループ・イオン強度・ensemble・engine・
軌道長・初期構造が交絡しうるため、**matched であることを確認するまで力場感度に帰属しない。**

## 10. 次にやること

1. **核酸 4 系の matched-protocol 検証**（MD 不要）— 上記 16 entry の protocol を突き合わせ、
   力場以外が揃っているかを確認する。揃っていれば calibrated モードが成立し、
   揃っていなければ `ensemble_reproduction` は matched-protocol と diagnostic-only に限定する。
2. **解析契約レジストリの最小版**（MD 不要）— 観測量 1 つを選び、契約を固定して
   MDDB の前計算値と自前再計算値を突き合わせ、どれだけずれるかを測る。
   H11 の必要性と難易度がここで確定する。
3. **`observable_recompute` タスクを 10 本**（MD 不要）— CI に載る最初の軸。
4. **H10 の scorer バグ修正と回帰テスト**（MD 不要）— タスク量産の前提。

いずれも MD を 1 本も走らせずに完了する。

## 付録: 実測値と定義 (2026-08-18 取得)

計数はすべて定義とともに記す。定義なしの数は使わない。

- `/api/rest/v1/projects/summary`: `projectsCount` 4554 / `mdCount` 14138 /
  `totalFrames` 296128391 / `totalTime` 12174700.69 ns / `dataSizeInTB` 33.66。
  **`totalFrames` は summary エンドポイントの集計値であり、
  project 一覧の `totalFrames` の総和 (287267536) とは一致しない。**
  両者は別の量なので混用しない。
- **ライセンス**: `LICENSE` が CC-BY 4.0 の project 4511、CC0 19。
  CC 系でないものは 24 件（AFL 3.0 が 9、Apache 2.0 が 5、MIT 4、LGPL 2、記載なし 4）。
  **タスク生成はこの 24 件を除外する。**
- **前計算解析**: `analyses` 配列に当該名で始まる要素を持つ **project 数**。
  `sasa` 4552 / `pca` 4552 / `rmsds` 4551 / `fluctuation` 4551 / `rgyr` 4551 /
  `interactions` 2398 / `hbonds` 2318 / `energies` 2304。
  （解析エントリ数ではなく project 数である。`-00` などの suffix は同一名に畳んでいる。）
- **replica**: `mdcount>=2` の project 1328（10 が 605、6 が 271、8 が 160、9 が 152）。
- **脂質**: 定義により件数が変わる。`LIPIRES>0` は 43、`LIPIRES>=100`（実バイアレイヤ）は 30、
  `MEMBRANES` が非空は 10。**「脂質を含む 43 件」という書き方はしない。**
- **GPCR**: `LIPIRES>0` の 43 件を全件目視した結果、GPCR は `OTRMG` / `OTRMGb`
  （ヒトオキシトシン受容体, 7RYC, Amber ff14SB, 3 replicas）のみ。**非 CC。**
- **同一 PDB / 複数力場**: 11 群。`6VXX` が 6 力場、`6M0J` が 5、`6M71` / `6VSB` / `6ACS` が 3、
  `1FZX` / `1ICK` / `1SK5` / `3GGI` が 4（OL15 / OL21 / ParmBSC1 / Tumuc1）、
  `6LU7` / `6NUR` が 2。**全群 CC-BY。**
