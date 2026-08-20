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

## 2026-08-20 — MDDataBench を別リポジトリに切り出した

MDPrepBench / MDStudyBench と同じ形で `/home/yasu/tmp/MDDataBench` に独立させた。
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
