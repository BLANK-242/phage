"""A/B tests the four signature-text formats (F0-F3) against the existing
labeled dataset. Committed.

Task 2 of docs/PHAGE_cc_prompt_signature_format_ab.md.

data/recognition_pairs.jsonl is FIXED INPUT — not regenerated here. Only the
embedded string changes per format; the 65 labeled pairs (and their
expected_recognize labels) stay exactly as generated for the prior brief.

ISOLATION: each format writes its anchors to its OWN eval scope,
{"app_name": f"phage-eval-{format_id.lower()}"} — never shared between
formats, never the production {"app_name": "phage-archivist"} scope. Every
format's scope is wiped and its emptiness verified via retrieve-after-
delete BEFORE that format's writes begin (defensive) and AFTER its deletes
complete (required) — a cross-format nearest neighbour would silently
corrupt every number downstream, so formats run strictly sequentially, one
fully torn down before the next starts.

Retrieval stays top-1 over the WHOLE anchor pool (25 anchors per format) for
every query — the real deployment condition: a hard negative gets 25
chances to sit near something. Never narrowed to its own paired anchor.
"""

from __future__ import annotations

import json
import statistics
from typing import Optional

from phage.archivist.memory import _client, _engine_name, _signature_text
from phage.targets import FLEET

_DATASET_PATH = "data/recognition_pairs.jsonl"
_FORMATS = ("F0", "F1", "F2", "F3")
_SWEEP_MIN, _SWEEP_MAX = 30, 95  # 0.30 to 0.95 in 0.01 steps, matching tune_threshold.py


def _tool_scope_for(target_id: str) -> list[str]:
    return next(t.tool_scope for t in FLEET if t.id == target_id)


def _load_dataset() -> list[dict]:
    records = []
    with open(_DATASET_PATH) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def _eval_scope(format_id: str) -> dict[str, str]:
    return {"app_name": f"phage-eval-{format_id.lower()}"}


def _wipe_scope(client, scope: dict[str, str]) -> int:
    existing = client.agent_engines.memories.retrieve(
        name=_engine_name(), scope=scope, simple_retrieval_params={"page_size": 100}
    )
    n = 0
    for rm in existing:
        memory = getattr(rm, "memory", None)
        if memory is not None:
            client.agent_engines.memories.delete(name=memory.name)
            n += 1
    return n


def _count_in_scope(client, scope: dict[str, str]) -> int:
    remaining = client.agent_engines.memories.retrieve(
        name=_engine_name(), scope=scope, simple_retrieval_params={"page_size": 100}
    )
    return len(list(remaining))


def _write_anchors(client, scope, records: list[dict], format_id: str) -> dict[tuple, dict]:
    """Returns {(target, archetype, anchor_text): {"name": ..., "fact": ...}}."""
    written: dict[tuple, dict] = {}
    name = _engine_name()
    for r in records:
        key = (r["target"], r["archetype"], r["anchor_text"])
        if key in written:
            continue
        fact = _signature_text(
            target_id=r["target"],
            archetype_id=r["archetype"],
            target_tools=_tool_scope_for(r["target"]),
            injection_text=r["anchor_text"],
            format_id=format_id,
        )
        op = client.agent_engines.memories.create(
            name=name, fact=fact, scope=scope, config={"wait_for_completion": True}
        )
        written[key] = {"name": op.response.name, "fact": fact}
    return written


def _query(client, scope, record: dict, format_id: str) -> tuple[Optional[float], Optional[str]]:
    query_target = record.get("query_target", record["target"])
    query_fact = _signature_text(
        target_id=query_target,
        archetype_id=record["archetype"],
        target_tools=_tool_scope_for(query_target),
        injection_text=record["query_text"],
        format_id=format_id,
    )
    results = client.agent_engines.memories.retrieve(
        name=_engine_name(),
        scope=scope,
        similarity_search_params={"search_query": query_fact, "top_k": 3},
    )
    nearest = next(iter(results), None)
    if nearest is None:
        return None, None
    distance = getattr(nearest, "distance", None)
    memory = getattr(nearest, "memory", None)
    fact = getattr(memory, "fact", None) if memory is not None else None
    return distance, fact


def _auc(variant: list[float], hard_negative: list[float]) -> float:
    """Mann-Whitney AUC: fraction of variant x hard_negative pairs where the
    variant distance is smaller (ties count 0.5). Below 0.5 = ranking
    inverted, no threshold can work."""
    total = len(variant) * len(hard_negative)
    if total == 0:
        return float("nan")
    count = 0.0
    for v in variant:
        for h in hard_negative:
            if v < h:
                count += 1.0
            elif v == h:
                count += 0.5
    return count / total


def _fpr_at_min_tpr(variant: list[float], hard_negative: list[float], min_tpr: float):
    """Sweeps the SAME 0.30-0.95/0.01 grid as tune_threshold.py's _sweep().
    Returns (threshold, tpr, fpr) with minimum FPR among grid thresholds
    achieving tpr >= min_tpr; None if none do within the grid."""
    best = None
    t = _SWEEP_MIN
    while t <= _SWEEP_MAX:
        threshold = round(t / 100, 2)
        tpr = sum(1 for d in variant if d < threshold) / len(variant)
        fpr = sum(1 for d in hard_negative if d < threshold) / len(hard_negative)
        if tpr >= min_tpr and (best is None or (fpr, threshold) < (best[2], best[0])):
            best = (threshold, tpr, fpr)
        t += 1
    return best


def run_format(client, format_id: str, records: list[dict]) -> dict:
    scope = _eval_scope(format_id)
    print(f"\n{'=' * 70}\nFORMAT {format_id}  scope={scope}\n{'=' * 70}", flush=True)

    pre_wipe = _wipe_scope(client, scope)
    if pre_wipe:
        print(f"  defensive pre-wipe: deleted {pre_wipe} pre-existing memories", flush=True)

    anchors = _write_anchors(client, scope, records, format_id)
    print(f"  wrote {len(anchors)} unique anchors", flush=True)

    by_class: dict[str, list[Optional[float]]] = {}
    identity_hits = 0
    identity_total = 0

    for r in records:
        distance, matched_fact = _query(client, scope, r, format_id)
        by_class.setdefault(r["class"], []).append(distance)
        if r["class"] == "variant":
            identity_total += 1
            own_key = (r["target"], r["archetype"], r["anchor_text"])
            own_fact = anchors[own_key]["fact"]
            if matched_fact == own_fact:
                identity_hits += 1
    print(f"  queried {len(records)} rows", flush=True)

    variant_d = sorted(d for d in by_class.get("variant", []) if d is not None)
    hard_negative_d = sorted(d for d in by_class.get("hard_negative", []) if d is not None)
    cross_target_d = sorted(d for d in by_class.get("cross_target", []) if d is not None)

    auc = _auc(variant_d, hard_negative_d)
    at_100 = _fpr_at_min_tpr(variant_d, hard_negative_d, 1.00)
    at_95 = _fpr_at_min_tpr(variant_d, hard_negative_d, 0.95)
    identity_acc = identity_hits / identity_total if identity_total else None
    ct_median = statistics.median(cross_target_d) if cross_target_d else None

    summary = {
        "format": format_id,
        "variant": {
            "n": len(variant_d), "min": variant_d[0], "median": statistics.median(variant_d), "max": variant_d[-1],
        },
        "hard_negative": {
            "n": len(hard_negative_d), "min": hard_negative_d[0],
            "median": statistics.median(hard_negative_d), "max": hard_negative_d[-1],
        },
        "auc": auc,
        "fpr_at_tpr_1.00": at_100[2] if at_100 else None,
        "threshold_at_tpr_1.00": at_100[0] if at_100 else None,
        "fpr_at_tpr_0.95": at_95[2] if at_95 else None,
        "threshold_at_tpr_0.95": at_95[0] if at_95 else None,
        "tpr_at_tpr_0.95_actual": at_95[1] if at_95 else None,
        "variant_top1_identity_accuracy": identity_acc,
        "identity_hits": identity_hits,
        "identity_total": identity_total,
        "cross_target_median": ct_median,
        "cross_target_sorted": cross_target_d,
        "variant_sorted": variant_d,
        "hard_negative_sorted": hard_negative_d,
    }
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("variant_sorted", "hard_negative_sorted", "cross_target_sorted")},
            indent=2,
        ),
        flush=True,
    )

    print(f"  deleting {len(anchors)} anchors...", flush=True)
    for a in anchors.values():
        client.agent_engines.memories.delete(name=a["name"])
    remaining = _count_in_scope(client, scope)
    print(f"  post-delete retrieve against {scope}: {remaining} results (expect 0)", flush=True)
    summary["eval_scope_remaining_after_cleanup"] = remaining

    return summary


def main() -> None:
    client = _client()
    records = _load_dataset()
    print(f"Loaded {len(records)} records from {_DATASET_PATH} (fixed input, NOT regenerated)", flush=True)

    results: dict[str, dict] = {}
    for format_id in _FORMATS:
        results[format_id] = run_format(client, format_id, records)

    with open("data/ab_test_signature_formats_result.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nWrote data/ab_test_signature_formats_result.json", flush=True)

    print("\n\n=== SUMMARY (all formats) ===", flush=True)
    for format_id, s in results.items():
        print(
            f"{format_id}: variant med={s['variant']['median']:.4f} "
            f"hard_neg med={s['hard_negative']['median']:.4f} "
            f"AUC={s['auc']:.4f} "
            f"FPR@TPR=1.00={s['fpr_at_tpr_1.00']} "
            f"FPR@TPR>=0.95={s['fpr_at_tpr_0.95']} "
            f"top1_id_acc={s['variant_top1_identity_accuracy']} "
            f"cross_target_med={s['cross_target_median']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
