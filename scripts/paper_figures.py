#!/usr/bin/env python
"""Provisional paper figures and summary tables from sealed MDDataBench experiments.

Reads every attempt's result.json (and events.jsonl for the agent start time),
builds one tidy table, and draws:

  fig1  pass rate per condition (per attempt with Wilson 95% CI; per task, any replicate)
  fig2  pass rate per task axis and condition
  fig3  outcome breakdown per condition
  fig4  cost of a passing attempt (agent wall, model calls, tokens, GPU hours)
  fig5  the tasks that failed under CLI + skills: campaign vs rerun
  fig6  models compared under CLI + skills (one bar per --experiment label)

Usage:
  python scripts/paper_figures.py --out DIR \
      --experiment kimi-k3=/path/to/kimi-k3-3cond-full-v2 \
      --skill-loss kimi-k3=2026-09-11T14:43:46 \
      --rerun kimi-k3=/path/to/kimi-k3-skill-failed-rerun

--skill-loss marks the CLI + skills attempts of that experiment whose agent
started at or after the given UTC time as run without skills (campaign v2 lost
the skill directory mid-run); such attempts are excluded from every rate and
the condition comparison uses only the tasks whose skill attempts all ran with
skills ("intact tasks").
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import math
from pathlib import Path

CONDITION_LABELS = {"cli_skill_sif": "CLI + skills", "cli_sif": "CLI only", "sif_only": "SIF only"}
CONDITION_ORDER = ["cli_skill_sif", "cli_sif", "sif_only"]
COLORS = {"cli_skill_sif": "#1f77b4", "cli_sif": "#ff7f0e", "sif_only": "#7f7f7f"}
AXIS_ORDER = ["soluble_amber", "soluble_charmm", "complex", "ligand", "metal", "nanobody", "antibody", "nucleic", "membrane"]
OUTCOME_ORDER = ["pass", "timeout", "no MD submitted", "MD execution failed", "checks failed", "infrastructure"]
OUTCOME_COLORS = {"pass": "#2ca02c", "timeout": "#d62728", "no MD submitted": "#e377c2",
                  "MD execution failed": "#9467bd", "checks failed": "#ff7f0e", "infrastructure": "#7f7f7f"}


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _agent_start(attempt: Path) -> str:
    events = attempt / "events.jsonl"
    if not events.is_file():
        return ""
    for line in events.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "agent" in str(row.get("event")) or row.get("command"):
            return str(row.get("at") or "")
    return ""


def _outcome(row: dict) -> str:
    if row["passed"]:
        return "pass"
    stage, code, exit_reason = row["failure_stage"], row["failure_code"], row["exit_reason"]
    if exit_reason == "timeout":
        return "timeout"
    if stage == "agent":
        return "no MD submitted"
    if stage == "execution" or stage == "md":
        return "MD execution failed"
    if stage == "evaluation":
        return "checks failed"
    if stage in ("infra", "scorer"):
        return "infrastructure"
    return "MD execution failed" if code else "infrastructure"


def load_experiment(label: str, directory: Path, skill_loss: str | None) -> list[dict]:
    rows = []
    try:
        dataset_id = json.loads((directory / "experiment.json").read_text()).get("dataset_id")
    except (OSError, ValueError):
        dataset_id = None
    for result in sorted(directory.glob("attempts/*/*/result.json")):
        attempt = result.parent
        r = json.loads(result.read_text())
        m = r.get("metrics") or {}
        d = r.get("execution_diagnostics") or {}
        usage = m.get("token_usage") or {}
        start = _agent_start(attempt)
        skills = True
        if r.get("condition") == "cli_skill_sif" and skill_loss and start and start >= skill_loss:
            skills = False
        row = {
            "experiment": label, "model": label, "condition": r.get("condition"), "task_id": r.get("task_id"),
            "axis": r.get("axis"), "replicate": r.get("replicate"), "passed": bool(r.get("passed")),
            "failure_stage": r.get("failure_stage"), "failure_code": r.get("failure_code"),
            "exit_reason": d.get("agent_exit_reason"), "agent_wall_s": m.get("agent_wall_seconds"),
            "calls": usage.get("calls"), "seconds_per_call": m.get("seconds_per_call"),
            "prompt_tokens": usage.get("prompt_total"), "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": usage.get("reasoning_tokens"), "gpu_seconds": m.get("gpu_seconds"),
            "md_run_seconds": m.get("md_run_seconds"), "total_wall_s": m.get("total_wall_seconds"),
            "checks_passed": r.get("checks_passed"), "checks_total": r.get("checks_total"),
            "skills_present": skills, "agent_start": start, "dataset_id": dataset_id,
        }
        row["outcome"] = _outcome(row)
        rows.append(row)
    return rows


def intact_tasks(rows: list[dict]) -> set[str]:
    """Tasks whose CLI + skills attempts all ran with skills and that have every condition."""
    by_task: dict[str, dict[str, list[dict]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in rows:
        by_task[row["task_id"]][row["condition"]].append(row)
    keep = set()
    for task, conds in by_task.items():
        skill_rows = conds.get("cli_skill_sif", [])
        if skill_rows and all(r["skills_present"] for r in skill_rows) and all(c in conds for c in CONDITION_ORDER if c in {x["condition"] for x in rows}):
            keep.add(task)
    return keep


def rate(rows: list[dict]) -> tuple[int, int, float, float, float]:
    n = len(rows)
    k = sum(1 for r in rows if r["passed"])
    lo, hi = wilson(k, n)
    return k, n, (k / n if n else 0.0), lo, hi


def per_task_any(rows: list[dict]) -> tuple[int, int]:
    by = collections.defaultdict(list)
    for r in rows:
        by[r["task_id"]].append(r["passed"])
    return sum(1 for v in by.values() if any(v)), len(by)


def main() -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--experiment", action="append", default=[], help="LABEL=DIR of a three-condition campaign")
    parser.add_argument("--rerun", action="append", default=[], help="LABEL=DIR of a CLI + skills rerun of failed tasks")
    parser.add_argument("--skill-loss", action="append", default=[], help="LABEL=ISO_UTC: skill attempts started after this ran without skills")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    losses = dict(item.split("=", 1) for item in args.skill_loss)
    experiments = [item.split("=", 1) for item in args.experiment]
    reruns = [item.split("=", 1) for item in args.rerun]

    rows: list[dict] = []
    for label, directory in experiments:
        rows.extend(load_experiment(label, Path(directory), losses.get(label)))
    rerun_rows: list[dict] = []
    for label, directory in reruns:
        rerun_rows.extend(load_experiment(label + " rerun", Path(directory), None))
    for r in rerun_rows:
        r["model"] = r["experiment"].replace(" rerun", "")

    with (out / "attempts.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list((rows or rerun_rows)[0].keys()))
        writer.writeheader()
        writer.writerows(rows + rerun_rows)

    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.dpi": 120, "savefig.dpi": 220, "pdf.fonttype": 42})
    summary: dict = {"experiments": {}, "reruns": {}}

    def save(fig, name):
        fig.savefig(out / f"{name}.pdf", bbox_inches="tight")
        fig.savefig(out / f"{name}.png", bbox_inches="tight")
        plt.close(fig)

    # ------------------------------------------------------------------ per experiment (three conditions)
    for label, _dir in experiments:
        exp = [r for r in rows if r["experiment"] == label]
        conds = [c for c in CONDITION_ORDER if any(r["condition"] == c for r in exp)]
        intact = intact_tasks(exp)
        usable = [r for r in exp if r["skills_present"]]
        subset = [r for r in usable if r["task_id"] in intact]
        stats = {"attempts": len(exp), "tasks": len({r["task_id"] for r in exp}),
                 "skill_attempts_without_skills": sum(1 for r in exp if not r["skills_present"]),
                 "intact_tasks": len(intact), "conditions": {}, "axes": {}, "outcomes": {}}
        for c in conds:
            k, n, p, lo, hi = rate([r for r in subset if r["condition"] == c])
            ka, na, pa, loa, hia = rate([r for r in usable if r["condition"] == c])
            t_any, t_n = per_task_any([r for r in subset if r["condition"] == c])
            stats["conditions"][c] = {"intact": {"passed": k, "n": n, "rate": p, "ci": [lo, hi], "tasks_any": t_any, "tasks": t_n},
                                      "all_with_skills": {"passed": ka, "n": na, "rate": pa, "ci": [loa, hia]}}
            stats["outcomes"][c] = dict(collections.Counter(r["outcome"] for r in subset if r["condition"] == c))
        for ax in AXIS_ORDER:
            stats["axes"][ax] = {c: rate([r for r in subset if r["condition"] == c and r["axis"] == ax])[:3] for c in conds}
        summary["experiments"][label] = stats

        # fig1: per-attempt and per-task rates on the intact tasks
        fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.9))
        x = np.arange(len(conds))
        vals = [stats["conditions"][c]["intact"] for c in conds]
        axes[0].bar(x, [v["rate"] for v in vals], color=[COLORS[c] for c in conds],
                    yerr=[[v["rate"] - v["ci"][0] for v in vals], [v["ci"][1] - v["rate"] for v in vals]], capsize=3)
        for i, v in enumerate(vals):
            axes[0].text(i, v["ci"][1] + 0.02, f"{v['passed']}/{v['n']}", ha="center", fontsize=8)
        axes[0].set_xticks(x, [CONDITION_LABELS[c] for c in conds])
        axes[0].set_ylim(0, 1.12)
        axes[0].set_ylabel("attempts passed")
        axes[0].set_title(f"(a) per attempt, {len(intact)} tasks x 3", fontsize=9, loc="left")
        axes[1].bar(x, [v["tasks_any"] / v["tasks"] for v in vals], color=[COLORS[c] for c in conds])
        for i, v in enumerate(vals):
            axes[1].text(i, v["tasks_any"] / v["tasks"] + 0.02, f"{v['tasks_any']}/{v['tasks']}", ha="center", fontsize=8)
        axes[1].set_xticks(x, [CONDITION_LABELS[c] for c in conds])
        axes[1].set_ylim(0, 1.12)
        axes[1].set_ylabel("tasks passed at least once")
        axes[1].set_title("(b) per task, any of 3 replicates", fontsize=9, loc="left")
        dataset_note = next((r["dataset_id"] for r in exp if r.get("dataset_id")), None)
        fig.suptitle(f"{label}: pass rate by condition" + (f" (dataset {dataset_note})" if dataset_note else ""), fontsize=10)
        fig.tight_layout()
        save(fig, f"fig1_condition_pass_rate_{label}")

        # fig2: per axis
        axes_present = [a for a in AXIS_ORDER if any(r["axis"] == a for r in subset)]
        fig, ax = plt.subplots(figsize=(7.2, 3.0))
        width = 0.8 / len(conds)
        for j, c in enumerate(conds):
            ys, ns = [], []
            for a in axes_present:
                k, n, p = stats["axes"][a][c]
                ys.append(p)
                ns.append(n)
            xs = np.arange(len(axes_present)) + (j - (len(conds) - 1) / 2) * width
            ax.bar(xs, ys, width=width, color=COLORS[c], label=CONDITION_LABELS[c])
        n_tasks = {a: len({r["task_id"] for r in subset if r["axis"] == a}) for a in axes_present}
        ax.set_xticks(np.arange(len(axes_present)), [f"{a.replace('_', ' ')}\n({n_tasks[a]} tasks)" for a in axes_present], fontsize=8)
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("attempts passed")
        ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.18))
        ax.set_title(f"{label}: pass rate by task axis (intact tasks, 3 replicates each)", fontsize=9, loc="left", pad=22)
        fig.tight_layout()
        save(fig, f"fig2_axis_pass_rate_{label}")

        # fig3: outcome breakdown
        fig, ax = plt.subplots(figsize=(5.0, 3.0))
        bottoms = np.zeros(len(conds))
        for outcome in OUTCOME_ORDER:
            fracs = []
            for c in conds:
                rows_c = [r for r in subset if r["condition"] == c]
                fracs.append(sum(1 for r in rows_c if r["outcome"] == outcome) / len(rows_c) if rows_c else 0)
            ax.bar(np.arange(len(conds)), fracs, bottom=bottoms, color=OUTCOME_COLORS[outcome], label=outcome, width=0.6)
            for i, f in enumerate(fracs):
                if f >= 0.06:
                    ax.text(i, bottoms[i] + f / 2, f"{100 * f:.0f}%", ha="center", va="center", fontsize=7, color="white")
            bottoms += np.array(fracs)
        ax.set_xticks(np.arange(len(conds)), [CONDITION_LABELS[c] for c in conds])
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("fraction of attempts")
        ax.legend(frameon=False, fontsize=7, loc="upper left", bbox_to_anchor=(1.0, 1.0))
        ax.set_title(f"{label}: how attempts end ({len(intact)} tasks x 3)", fontsize=9, loc="left")
        fig.tight_layout()
        save(fig, f"fig3_outcomes_{label}")

        # fig4: cost of a passing attempt
        fig, axes4 = plt.subplots(1, 4, figsize=(9.0, 2.6))
        metrics = [("agent_wall_s", "agent wall time (min)", 1 / 60), ("calls", "model calls", 1),
                   ("output_tokens", "output + reasoning tokens (k)", None), ("gpu_seconds", "GPU hours per attempt", 1 / 3600)]
        for ax4, (key, title, scale) in zip(axes4, metrics):
            data = []
            for c in conds:
                vals4 = []
                for r in subset:
                    if r["condition"] != c or not r["passed"]:
                        continue
                    if key == "output_tokens":
                        v = ((r.get("output_tokens") or 0) + (r.get("reasoning_tokens") or 0)) / 1000
                    else:
                        v = (r.get(key) or 0) * scale
                    vals4.append(v)
                data.append(vals4)
            box = ax4.boxplot(data, widths=0.55, patch_artist=True, showfliers=False)
            for patch, c in zip(box["boxes"], conds):
                patch.set_facecolor(COLORS[c])
                patch.set_alpha(0.7)
            for median in box["medians"]:
                median.set_color("black")
            ax4.set_xticks(np.arange(1, len(conds) + 1), [CONDITION_LABELS[c].replace(" ", "\n") for c in conds], fontsize=7)
            ax4.set_title(title, fontsize=8, loc="left")
            stats.setdefault("cost_medians", {})[key] = {c: (float(np.median(v)) if v else None) for c, v in zip(conds, data)}
        fig.suptitle(f"{label}: cost of a passing attempt (medians, intact tasks)", fontsize=9)
        fig.tight_layout()
        save(fig, f"fig4_cost_{label}")

    # ------------------------------------------------------------------ fig5: failed tasks, campaign vs rerun
    for label, _dir in reruns:
        base = [r for r in rows if r["experiment"] == label and r["condition"] == "cli_skill_sif"]
        rr = [r for r in rerun_rows if r["model"] == label]
        tasks = sorted({r["task_id"] for r in rr})
        if not tasks:
            continue
        before = {t: rate([r for r in base if r["task_id"] == t]) for t in tasks}
        after = {t: rate([r for r in rr if r["task_id"] == t]) for t in tasks}
        fig, ax = plt.subplots(figsize=(8.0, 3.0))
        x = np.arange(len(tasks))
        ax.bar(x - 0.2, [before[t][2] for t in tasks], width=0.4, color="#bbbbbb", label="campaign (3 replicates)")
        ax.bar(x + 0.2, [after[t][2] for t in tasks], width=0.4, color=COLORS["cli_skill_sif"], label="rerun after fixes (1 replicate)")
        ax.set_xticks(x, [t.split("_", 1)[1] if "_" in t else t for t in tasks], rotation=60, ha="right", fontsize=7)
        ax.set_ylim(0, 1.15)
        ax.set_ylabel("attempts passed")
        ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper left")
        tot_b = rate([r for r in base if r["task_id"] in set(tasks)])
        tot_a = rate(rr)
        ax.set_title(f"{label}, CLI + skills: the {len(tasks)} tasks that failed at least once; campaign {tot_b[0]}/{tot_b[1]} -> rerun {tot_a[0]}/{tot_a[1]}",
                     fontsize=9, loc="left")
        fig.tight_layout()
        save(fig, f"fig5_failed_tasks_rerun_{label}")
        summary["reruns"][label] = {"tasks": len(tasks), "campaign": tot_b[:3], "rerun": tot_a[:3],
                                    "per_task": {t: {"campaign": before[t][:3], "rerun": after[t][:3]} for t in tasks}}

    # ------------------------------------------------------------------ fig6: models under CLI + skills
    labels = [label for label, _ in experiments]
    fig, ax = plt.subplots(figsize=(max(3.0, 1.2 * len(labels) + 1.5), 2.8))
    vals6 = []
    for label in labels:
        exp = [r for r in rows if r["experiment"] == label and r["condition"] == "cli_skill_sif" and r["skills_present"]]
        vals6.append(rate(exp))
    ax.bar(np.arange(len(labels)), [v[2] for v in vals6], color=COLORS["cli_skill_sif"],
           yerr=[[v[2] - v[3] for v in vals6], [v[4] - v[2] for v in vals6]], capsize=3, width=0.5)
    for i, v in enumerate(vals6):
        ax.text(i, v[4] + 0.02, f"{v[0]}/{v[1]}", ha="center", fontsize=8)
    ax.set_xticks(np.arange(len(labels)), labels)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("attempts passed")
    ax.set_title("CLI + skills: models compared (attempts run with skills)", fontsize=9, loc="left")
    fig.tight_layout()
    save(fig, "fig6_models_cli_skills")
    summary["models_cli_skills"] = {label: {"passed": v[0], "n": v[1], "rate": v[2], "ci": [v[3], v[4]]} for label, v in zip(labels, vals6)}

    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "experiments"}, indent=1)[:1500])
    for label, stats in summary["experiments"].items():
        print(label, "intact tasks", stats["intact_tasks"], "| conditions:", {c: (v["intact"]["passed"], v["intact"]["n"], round(v["intact"]["rate"], 3)) for c, v in stats["conditions"].items()})


if __name__ == "__main__":
    main()
