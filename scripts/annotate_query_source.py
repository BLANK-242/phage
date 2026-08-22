"""Adds query_source_archetype to every record in data/recognition_pairs.jsonl.

Task 1 of docs/PHAGE_cc_prompt_loao_eval.md. This ANNOTATES the existing
dataset in place — it does not regenerate it or call _tailor_one() again
(data/recognition_pairs.jsonl is fixed input; only a new field is added to
each existing record, every other field is preserved verbatim).

The JSONL's `archetype` field records the ANCHOR's label, not the query's
true source. Recovery rule, per class, grounded in
scripts/build_recognition_dataset.py's own construction logic:

  variant / cross_target - query_text is a REAL _tailor_one() mutation of
    the anchor's own archetype (_generate_variant_rows /
    _build_cross_target_rows both mutate/reuse the SAME archetype as the
    anchor). query_source_archetype = archetype. Not text-matched — a
    Gemini paraphrase cannot be matched against a fixed template string —
    this is a fact about how the row was built, not a guess.

  hard_negative - query_text is render_local(some_OTHER_archetype, slots)
    for the anchor's own target (_build_hard_negative_rows) - an EXACT
    deterministic template rendering, no LLM involved. Recovered by
    rendering all 8 archetypes' templates against that row's target and
    finding the ONE that matches query_text byte-for-byte. Verified
    against the actual text, not assumed from generator bookkeeping.

  easy_negative - query_text is hand-written unrelated content
    (_UNRELATED_SNIPPETS), drawn from no archetype template at all.
    query_source_archetype = null: there is nothing to recover, and the
    brief says do not guess.
"""

from __future__ import annotations

import json

from phage.targets import FLEET
from phage.vaccinator.archetypes import ARCHETYPES
from phage.vaccinator.engine import _slots, classify_scope, render_local

_DATASET_PATH = "data/recognition_pairs.jsonl"


def _tool_scope_for(target_id: str) -> list[str]:
    return next(t.tool_scope for t in FLEET if t.id == target_id)


def _local_text_for(target_id: str, archetype) -> str:
    tools = classify_scope(_tool_scope_for(target_id))
    slots = _slots(tools)
    return render_local(archetype, slots)


def _recover_hard_negative_source(record: dict):
    """Exact byte-for-byte match against all 8 archetypes' renderings for
    this row's target. Returns the archetype id on a unique match, None
    otherwise (0 or >1 matches) — do not guess."""
    target_id = record["target"]
    query_text = record["query_text"]
    matches = [a.id for a in ARCHETYPES if _local_text_for(target_id, a) == query_text]
    if len(matches) == 1:
        return matches[0]
    return None


def annotate(record: dict) -> dict:
    cls = record["class"]
    if cls in ("variant", "cross_target"):
        source = record["archetype"]
    elif cls == "hard_negative":
        source = _recover_hard_negative_source(record)
    elif cls == "easy_negative":
        source = None
    else:
        raise ValueError(f"unknown class {cls!r} in record {record.get('id')!r}")
    annotated = dict(record)
    annotated["query_source_archetype"] = source
    return annotated


def main() -> None:
    records = []
    with open(_DATASET_PATH) as f:
        for line in f:
            records.append(json.loads(line))

    annotated = [annotate(r) for r in records]

    unresolved = [r for r in annotated if r["query_source_archetype"] is None and r["class"] != "easy_negative"]
    print(f"Unresolved rows (excluding easy_negative, which has no source by design): {len(unresolved)}")
    for r in unresolved:
        print(f"  UNRESOLVED: {r['id']} class={r['class']} target={r['target']} archetype={r['archetype']}")

    n_variant = sum(1 for r in annotated if r["class"] == "variant")
    n_variant_equal = sum(
        1 for r in annotated if r["class"] == "variant" and r["query_source_archetype"] == r["archetype"]
    )
    n_hard_negative = sum(1 for r in annotated if r["class"] == "hard_negative")
    n_hard_negative_resolved = sum(
        1 for r in annotated if r["class"] == "hard_negative" and r["query_source_archetype"] is not None
    )
    n_hard_negative_differ = sum(
        1
        for r in annotated
        if r["class"] == "hard_negative"
        and r["query_source_archetype"] is not None
        and r["query_source_archetype"] != r["archetype"]
    )

    print(f"\nvariant: {n_variant_equal}/{n_variant} have query_source_archetype == archetype")
    print(
        f"hard_negative: {n_hard_negative_differ}/{n_hard_negative} resolved AND differ from archetype "
        f"({n_hard_negative_resolved}/{n_hard_negative} resolved total)"
    )

    with open(_DATASET_PATH, "w") as f:
        for r in annotated:
            f.write(json.dumps(r) + "\n")
    print(f"\nWrote {len(annotated)} annotated records to {_DATASET_PATH}")


if __name__ == "__main__":
    main()
