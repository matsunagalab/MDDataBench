"""Evidence-backed execution diagnosis, separate from scientific scoring."""

import json
import math
from pathlib import Path


def measured(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def gpu_totals(values):
    """Never label a partial allocation-time subtotal as a complete total."""
    values = list(values)
    known = [v for v in values if measured(v)]
    return {"gpu_seconds": sum(known) if values and len(known) == len(values) else None,
            "gpu_seconds_known": sum(known) if known else None,
            "gpu_observed_count": len(known), "gpu_expected_count": len(values),
            "gpu_coverage": len(known) / len(values) if values else None}


def read_record(path):
    try:
        record = json.loads(path.read_text())
        return record if isinstance(record, dict) else {}
    except (OSError, ValueError):
        return {}


def diagnose(job_dir, report, passed, jobs=(), explicit=None, scheduler_source=None):
    """Preserve failures, without treating recovered branches as final causes.

    A unique failed node is an observed execution failure, not a proven causal
    explanation of every downstream state. Multiple failures remain ambiguous.
    """
    checks = [dict(row) for row in (report or {}).get("checks", [])
              if row.get("weight", 0) and not row.get("passed")]
    nodes, evidence = [], []
    for path in sorted(Path(job_dir).glob("nodes/*/node.json")):
        node = read_record(path)
        if not node:
            continue
        metadata = node.get("metadata") or {}
        item = {"node_id": node.get("node_id", path.parent.name),
                "node_type": node.get("node_type", node.get("type")),
                "status": node.get("status"), "source": str(path),
                "timestamp": node.get("updated_at"),
                "code": metadata.get("failure_code"), "errors": metadata.get("errors", [])}
        nodes.append(item)
        if item["status"] == "failed":
            evidence.append({**item, "kind": "node_failure"})
        failure_path = path.parent / "artifacts/failure/latest/failure_manifest.json"
        failure = read_record(failure_path)
        if failure:
            evidence.append({"kind": "tool_failure", "source": str(failure_path),
                             "node_id": item["node_id"], "code": failure.get("code"),
                             "errors": failure.get("errors", []), "tool": failure.get("tool"),
                             "timestamp": failure.get("recorded_at")})
    for path in sorted((Path(job_dir) / "events").glob("*.json")):
        event = read_record(path)
        if event.get("success") is False:
            details = event.get("details") or {}
            evidence.append({"kind": "event_failure", "source": str(path),
                             "node_id": event.get("node_id"), "timestamp": event.get("timestamp"),
                             "code": details.get("code"), "errors": details.get("errors", []),
                             "event_type": event.get("event_type")})
    for job in jobs:
        if job.get("state") not in {None, "COMPLETED", "RUNNING", "PENDING"}:
            evidence.append({"kind": "scheduler_failure", "source": scheduler_source, **job})
    complete = passed or any(n["node_type"] == "prod" and n["status"] == "completed" for n in nodes)
    failed = [n for n in nodes if n["status"] == "failed"]
    # Old failed branches/events remain evidence; successful production means
    # they must not be selected as the final execution failure.
    stage, code, detail = None, None, None
    status = "completed" if complete else "unknown"
    if not passed:
        if explicit:
            stage, code, detail = explicit.get("stage"), explicit.get("code"), explicit.get("detail")
            status = "reported_failure"
        elif complete:
            stage, code = "evaluation", "checks_failed" if checks else "score_unavailable"
        elif failed:
            stage, status = "execution", "failed"
            if len(failed) == 1:
                item = failed[0]
                relevant = [e for e in evidence if e.get("node_id") == item["node_id"] and e.get("code")]
                codes = {e["code"] for e in relevant}
                code = item["code"] or (next(iter(codes)) if len(codes) == 1 else "node_failed")
                messages = item["errors"] or [message for e in relevant for message in e.get("errors", [])]
                detail = "; ".join(dict.fromkeys(str(m) for m in messages)) or None
            else:
                code = "multiple_execution_failures"
        elif nodes:
            stage, code, status = "execution", "production_incomplete", "incomplete"
        elif any(e["kind"] == "scheduler_failure" for e in evidence):
            stage, code, status = "execution", "scheduler_failure_observed", "failed"
        else:
            stage, code = "unknown", "execution_evidence_unavailable"
    return {"failure_stage": stage, "failure_code": code, "failure_detail": detail,
            "scoring_failures": checks,
            "execution_diagnostics": {"schema_version": 1, "status": status,
                                      "nodes": nodes, "evidence": evidence,
                                      "explicit_failure": explicit}}
