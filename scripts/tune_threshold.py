"""Tunes RECOGNITION_DISTANCE_THRESHOLD against data/recognition_pairs.jsonl
and reports the FPR/TPR.

Task 3 of docs/PHAGE_cc_prompt_archivist_dataset.md. Committed.

ISOLATION (non-negotiable, brief 3.1): every Memory Bank write here uses the
DEDICATED EVAL SCOPE {"app_name": "phage-eval"} — never the production
{"app_name": "phage-archivist"} scope archivist.memory.record()/recognize()
use. This script therefore does NOT call record()/recognize() (their scope
is hardcoded to production) — it reuses only the scope-agnostic pieces,
_client()/_engine_name()/_signature_text(), and supplies its own eval scope.
Reusing _signature_text() specifically (rather than reimplementing it) is
deliberate: that function's whole reason to exist is that record()'s write
side and recognize()'s query side must never drift apart (build brief 3.1);
a second, hand-rolled copy here would reintroduce exactly that risk.

Flow: delete anything already in the eval scope (defensive — a prior crashed
run could have left orphans) -> write each of the dataset's 25 unique
anchors once -> query all 65 rows against the full eval-scope pool (the
real nearest match, exactly what recognize() would see in production, not
an artificially isolated one-anchor comparison) -> report distributions ->
sweep the threshold -> delete every eval memory -> verify empty.
"""

from __future__ import annotations

import json
import os
import statistics
from typing import Optional

from phage.archivist.memory import _client, _engine_name, _signature_text
from phage.targets import FLEET

_DATASET_PATH = "data/recognition_pairs.jsonl"
_EVAL_SCOPE = {"app_name": "phage-eval"}


def _tool_scope_for(target_id: str) -> list[str]:
    return next(t.tool_scope for t in FLEET if t.id == target_id)


def _load_dataset() -> list[dict]:
    records = []
    with open(_DATASET_PATH) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def _wipe_eval_scope(client) -> int:
    """Defensive cleanup before writing — deletes anything already present
    in the eval scope. Returns the count deleted."""
    existing = client.agent_engines.memories.retrieve(
        name=_engine_name(),
        scope=_EVAL_SCOPE,
        simple_retrieval_params={"page_size": 100},
    )
    n = 0
    for rm in existing:
        memory = getattr(rm, "memory", None)
        if memory is not None:
            client.agent_engines.memories.delete(name=memory.name)
            n += 1
    return n


def _write_anchors(client, records: list[dict]) -> dict[tuple, str]:
    """Writes each UNIQUE anchor (by target+archetype+anchor_text) to the
    eval scope once. Returns {(target, archetype, anchor_text): memory_name}."""
    written: dict[tuple, str] = {}
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
        )
        op = client.agent_engines.memories.create(
            name=name,
            fact=fact,
            scope=_EVAL_SCOPE,
            config={"wait_for_completion": True},
        )
        written[key] = op.response.name
    return written


def _query_distance(client, record: dict) -> Optional[float]:
    query_target = record.get("query_target", record["target"])
    query_fact = _signature_text(
        target_id=query_target,
        archetype_id=record["archetype"],
        target_tools=_tool_scope_for(query_target),
        injection_text=record["query_text"],
    )
    results = client.agent_engines.memories.retrieve(
        name=_engine_name(),
        scope=_EVAL_SCOPE,
        similarity_search_params={"search_query": query_fact, "top_k": 3},
    )
    nearest = next(iter(results), None)
    if nearest is None:
        return None
    return getattr(nearest, "distance", None)


def _sweep(variant: list[float], hard_negative: list[float]):
    max_variant = max(variant)
    min_hard_negative = min(hard_negative)

    if max_variant < min_hard_negative:
        chosen = (max_variant + min_hard_negative) / 2
        tpr = sum(1 for d in variant if d < chosen) / len(variant)
        fpr = sum(1 for d in hard_negative if d < chosen) / len(hard_negative)
        return {
            "threshold": chosen,
            "rule": "cleanly-separable-midpoint",
            "tpr": tpr,
            "fpr": fpr,
            "max_variant": max_variant,
            "min_hard_negative": min_hard_negative,
        }

    candidates = []
    t = 30
    while t <= 95:
        threshold = round(t / 100, 2)
        tpr = sum(1 for d in variant if d < threshold) / len(variant)
        fpr = sum(1 for d in hard_negative if d < threshold) / len(hard_negative)
        candidates.append((threshold, tpr, fpr))
        t += 1

    eligible = [c for c in candidates if c[1] >= 0.95]
    if eligible:
        eligible.sort(key=lambda c: (c[2], c[0]))  # min FPR, tie-break smallest threshold
        chosen_t, chosen_tpr, chosen_fpr = eligible[0]
        rule = "overlap-min-fpr-subject-to-tpr>=0.95"
    else:
        ranked = sorted(candidates, key=lambda c: (-c[1], c[2]))
        chosen_t, chosen_tpr, chosen_fpr = ranked[0]
        rule = "overlap-no-threshold-reaches-tpr>=0.95-fallback-max-tpr"

    return {
        "threshold": chosen_t,
        "rule": rule,
        "tpr": chosen_tpr,
        "fpr": chosen_fpr,
        "max_variant": max_variant,
        "min_hard_negative": min_hard_negative,
        "all_candidates": candidates,
    }


def main() -> None:
    client = _client()
    records = _load_dataset()
    print(f"Loaded {len(records)} records from {_DATASET_PATH}")

    wiped = _wipe_eval_scope(client)
    if wiped:
        print(f"Defensive cleanup: deleted {wiped} pre-existing eval-scope memories")

    print("Writing unique anchors to eval scope {'app_name': 'phage-eval'}...")
    written = _write_anchors(client, records)
    print(f"  wrote {len(written)} unique anchor memories")

    print("Querying all 65 rows against the eval-scope pool...")
    by_class: dict[str, list[float]] = {}
    for r in records:
        d = _query_distance(client, r)
        r["_distance"] = d
        by_class.setdefault(r["class"], []).append(d)

    print("\n=== per-class distance distributions ===")
    for cls, dists in by_class.items():
        clean = [d for d in dists if d is not None]
        if clean:
            print(
                f"{cls:15s} n={len(dists):3d} min={min(clean):.4f} "
                f"median={statistics.median(clean):.4f} max={max(clean):.4f}"
            )
        else:
            print(f"{cls:15s} n={len(dists):3d} (no distances returned)")

    variant_d = sorted(d for d in by_class.get("variant", []) if d is not None)
    hard_negative_d = sorted(d for d in by_class.get("hard_negative", []) if d is not None)
    print(f"\nvariant sorted ({len(variant_d)}): {variant_d}")
    print(f"hard_negative sorted ({len(hard_negative_d)}): {hard_negative_d}")

    cross_target_d = [d for d in by_class.get("cross_target", []) if d is not None]
    print(f"\ncross_target distances ({len(cross_target_d)}): {sorted(cross_target_d)}")
    if cross_target_d and variant_d and hard_negative_d:
        ct_median = statistics.median(cross_target_d)
        v_median = statistics.median(variant_d)
        hn_median = statistics.median(hard_negative_d)
        closer_to = "variant" if abs(ct_median - v_median) <= abs(ct_median - hn_median) else "hard_negative"
        print(
            f"cross_target median={ct_median:.4f} vs variant median={v_median:.4f} "
            f"vs hard_negative median={hn_median:.4f} -> clusters with: {closer_to}"
        )

    print("\n=== threshold sweep ===")
    result = _sweep(variant_d, hard_negative_d)
    print(json.dumps({k: v for k, v in result.items() if k != "all_candidates"}, indent=2))

    print("\nDeleting every eval-scope memory...")
    for mem_name in written.values():
        client.agent_engines.memories.delete(name=mem_name)
    print(f"  deleted {len(written)} memories")

    remaining = client.agent_engines.memories.retrieve(
        name=_engine_name(),
        scope=_EVAL_SCOPE,
        simple_retrieval_params={"page_size": 100},
    )
    remaining_list = list(remaining)
    print(f"Post-delete retrieve against eval scope: {len(remaining_list)} results (expect 0)")

    os.makedirs("data", exist_ok=True)
    with open("data/tune_threshold_result.json", "w") as f:
        json.dump(
            {
                "by_class_summary": {
                    cls: {
                        "n": len(dists),
                        "min": min((d for d in dists if d is not None), default=None),
                        "median": statistics.median([d for d in dists if d is not None]) if any(d is not None for d in dists) else None,
                        "max": max((d for d in dists if d is not None), default=None),
                    }
                    for cls, dists in by_class.items()
                },
                "variant_sorted": variant_d,
                "hard_negative_sorted": hard_negative_d,
                "cross_target_sorted": sorted(cross_target_d),
                "sweep_result": result,
                "eval_scope_remaining_after_cleanup": len(remaining_list),
            },
            f,
            indent=2,
        )
    print("\nWrote data/tune_threshold_result.json")


if __name__ == "__main__":
    main()
