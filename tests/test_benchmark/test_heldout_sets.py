"""The selection and build scripts are parameterised by held-out set; v6 stays the default.

Test sets are single-use (2026-11-01): test-v6 (tasks 101-130, split ``test``)
was run once on a frozen MDClaw and is now development data, and test-v7
(tasks 131-160, split ``test_v7``) is built by the same procedure with v6 added
to its development set. ``scripts/heldout_sets.py`` holds each set's
parameters. These tests pin that a run without ``--set`` is still v6, that
``--set v7`` switches every parameter together, and that the v6 selection and
numbering are reproduced from the v6 records.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
DATASET = REPO / "benchmarks" / "mddatabench"

hsets = pytest.importorskip("heldout_sets")


def _dataset():
    return json.loads((DATASET / "dataset.json").read_text())


def _split_ids(split):
    return [t["task_id"] for t in _dataset()["tasks"] if t["split"] == split]


@pytest.fixture
def bt():
    module = pytest.importorskip("build_test_tasks")
    yield module
    module.configure("v6")


@pytest.fixture
def st():
    return pytest.importorskip("select_test_set")


def test_the_default_set_is_v6():
    assert hsets.DEFAULT == "v6" and hsets.get() is hsets.V6 and hsets.get(None) is hsets.V6
    assert hsets.V6.first_number == 101 and hsets.V6.split == "test"
    assert hsets.V6.workdir == Path("/data1/rkp00079/rku00161/testset-20261031")
    assert hsets.V6.mdclaw_commit.startswith("ac0e328")
    assert hsets.V6.previous_test_splits == () and not hsets.V6.previous_tests_are_anchors
    with pytest.raises(SystemExit):
        hsets.get("v5")


def test_v7_follows_v6_and_excludes_it():
    v6, v7 = hsets.V6, hsets.V7
    assert v7.first_number == v6.first_number + 30 == 131
    assert v7.split == "test_v7" and v7.split != v6.split
    assert v7.workdir != v6.workdir
    assert v7.previous_test_splits == (v6.split,) and v7.previous_tests_are_anchors
    assert v7.cast_splits == v6.cast_splits == ("train", "eval")
    # The builder's known limits carry over; MDPrepBench did not change.
    assert set(v6.not_statable) <= set(v7.not_statable)
    assert v7.mdprepbench_pdbs == v6.mdprepbench_pdbs and len(v6.mdprepbench_pdbs) == 30
    assert v7.mdclaw_not_pdb == v6.mdclaw_not_pdb
    assert v7.dataset_id == "MDDataBench-v0.7" and "sealed" in v7.changelog


def test_v6_changelog_is_the_shipped_line():
    """The v0.6 line moved into heldout_sets.py unchanged."""
    assert hsets.V6.changelog in _dataset()["changelog"]
    assert hsets.V6.description_addition.strip() in _dataset()["description"]


def test_the_builder_defaults_to_v6_and_configure_switches_everything(bt):
    assert (bt.SET, bt.WORKDIR, bt.SPLIT, bt.FIRST_NUMBER, bt.RETRIEVED) == (
        hsets.V6, hsets.V6.workdir, "test", 101, "2026-10-31")
    assert set(bt.NOT_STATABLE) == {"2AF1", "1PNE"} and bt.DATASET_ID == "MDDataBench-v0.6"
    bt.configure("v7")
    assert (bt.SET, bt.WORKDIR, bt.SPLIT, bt.FIRST_NUMBER, bt.RETRIEVED) == (
        hsets.V7, hsets.V7.workdir, "test_v7", 131, hsets.V7.retrieved)
    assert bt.NOT_STATABLE is hsets.V7.not_statable and bt.DATASET_ID == "MDDataBench-v0.7"
    assert bt.CHANGELOG == hsets.V7.changelog
    bt.configure("v6")
    assert bt.SPLIT == "test" and bt.WORKDIR == hsets.V6.workdir


def test_no_function_binds_a_work_directory_at_import(bt):
    """derive() and plan() read the configured set's directory when called."""
    import inspect
    for function in (bt.derive, bt.plan):
        assert inspect.signature(function).parameters["workdir"].default is None


def test_dataset_versions_compare_with_a_patch_level(bt):
    assert bt._older("MDDataBench-v0.6", "MDDataBench-v0.7")
    assert bt._older("MDDataBench-v0.6.1", "MDDataBench-v0.7")
    assert not bt._older("MDDataBench-v0.6.1", "MDDataBench-v0.6")
    assert not bt._older("MDDataBench-v0.7", "MDDataBench-v0.6")
    assert not bt._older("MDDataBench-v0.7", "MDDataBench-v0.7")
    assert bt._older(None, "MDDataBench-v0.6")


def test_split_counts_keep_v06_keys_and_add_new_splits(bt):
    tasks = [{"split": s} for s in ["train"] * 3 + ["eval"] * 2 + ["test"] + ["test_v7"] * 4]
    assert bt.split_counts(tasks) == {"total": 10, "train": 3, "eval": 2, "test": 1, "test_v7": 4}
    assert bt.split_counts([{"split": "train"}]) == {"total": 1, "train": 1, "eval": 0, "test": 0}


def _plan_or_skip(bt, name):
    workdir = hsets.get(name).workdir
    if not (workdir / "selection" / "selected.json").is_file():
        pytest.skip(f"{name} selection record not available")
    bt.configure(name)
    return bt.plan()


def test_v6_plan_reproduces_tasks_101_to_130(bt):
    items, replaced = _plan_or_skip(bt, "v6")
    assert [i["task_id"] for i in items] == _split_ids("test")
    assert [(r["replaced"], r["by"]) for r in replaced] == [("2AF1", "1JE8"), ("1PNE", "1J7A")]


def test_v7_plan_numbers_131_to_160_in_dispatch_order(bt):
    items, _ = _plan_or_skip(bt, "v7")
    assert [int(i["task_id"][:3]) for i in items] == list(range(131, 161))
    order = [bt.ORDER.index(i["axis"]) for i in items]
    assert order == sorted(order)
    shipped = _split_ids("test_v7")
    if shipped:
        assert [i["task_id"] for i in items] == shipped


@pytest.mark.parametrize("name", ["v6", "v7"])
def test_finalize_is_idempotent_and_never_downgrades(bt, name, tmp_path, monkeypatch):
    """Rerunning a set's finalize on the shipped dataset changes neither file."""
    if name == "v7" and not _split_ids("test_v7"):
        pytest.skip("test_v7 not built")
    items, _ = _plan_or_skip(bt, name)
    root = tmp_path / "mddatabench"
    (root / "_audits").mkdir(parents=True)
    shutil.copy(DATASET / "dataset.json", root / "dataset.json")
    shutil.copy(bt.AUDIT_CSV, root / "_audits" / bt.AUDIT_CSV.name)
    monkeypatch.setattr(bt, "DATASET", root)
    monkeypatch.setattr(bt, "AUDIT_CSV", root / "_audits" / bt.AUDIT_CSV.name)
    before = {p.name: p.read_bytes() for p in (root / "dataset.json", bt.AUDIT_CSV)}
    result = bt.finalize(items, {"tasks": []})
    after = {p.name: p.read_bytes() for p in (root / "dataset.json", bt.AUDIT_CSV)}
    assert after == before
    assert result["dataset_id"] == _dataset()["dataset_id"]


def test_finalize_bumps_an_older_dataset_once(bt, tmp_path, monkeypatch):
    bt.configure("v7")
    root = tmp_path / "mddatabench"
    (root / "_audits").mkdir(parents=True)
    meta = _dataset()
    meta["tasks"] = [t for t in meta["tasks"] if t["split"] != "test_v7"]
    meta["dataset_id"] = "MDDataBench-v0.6.1"
    meta["changelog"] = [line for line in meta["changelog"] if not line.startswith("v0.7")]
    meta["description"] = meta["description"].replace(hsets.V7.description_addition, "")
    (root / "dataset.json").write_text(json.dumps(meta))
    shutil.copy(bt.AUDIT_CSV, root / "_audits" / bt.AUDIT_CSV.name)
    monkeypatch.setattr(bt, "DATASET", root)
    monkeypatch.setattr(bt, "AUDIT_CSV", root / "_audits" / bt.AUDIT_CSV.name)
    # No new items: the version and the text change, the task list does not.
    for _ in range(2):
        bt.finalize([], {"tasks": []})
    out = json.loads((root / "dataset.json").read_text())
    assert out["dataset_id"] == "MDDataBench-v0.7"
    assert out["changelog"].count(hsets.V7.changelog) == 1
    assert out["description"].count(hsets.V7.description_addition.strip()) == 1


def test_load_cast_reads_the_sets_splits_only(st, monkeypatch, tmp_path):
    """v6 sees the 98 (a v6 rerun ignores 101-130 in the tree); v7 adds v6 as development data."""
    dummy = tmp_path / "reference.pdb"
    dummy.write_text("END\n")
    monkeypatch.setattr(st, "BUNDLES", tmp_path / "none")
    monkeypatch.setattr(st.vc, "reference_structure", lambda *a, **k: dummy)
    monkeypatch.setattr(st.vc, "reference_polymers", lambda path: [])
    roles = {}
    for name in ("v6", "v7"):
        cast = st.load_cast(tmp_path, {}, hsets.get(name))
        roles[name] = {role: [c["task_id"] for c in cast if c["role"] == role]
                       for role in ("cast", "previous_test", "withdrawn")}
    shipped = _split_ids("train") + _split_ids("eval")
    assert sorted(roles["v6"]["cast"]) == sorted(shipped) and len(shipped) == 98
    assert roles["v6"]["previous_test"] == []
    assert roles["v7"]["cast"] == roles["v6"]["cast"]
    assert roles["v7"]["previous_test"] == _split_ids("test")
    assert len(roles["v6"]["withdrawn"]) == len(roles["v7"]["withdrawn"]) == 3
    v6, v7 = hsets.V6, hsets.V7
    item = {"role": "previous_test", "withdrawn": False}
    assert not st.is_anchor(item, v6) and st.is_anchor(item, v7)
    assert st.is_anchor({"role": "cast", "withdrawn": False}, v6)
    assert not st.is_anchor({"role": "withdrawn", "withdrawn": True}, v7)


def test_caps_come_from_the_98_only(st):
    cast = [{"axis": "metal", "withdrawn": False, "role": "cast",
             "reference_system": {"SYSTATS": 100, "PROTRES": 10}},
            {"axis": "metal", "withdrawn": False, "role": "previous_test",
             "reference_system": {"SYSTATS": 900, "PROTRES": 90}}]
    assert st.caps_by_axis(cast) == {"metal": (100, 10)}


def _mdclaw_or_skip():
    checkout = Path("/home/rku00161/mdclaw")
    if not (checkout / ".git").exists():
        pytest.skip("mdclaw checkout not available")
    return checkout


@pytest.mark.parametrize("name", ["v6", "v7"])
def test_mdclaw_mentions_are_reproduced_from_the_pinned_commit(st, name):
    """The git tree at the set's commit gives the mentions its record stores, locations too."""
    _mdclaw_or_skip()
    hs = hsets.get(name)
    record = hs.workdir / "selection" / "selected.json"
    if not record.is_file():
        pytest.skip(f"{name} selection record not available")
    stored = json.loads(record.read_text())["development_set"]["mdclaw_documented_pdbs"]
    if not all((hs.workdir / "cache" / "rcsb" / "entry" / f"{pdb}.json").is_file()
               for pdb in st.mdclaw_tokens(st.MDCLAW_CHECKOUT, hs.mdclaw_commit)):
        pytest.skip("RCSB entry cache incomplete")
    assert st.mdclaw_mentions(hs.workdir, hs) == stored


def test_v7_mentions_add_only_v6_task_systems(st):
    _mdclaw_or_skip()
    old = st.mdclaw_tokens(st.MDCLAW_CHECKOUT, hsets.V6.mdclaw_commit)
    new = st.mdclaw_tokens(st.MDCLAW_CHECKOUT, hsets.V7.mdclaw_commit)
    assert set(old) <= set(new)
    v6_pdbs = {t.rsplit("_", 1)[1].upper() for t in _split_ids("test")}
    assert set(new) - set(old) <= v6_pdbs


def test_a_category_out_of_reserves_hands_its_slot_to_soluble(bt, tmp_path, monkeypatch):
    """Rule 1.8: no reserve left -> the slot goes to soluble, alternating over all moved slots."""
    def item(category, pdb):
        return {"category": category, "pdb_id": pdb, "node": "x", "accession": pdb}
    selected = {
        "shortfall": {"membrane": {"wanted": 1, "found": 0}},     # one slot already moved (ATLAS)
        "selected": [item("antibody", "AB01"), item("antibody", "AB02"),
                     item("soluble_charmm", "SC01"), item("soluble_charmm", "SC02"),
                     item("soluble_amber", "SA01")],
        "reserves": [item("antibody", "AB03"), item("soluble_charmm", "SC03"),
                     item("soluble_amber", "SA02"), item("soluble_amber", "SA03")],
    }
    (tmp_path / "selection").mkdir()
    (tmp_path / "selection" / "selected.json").write_text(json.dumps(selected))
    monkeypatch.setattr(bt, "NOT_STATABLE", {"AB01": "cannot", "AB03": "cannot", "SA02": "cannot"})
    monkeypatch.setattr(bt, "FIRST_NUMBER", 500)
    items, replaced = bt.plan(tmp_path)
    # AB01 -> AB03 (also unstatable) -> no reserve: the slot is the second moved
    # slot, so it goes to MoDEL, whose next reserve SA02 is unstatable -> SA03.
    assert [i["task_id"] for i in items] == [
        "500_antibody_ab02", "501_soluble_sc01", "502_soluble_sc02", "503_soluble_sa01",
        "504_soluble_sa03"]
    assert [(r["replaced"], r["by"]) for r in replaced] == [
        ("AB01", "AB03"), ("AB03", None), (None, "SA02"), ("SA02", "SA03")]
    assert replaced[1]["moved_to"] == "soluble_amber" and replaced[2]["moved_from"] == "antibody"
