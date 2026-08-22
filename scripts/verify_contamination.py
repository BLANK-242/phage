"""Task 2 of docs/PHAGE_cc_prompt_loao_eval.md — the falsifiable check.

Re-runs F0 exactly as the A/B did, but records WHICH ANCHOR each hard
negative matched (not just the distance), then checks: of the hard
negatives that recognize at threshold 0.59, how many matched an anchor
whose archetype equals that negative's OWN query_source_archetype (a
genuine same-source twin already in the pool -> confirms contamination)
versus an unrelated anchor (-> the mechanism itself over-recognizes,
refutes the diagnosis)?

Own eval scope {"app_name": "phage-eval-loao-verify"}, never production,
deleted and verified empty at the end.
"""

from __future__ import annotations

import json

from phage.archivist.memory import _client, _engine_name, _signature_text
from phage.targets import FLEET

_DATASET_PATH = "data/recognition_pairs.jsonl"
_EVAL_SCOPE = {"app_name": "phage-eval-loao-verify"}
_THRESHOLD = 0.59


def _tool_scope_for(target_id: str) -> list[str]:
    return next(t.tool_scope for t in FLEET if t.id == target_id)


def _load_dataset() -> list[dict]:
    records = []
    with open(_DATASET_PATH) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def _wipe(client, scope) -> int:
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


def _count_in_scope(client, scope) -> int:
    remaining = client.agent_engines.memories.retrieve(
        name=_engine_name(), scope=scope, simple_retrieval_params={"page_size": 100}
    )
    return len(list(remaining))


def main() -> None:
    client = _client()
    records = _load_dataset()
    print(f"Loaded {len(records)} records", flush=True)

    pre = _wipe(client, _EVAL_SCOPE)
    if pre:
        print(f"defensive pre-wipe: deleted {pre}", flush=True)

    name = _engine_name()
    fact_to_archetype: dict[str, str] = {}
    written: dict[tuple, str] = {}
    for r in records:
        key = (r["target"], r["archetype"], r["anchor_text"])
        if key in written:
            continue
        fact = _signature_text(
            target_id=r["target"],
            archetype_id=r["archetype"],
            target_tools=_tool_scope_for(r["target"]),
            injection_text=r["anchor_text"],
            format_id="F0",
        )
        op = client.agent_engines.memories.create(
            name=name, fact=fact, scope=_EVAL_SCOPE, config={"wait_for_completion": True}
        )
        written[key] = op.response.name
        fact_to_archetype[fact] = r["archetype"]
    print(f"wrote {len(written)} anchors", flush=True)

    hard_negatives = [r for r in records if r["class"] == "hard_negative"]
    results = []
    for r in hard_negatives:
        query_fact = _signature_text(
            target_id=r["target"],
            archetype_id=r["archetype"],
            target_tools=_tool_scope_for(r["target"]),
            injection_text=r["query_text"],
            format_id="F0",
        )
        res = client.agent_engines.memories.retrieve(
            name=name,
            scope=_EVAL_SCOPE,
            similarity_search_params={"search_query": query_fact, "top_k": 3},
        )
        nearest = next(iter(res), None)
        distance = getattr(nearest, "distance", None) if nearest is not None else None
        memory = getattr(nearest, "memory", None) if nearest is not None else None
        matched_fact = getattr(memory, "fact", None) if memory is not None else None
        matched_archetype = fact_to_archetype.get(matched_fact)
        recognized = distance is not None and distance < _THRESHOLD
        results.append(
            {
                "id": r["id"],
                "query_source_archetype": r["query_source_archetype"],
                "anchor_archetype_label": r["archetype"],
                "distance": distance,
                "recognized": recognized,
                "matched_archetype": matched_archetype,
                "same_source_match": bool(recognized and matched_archetype == r["query_source_archetype"]),
            }
        )
    print(f"queried {len(hard_negatives)} hard_negative rows", flush=True)

    recognized_rows = [x for x in results if x["recognized"]]
    same_source = [x for x in recognized_rows if x["same_source_match"]]
    unrelated = [x for x in recognized_rows if not x["same_source_match"]]

    print(f"\n{len(recognized_rows)}/25 hard negatives recognized at threshold {_THRESHOLD}", flush=True)
    print(f"  same-source match (matched_archetype == query_source_archetype): {len(same_source)}", flush=True)
    print(f"  unrelated match: {len(unrelated)}", flush=True)
    print(flush=True)
    for x in results:
        print(
            f"  {x['id']}: source={x['query_source_archetype']:<28s} "
            f"recognized={x['recognized']!s:5s} distance={x['distance']:.4f} "
            f"matched_archetype={x['matched_archetype']!s:<28s} same_source={x['same_source_match']}",
            flush=True,
        )

    print(f"\nDeleting {len(written)} anchors...", flush=True)
    for mem_name in written.values():
        client.agent_engines.memories.delete(name=mem_name)
    remaining = _count_in_scope(client, _EVAL_SCOPE)
    print(f"post-delete retrieve against {_EVAL_SCOPE}: {remaining} results (expect 0)", flush=True)

    with open("data/loao_verify_result.json", "w") as f:
        json.dump(
            {
                "threshold": _THRESHOLD,
                "results": results,
                "n_recognized": len(recognized_rows),
                "n_same_source": len(same_source),
                "n_unrelated": len(unrelated),
                "eval_scope_remaining_after_cleanup": remaining,
            },
            f,
            indent=2,
        )
    print("\nWrote data/loao_verify_result.json", flush=True)


if __name__ == "__main__":
    main()
