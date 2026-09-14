#!/usr/bin/env python
"""Dataset v0.4: say, in every prompt, what the reference does with the deposit's non-polymer components.

Input: ``benchmarks/mddatabench/_audits/nonpolymer-20260914.csv`` (one row per
task; ``unaddressed`` lists the non-polymer residue names on the selected
chains that the prompt left undecided, ``in_reference`` those the reference
keeps). For every task with undecided names:

- sugar residues of glycosylation sites are dropped (the glycosylation-site
  sentence already says to leave them out);
- names the reference keeps are dropped from the exclusion (the kept
  instances are described by ``KEPT``, by hand, from the coordinating residues);
- the rest go to ``task.json`` ``reference.selection.excluded_components`` and
  the builder's sentence is inserted into ``prompt.md`` before the
  standard-protonation sentence, with the polymer noun chosen from
  ``reference_system`` (protein / nucleic acid / system).

Idempotent: a prompt that already carries the sentence is left alone.
``dataset.json`` gets ``dataset_id`` v0.4 and a changelog line.

Usage: python scripts/apply_nonpolymer_audit.py [--dataset benchmarks/mddatabench] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from mddatabench._task_builder import excluded_components_sentence, kept_component_sentence

SUGARS = {"NAG", "NDG", "BMA", "MAN", "FUC", "GAL", "GLC", "BGC", "SIA", "XYS"}
# Components the reference keeps one instance of, read off the coordinating
# residues: 6W9C chain C has ZN 401 (Cys270 only) and ZN 402 (Cys189, Cys224);
# the reference's zinc sits on CYM 186/223 = deposit Cys189/Cys224.
KEPT = {
    "062_metal_6w9c": [{"name": "ZN", "chain": "C", "keep": "402", "bound_by": ["Cys189", "Cys224"],
                        "leave": ["401"], "role": "structural zinc"}],
}
ANCHOR = re.compile(r"^Simulate every (?:other )?ionisable side chain", re.M)
DATASET_ID = "MDDataBench-v0.4"
CHANGELOG = ("v0.4 (2026-09-14): every prompt names the deposit's non-polymer components the reference "
             "does not carry (48 tasks) and, for 6W9C, which of two zincs is kept; glycosylation sites "
             "are named as glycans to leave out (four tasks, 9/14 morning).")


def polymer_subject(task: dict) -> str:
    system = task["reference"].get("reference_system") or {}
    nucleic = bool(system.get("DNARES") or system.get("RNARES"))
    protein = bool(system.get("PROTRES"))
    if protein and nucleic:
        return "system"
    if nucleic:
        return "nucleic acid"
    return "protein"


def apply(dataset: Path, audit: Path, dry_run: bool = False) -> dict:
    changed, unchanged = [], []
    for row in csv.DictReader(audit.open()):
        task_id = row["task"]
        undecided = [n for n in row["unaddressed"].split() if n]
        kept = set(row["in_reference"].split())
        names = sorted({n for n in undecided if n not in SUGARS and n not in kept})
        kept_entries = KEPT.get(task_id, [])
        if not names and not kept_entries:
            unchanged.append(task_id)
            continue
        task_dir = dataset / "tasks" / task_id
        task = json.loads((task_dir / "task.json").read_text())
        prompt_path = task_dir / "prompt.md"
        prompt = prompt_path.read_text()
        sentences = [kept_component_sentence(e) for e in kept_entries]
        if names:
            sentences.append(excluded_components_sentence(names, polymer_subject(task)))
        missing = [s for s in sentences if s not in prompt]
        selection = task["reference"]["selection"]
        merged = sorted(set(selection.get("excluded_components") or []) | set(names))
        touched = missing or merged != (selection.get("excluded_components") or []) \
            or (kept_entries and selection.get("kept_components") != kept_entries)
        if not touched:
            unchanged.append(task_id)
            continue
        if missing:
            match = ANCHOR.search(prompt)
            if not match:
                raise ValueError(f"{task_id}: no protonation sentence to anchor on")
            prompt = prompt[:match.start()] + "\n\n".join(missing) + "\n\n" + prompt[match.start():]
        if names:
            selection["excluded_components"] = merged
        if kept_entries:
            selection["kept_components"] = kept_entries
        if not dry_run:
            prompt_path.write_text(prompt)
            (task_dir / "task.json").write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n")
        changed.append({"task": task_id, "excluded": names, "kept": [e["name"] for e in kept_entries]})
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
    parser.add_argument("--audit", default="benchmarks/mddatabench/_audits/nonpolymer-20260914.csv")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = apply(Path(args.dataset), Path(args.audit), args.dry_run)
    print(json.dumps(result, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
