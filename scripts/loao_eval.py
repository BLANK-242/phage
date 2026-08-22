"""Leave-one-archetype-out (LOAO) evaluation. Committed.

Task 3 of docs/PHAGE_cc_prompt_loao_eval.md. The A/B's negative population
was contaminated (Task 2 confirmed: 16/18 recognized hard negatives matched
a genuine same-source twin already in the anchor pool). This re-partitions
the SAME 65 labeled rows (no regeneration, no new _tailor_one() calls, F0
stays the format) so that for each fold, the held-out archetype's content
has NO twin anywhere in the pool — a recognition there is unambiguous.

For each archetype k (8 folds):
  - Anchor pool: all unique anchors EXCEPT those whose archetype == k
  - Positives: variant rows whose own anchor is in that pool (archetype != k)
  - Negatives: ALL rows (any class) with query_source_archetype == k —
    literally per the brief; this naturally includes variant/cross_target
    rows whose OWN intent happens to be the held-out archetype, alongside
    hard_negative rows sourced from it, and naturally excludes
    easy_negative (query_source_archetype is null there, never equals a
    real archetype id).

Every row is queried using ITS OWN `archetype`/`target(or query_target)`
fields exactly as every prior measurement (A/B, contamination check) did —
NOT relabeled to query_source_archetype. hard_negative's "same label as
anchor, different content" mislabeling is deliberate (the realistic
false-positive population per the original dataset brief) and is not what
LOAO is correcting; LOAO corrects the ANCHOR POOL's contamination, a
separate axis. Any recognition against a pool with zero same-source twins
counts as a false positive regardless of why it matched, matching the
brief's own framing ("a recognition is a genuine false positive").

Each fold: its own isolated eval scope
{"app_name": f"phage-eval-loao-{k.lower()}"}, deleted and verified empty
before the next fold starts. All 8 folds' distances are then pooled into
one distribution for the reported metrics.
"""

from __future__ import annotations

import json
import random
import statistics
import time

from google.genai import errors as genai_errors

from phage.archivist.memory import _client, _engine_name, _signature_text
from phage.targets import FLEET
from phage.vaccinator.archetypes import ARCHETYPES

_DATASET_PATH = "data/recognition_pairs.jsonl"
_SWEEP_MIN, _SWEEP_MAX = 30, 95  # 0.30 to 0.95 step 0.01, matching every prior sweep

# This run makes ~600 real Memory Bank calls across 8 sequential folds — long
# enough that a transient 5xx (observed live: 503 UNAVAILABLE mid-write on
# fold 3) is a real risk, and the underlying google.genai client's own retry
# already exhausted before raising. Same backoff shape as phage.llm's
# generate_with_backoff (retryable codes, exponential + jitter), scoped here
# to Memory Bank calls instead of Gemini generation.
_RETRYABLE_CODES = (429, 500, 503)


def _with_retry(fn, *, max_attempts: int = 5, base_delay: float = 1.0):
    delay = base_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except genai_errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code not in _RETRYABLE_CODES or attempt == max_attempts:
                raise
            print(f"    [retry {attempt}/{max_attempts}] {code} on Memory Bank call, backing off {delay:.1f}s", flush=True)
            time.sleep(delay + random.uniform(0, 0.5))
            delay *= 2
    raise RuntimeError("unreachable")


def _tool_scope_for(target_id: str) -> list[str]:
    return next(t.tool_scope for t in FLEET if t.id == target_id)


def _load_dataset() -> list[dict]:
    records = []
    with open(_DATASET_PATH) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def _fold_scope(k: str) -> dict[str, str]:
    return {"app_name": f"phage-eval-loao-{k.lower()}"}


def _wipe(client, scope) -> int:
    existing = _with_retry(
        lambda: client.agent_engines.memories.retrieve(
            name=_engine_name(), scope=scope, simple_retrieval_params={"page_size": 100}
        )
    )
    n = 0
    for rm in existing:
        memory = getattr(rm, "memory", None)
        if memory is not None:
            _with_retry(lambda mn=memory.name: client.agent_engines.memories.delete(name=mn))
            n += 1
    return n


def _count_in_scope(client, scope) -> int:
    remaining = _with_retry(
        lambda: client.agent_engines.memories.retrieve(
            name=_engine_name(), scope=scope, simple_retrieval_params={"page_size": 100}
        )
    )
    return len(list(remaining))


def _fact_for(target_id: str, archetype_id: str, injection_text: str) -> str:
    return _signature_text(
        target_id=target_id,
        archetype_id=archetype_id,
        target_tools=_tool_scope_for(target_id),
        injection_text=injection_text,
        format_id="F0",
    )


def _query(client, scope, target_id: str, archetype_id: str, injection_text: str):
    query_fact = _fact_for(target_id, archetype_id, injection_text)
    res = _with_retry(
        lambda: client.agent_engines.memories.retrieve(
            name=_engine_name(),
            scope=scope,
            similarity_search_params={"search_query": query_fact, "top_k": 3},
        )
    )
    nearest = next(iter(res), None)
    distance = getattr(nearest, "distance", None) if nearest is not None else None
    memory = getattr(nearest, "memory", None) if nearest is not None else None
    fact = getattr(memory, "fact", None) if memory is not None else None
    return distance, fact


def run_fold(client, k: str, records: list[dict], variant_rows: list[dict]) -> dict:
    scope = _fold_scope(k)
    print(f"\n{'=' * 70}\nFOLD k={k}  scope={scope}\n{'=' * 70}", flush=True)

    pre = _wipe(client, scope)
    if pre:
        print(f"  defensive pre-wipe: deleted {pre}", flush=True)

    name = _engine_name()
    pool_anchors: dict[tuple, dict] = {}
    for r in variant_rows:
        if r["archetype"] == k:
            continue
        key = (r["target"], r["archetype"], r["anchor_text"])
        if key in pool_anchors:
            continue
        fact = _fact_for(r["target"], r["archetype"], r["anchor_text"])
        op = _with_retry(
            lambda f=fact: client.agent_engines.memories.create(
                name=name, fact=f, scope=scope, config={"wait_for_completion": True}
            )
        )
        pool_anchors[key] = {"name": op.response.name, "fact": fact}
    print(f"  wrote {len(pool_anchors)} pool anchors (archetype={k} held out)", flush=True)

    positives = [r for r in variant_rows if r["archetype"] != k]
    pos_distances: list[float] = []
    identity_hits = 0
    for r in positives:
        own_key = (r["target"], r["archetype"], r["anchor_text"])
        own_fact = pool_anchors[own_key]["fact"]
        distance, matched_fact = _query(client, scope, r["query_target"], r["archetype"], r["query_text"])
        if distance is not None:
            pos_distances.append(distance)
        if matched_fact == own_fact:
            identity_hits += 1
    print(f"  queried {len(positives)} positives", flush=True)

    negatives = [r for r in records if r.get("query_source_archetype") == k]
    neg_distances: list[float] = []
    for r in negatives:
        query_target = r.get("query_target", r["target"])
        distance, _matched_fact = _query(client, scope, query_target, r["archetype"], r["query_text"])
        if distance is not None:
            neg_distances.append(distance)
    print(f"  queried {len(negatives)} negatives", flush=True)

    print(f"  deleting {len(pool_anchors)} pool anchors...", flush=True)
    for a in pool_anchors.values():
        _with_retry(lambda mn=a["name"]: client.agent_engines.memories.delete(name=mn))
    remaining = _count_in_scope(client, scope)
    print(f"  post-delete retrieve against {scope}: {remaining} results (expect 0)", flush=True)

    print(
        f"  fold summary: n_pos={len(pos_distances)} n_neg={len(neg_distances)} "
        f"identity_hits={identity_hits}/{len(positives)}",
        flush=True,
    )

    return {
        "k": k,
        "n_pool_anchors": len(pool_anchors),
        "n_positives": len(positives),
        "n_negatives": len(negatives),
        "positive_distances": pos_distances,
        "negative_distances": neg_distances,
        "identity_hits": identity_hits,
        "eval_scope_remaining_after_cleanup": remaining,
    }


def _auc(positives: list[float], negatives: list[float]) -> float:
    total = len(positives) * len(negatives)
    if total == 0:
        return float("nan")
    count = 0.0
    for p in positives:
        for n in negatives:
            if p < n:
                count += 1.0
            elif p == n:
                count += 0.5
    return count / total


def _sweep(positives: list[float], negatives: list[float]) -> dict:
    """Same Rule 1 / Rule 2 logic as scripts/tune_threshold.py's _sweep()."""
    max_pos = max(positives)
    min_neg = min(negatives)

    if max_pos < min_neg:
        chosen = (max_pos + min_neg) / 2
        tpr = sum(1 for d in positives if d < chosen) / len(positives)
        fpr = sum(1 for d in negatives if d < chosen) / len(negatives)
        return {
            "threshold": chosen, "rule": "cleanly-separable-midpoint",
            "tpr": tpr, "fpr": fpr, "max_positive": max_pos, "min_negative": min_neg,
        }

    candidates = []
    t = _SWEEP_MIN
    while t <= _SWEEP_MAX:
        threshold = round(t / 100, 2)
        tpr = sum(1 for d in positives if d < threshold) / len(positives)
        fpr = sum(1 for d in negatives if d < threshold) / len(negatives)
        candidates.append((threshold, tpr, fpr))
        t += 1

    eligible = [c for c in candidates if c[1] >= 0.95]
    if eligible:
        eligible.sort(key=lambda c: (c[2], c[0]))
        chosen_t, chosen_tpr, chosen_fpr = eligible[0]
        rule = "overlap-min-fpr-subject-to-tpr>=0.95"
    else:
        ranked = sorted(candidates, key=lambda c: (-c[1], c[2]))
        chosen_t, chosen_tpr, chosen_fpr = ranked[0]
        rule = "overlap-no-threshold-reaches-tpr>=0.95-fallback-max-tpr"

    return {
        "threshold": chosen_t, "rule": rule, "tpr": chosen_tpr, "fpr": chosen_fpr,
        "max_positive": max_pos, "min_negative": min_neg,
    }


def _fpr_at_min_tpr(positives: list[float], negatives: list[float], min_tpr: float):
    best = None
    t = _SWEEP_MIN
    while t <= _SWEEP_MAX:
        threshold = round(t / 100, 2)
        tpr = sum(1 for d in positives if d < threshold) / len(positives)
        fpr = sum(1 for d in negatives if d < threshold) / len(negatives)
        if tpr >= min_tpr and (best is None or (fpr, threshold) < (best[2], best[0])):
            best = (threshold, tpr, fpr)
        t += 1
    return best


def main() -> None:
    client = _client()
    records = _load_dataset()
    variant_rows = [r for r in records if r["class"] == "variant"]
    archetypes = sorted({a.id for a in ARCHETYPES})
    print(f"Loaded {len(records)} records; {len(variant_rows)} unique anchors; {len(archetypes)} archetypes", flush=True)

    fold_results = []
    for k in archetypes:
        fold_results.append(run_fold(client, k, records, variant_rows))

    all_positives = [d for f in fold_results for d in f["positive_distances"]]
    all_negatives = [d for f in fold_results for d in f["negative_distances"]]
    total_identity_hits = sum(f["identity_hits"] for f in fold_results)
    total_positives_n = sum(f["n_positives"] for f in fold_results)

    print(f"\n{'=' * 70}\nPOOLED RESULTS ({len(fold_results)} folds)\n{'=' * 70}", flush=True)
    print(
        f"positives: n={len(all_positives)} min={min(all_positives):.4f} "
        f"median={statistics.median(all_positives):.4f} max={max(all_positives):.4f}",
        flush=True,
    )
    print(
        f"negatives: n={len(all_negatives)} min={min(all_negatives):.4f} "
        f"median={statistics.median(all_negatives):.4f} max={max(all_negatives):.4f}",
        flush=True,
    )
    auc = _auc(all_positives, all_negatives)
    at_100 = _fpr_at_min_tpr(all_positives, all_negatives, 1.00)
    at_95 = _fpr_at_min_tpr(all_positives, all_negatives, 0.95)
    identity_acc = total_identity_hits / total_positives_n if total_positives_n else None
    print(f"AUC = {auc:.4f}", flush=True)
    print(f"FPR@TPR=1.00: threshold={at_100[0] if at_100 else None} fpr={at_100[2] if at_100 else None}", flush=True)
    print(f"FPR@TPR>=0.95: threshold={at_95[0] if at_95 else None} fpr={at_95[2] if at_95 else None} (actual tpr={at_95[1] if at_95 else None})", flush=True)
    print(f"positive top-1 identity accuracy (pooled): {total_identity_hits}/{total_positives_n} = {identity_acc}", flush=True)

    sweep_result = _sweep(all_positives, all_negatives)
    print(f"\nRule 1/2 sweep result: {json.dumps(sweep_result, indent=2)}", flush=True)

    adopted_threshold = sweep_result["threshold"]
    print(f"\nPer-fold FPR at adopted threshold ({adopted_threshold}):", flush=True)
    per_fold_fpr = {}
    for f in fold_results:
        negs = f["negative_distances"]
        fpr = sum(1 for d in negs if d < adopted_threshold) / len(negs) if negs else None
        per_fold_fpr[f["k"]] = {"n_negatives": len(negs), "fpr": fpr}
        print(f"  {f['k']}: n_neg={len(negs)} fpr={fpr}", flush=True)

    qualifies = sweep_result["fpr"] <= 0.25 and (
        sweep_result["tpr"] >= 0.95
    )
    print(f"\nQualifies (FPR<=0.25 at TPR>=0.95)? {qualifies}", flush=True)

    with open("data/loao_eval_result.json", "w") as f:
        json.dump(
            {
                "fold_results": fold_results,
                "pooled_positives_sorted": sorted(all_positives),
                "pooled_negatives_sorted": sorted(all_negatives),
                "auc": auc,
                "fpr_at_tpr_1.00": at_100,
                "fpr_at_tpr_0.95": at_95,
                "identity_accuracy": identity_acc,
                "identity_hits": total_identity_hits,
                "identity_total": total_positives_n,
                "sweep_result": sweep_result,
                "per_fold_fpr_at_adopted_threshold": per_fold_fpr,
                "qualifies": qualifies,
            },
            f,
            indent=2,
        )
    print("\nWrote data/loao_eval_result.json", flush=True)


if __name__ == "__main__":
    main()
