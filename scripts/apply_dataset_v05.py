#!/usr/bin/env python
"""Dataset v0.5: stop asking for standard ionisation states; name only what the reference carries.

MDDB's project metadata (80 fields, checked live 2026-09-16) records no pH and
no protonation state. The reference topology is the only record, and 92 of the
98 references are all-standard because that is how pdb2gmx and tleap build a
system, not because anyone chose pH 7. Since v0.3 every prompt closed with
"Simulate every (other) ionisable side chain in its standard state at pH 7:
...", which turned a build convention into an instruction: four campaign
attempts (kimi-k3 v4 008 r2, 013 r1, 069 r2; glm-5.3-flash 025 r2) lost the
prep axis because propka moved one or two unnamed residues (ASH, GLH, HIP).

v0.5 removes that sentence. Tasks with nothing named get a conditions bullet
("neutral pH; ionisation states of the side chains are your choice"); the six
tasks whose reference carries a variant name it with the residue name
("Residue 107 of chain A is a doubly protonated histidine (HIP); keep it that
way.") followed by "Ionisation states of the other side chains are your
choice." The scorer tolerates one proton on unnamed ionisable side chains and
keeps the named ones strict (``composition.compare_monomer``).

Idempotent: a prompt already in the v0.5 form is left alone. ``dataset.json``
gets ``dataset_id`` v0.5 and a changelog line.

Usage: python scripts/apply_dataset_v05.py [--dataset benchmarks/mddatabench] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from mddatabench._task_builder import (FREE_IONISATION_BULLET, OTHER_IONISATION_SENTENCE,
                                       protonation_statements)

DATASET_ID = "MDDataBench-v0.5"
CHANGELOG = ("v0.5 (2026-09-16): the standard-protonation sentence is gone from every prompt. "
             "MDDB records no pH or protonation state, so the sentence encoded the references' "
             "build convention; the scorer now tolerates one proton on any ionisable side chain "
             "the task does not name, and the six tasks whose reference carries a variant name "
             "it with its residue name (HIP) and keep it strict.")
STANDARD_SENTENCE = re.compile(
    r"^Simulate every (?:other )?ionisable side chain in its standard state at pH 7:"
    r"[^\n]*\n(?:\n)?", re.M)
OLD_STATEMENT = re.compile(r"^Residue (\S+) of chain (\S+) is a ([a-z ]+)\.\n(?:\n)?", re.M)
PRODUCTION_BULLET = re.compile(r"^(- at least \*\*[0-9.]+ ns\*\* of production MD)\n", re.M)


def rewrite(prompt: str, stated: list) -> str:
    """The v0.5 text of one prompt, or the prompt unchanged when already there."""
    has_old = STANDARD_SENTENCE.search(prompt) or OLD_STATEMENT.search(prompt)
    if not has_old and ("your choice" in prompt):
        return prompt
    prompt = STANDARD_SENTENCE.sub("", prompt)
    if stated:
        entries = [{"chain": e.get("chain"), "residue": e.get("residue"),
                    "meaning": e.get("meaning"), "name": e.get("name")} for e in stated]
        block = "\n\n".join(protonation_statements(entries) + [OTHER_IONISATION_SENTENCE]) + "\n\n"
        match = OLD_STATEMENT.search(prompt)
        if match:
            start = match.start()
            prompt = OLD_STATEMENT.sub("", prompt)
            prompt = prompt[:start] + block + prompt[start:]
        elif OTHER_IONISATION_SENTENCE not in prompt:
            anchor = prompt.find("Leave the prepared structure")
            prompt = prompt[:anchor] + block + prompt[anchor:]
    elif FREE_IONISATION_BULLET not in prompt:
        prompt, n = PRODUCTION_BULLET.subn(r"\1\n- " + FREE_IONISATION_BULLET + "\n", prompt, count=1)
        if n != 1:
            raise ValueError("no production bullet to anchor the ionisation bullet on")
    return prompt


def apply(dataset: Path, dry_run: bool = False) -> dict:
    changed, unchanged = [], []
    for task_dir in sorted((dataset / "tasks").iterdir()):
        task = json.loads((task_dir / "task.json").read_text())
        stated = task["reference"]["selection"].get("stated_protonation") or []
        prompt_path = task_dir / "prompt.md"
        prompt = prompt_path.read_text()
        try:
            new = rewrite(prompt, stated)
        except ValueError as exc:
            raise ValueError(f"{task_dir.name}: {exc}") from exc
        if new == prompt:
            unchanged.append(task_dir.name)
            continue
        if not dry_run:
            prompt_path.write_text(new)
        changed.append(task_dir.name)
    meta_path = dataset / "dataset.json"
    meta = json.loads(meta_path.read_text())
    if meta.get("dataset_id") != DATASET_ID:
        meta["dataset_id"] = DATASET_ID
        meta.setdefault("changelog", []).append(CHANGELOG)
        if not dry_run:
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    return {"changed": changed, "unchanged": len(unchanged), "dataset_id": meta["dataset_id"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="benchmarks/mddatabench")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = apply(Path(args.dataset), args.dry_run)
    print(json.dumps({"changed": len(result["changed"]), "unchanged": result["unchanged"],
                      "dataset_id": result["dataset_id"]}, indent=1))


if __name__ == "__main__":
    main()
