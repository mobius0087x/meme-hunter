"""Atomic UTF-8 state and append-only, point-in-time research snapshots."""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = Path(os.environ.get("MH_DATA_DIR", str(ROOT / ".runtime"))).resolve()
RULES_VERSION = "2026-09-07-disjoint-v2"


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def archive_cycle(pools, verdicts, requests, stats, root=RUNTIME):
    from dataclasses import asdict
    now = datetime.now(timezone.utc)
    rows = []
    by_pool = {v.pool.address: v for v in verdicts}
    for p in pools.values():
        row = asdict(p)
        row["created_at"] = p.created_at.isoformat() if p.created_at else None
        row["observed_at"] = p.observed_at.isoformat()
        v = by_pool.get(p.address)
        row["decision"] = ({"tier": v.tier.name, "score": v.score, "rejected": v.rejected,
            "reasons": v.reasons, "warnings": v.warnings, "score_parts": v.score_parts,
            "forensic": asdict(v.forensic) if v.forensic else None} if v else {"excluded": "outside_new_pool_window"})
        rows.append(row)
    path = root / "archive" / now.strftime("%Y-%m-%d") / (now.strftime("%H%M%S") + "-" + uuid.uuid4().hex + ".json")
    atomic_json(path, {"schema_version": 1, "rules_version": RULES_VERSION,
        "recorded_at": now.isoformat(), "stats": stats, "requests": requests, "candidates": rows})
    return path
