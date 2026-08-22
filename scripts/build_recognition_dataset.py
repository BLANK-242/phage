"""Generates data/recognition_pairs.jsonl — the labeled recognition dataset.

Task 2 of docs/PHAGE_cc_prompt_archivist_dataset.md. Committed (unlike
scripts/probe_distance.py) because the dataset it writes is a fixed artifact
the write-up cites, but it is also regenerable: uv run python
scripts/build_recognition_dataset.py

Four classes, drawn only from the fleet (targets.py) and the archetype
library (vaccinator/archetypes.py) already in this repo — no new attack
families invented:

  variant       (25) — payload P against target T; query = _tailor_one()'s
                        REAL mutation of P for the same T (live Gemini call).
  hard_negative (25) — the SAME 25 anchors as variant; query = a DIFFERENT
                        archetype's local rendering against the same T, but
                        labeled (target=/archetype=/tools=) identically to
                        the anchor. This is the realistic false-positive
                        population (build brief 3.2): everything about the
                        signature-text PREFIX matches; only the injection
                        content differs.
  cross_target  (10) — the first 10 variant rows' anchor+mutation, but the
                        query is labeled against a DIFFERENT target U that
                        also supports the same archetype (query_target).
                        Diagnostic only: tests whether the target= line
                        dominates the embedding and blocks fleet-wide
                        transfer. expected_recognize is null (no ground
                        truth is claimed for this class).
  easy_negative  (5) — 5 of the variant anchors, paired with content about
                        an unrelated topic.

Every row goes through _signature_text-compatible fields (target, archetype,
target_tools looked up from FLEET, injection_text) rather than a pre-baked
wrapped string, so scripts/tune_threshold.py exercises the SAME shared
_signature_text() function record()/recognize() use in production, not a
frozen copy of it.

query_target defaults to target (i.e. is absent from the row logic here but
always written explicitly) for every class except cross_target, where it is
the different target U.
"""

from __future__ import annotations

import json
import random

from google import genai

from phage import config
from phage.targets import FLEET, Target
from phage.vaccinator.archetypes import ARCHETYPES, Archetype
from phage.vaccinator.engine import (
    MutationRefused,
    _slots,
    _tailor_one,
    classify_scope,
    render_local,
    select_archetypes,
)

_SEED = 20260822  # fixed — regenerable means the same dataset comes out each run
_OUT_PATH = "data/recognition_pairs.jsonl"

_N_VARIANT = 25
_N_HARD_NEGATIVE = 25
_N_CROSS_TARGET = 10
_N_EASY_NEGATIVE = 5

_UNRELATED_SNIPPETS = [
    "Here's a simple recipe for Moroccan mint tea: boil water, add fresh "
    "mint leaves and green tea, steep for five minutes, then sweeten "
    "generously with sugar before serving in small glasses.",
    "The Atlas mountains reach their highest point at Jbel Toubkal, just "
    "over 4,000 meters, and are a popular multi-day trekking destination "
    "from Marrakech.",
    "A standard chess opening repertoire for beginners usually starts with "
    "either 1.e4 or 1.d4, focusing on rapid development and central "
    "control.",
    "Sourdough bread needs a mature starter, a long cold ferment, and a hot "
    "Dutch oven to get a good open crumb and a crackly crust.",
    "The Casablanca tramway network connects several districts of the city "
    "and has been steadily expanded since it first opened in 2012.",
]


def _fleet_archetype_pairs() -> list[tuple[Target, Archetype]]:
    """Every (target, archetype) combination the fleet actually supports,
    via the SAME select_archetypes() the engine itself uses for selection."""
    pairs: list[tuple[Target, Archetype]] = []
    for t in FLEET:
        for a in select_archetypes(t.tool_scope):
            pairs.append((t, a))
    return pairs


def _local_text(target: Target, archetype: Archetype) -> str:
    tools = classify_scope(target.tool_scope)
    slots = _slots(tools)
    return render_local(archetype, slots)


def _different_archetype(exclude_id: str, index: int) -> Archetype:
    """Deterministic pick of a DIFFERENT archetype for hard_negative's
    differing intent — cycles ARCHETYPES in fixed order, skipping the
    anchor's own archetype. Drawn only from archetypes this codebase
    already defines (build brief 3.2: "do not invent new attack families")."""
    others = [a for a in ARCHETYPES if a.id != exclude_id]
    return others[index % len(others)]


def _different_target(anchor_target: Target, archetype: Archetype) -> Target | None:
    """Deterministic pick of a different target that ALSO supports this
    archetype — next target in FLEET order (wrapping) that qualifies. None
    if no other target supports it (shouldn't happen: every archetype in
    this fleet applies to at least 2 of the 4 targets)."""
    start = FLEET.index(anchor_target)
    for offset in range(1, len(FLEET)):
        candidate = FLEET[(start + offset) % len(FLEET)]
        if archetype in select_archetypes(candidate.tool_scope):
            return candidate
    return None


def _generate_variant_rows(client, model: str) -> tuple[list[dict], int, int]:
    """Returns (rows, refused_count, attempted_count). Each row: target,
    archetype, anchor_text, mutation_text (the real _tailor_one() paraphrase)."""
    all_pairs = _fleet_archetype_pairs()
    pool = list(all_pairs)
    random.Random(_SEED).shuffle(pool)

    rows: list[dict] = []
    used: set[tuple[str, str]] = set()
    refused = 0
    attempted = 0
    idx = 0

    # One pass over the shuffled pool first (28 unique pairs); if that isn't
    # enough (i.e. > 3 refusals), fall back to fresh (stochastic,
    # temperature=0.7 — see _tailor_one) re-attempts over the SAME pool
    # rather than ever inventing new pairs. Each attempt is still "a
    # different source payload" than whichever one JUST failed, per 3.3.
    max_passes = 6
    for _pass in range(max_passes):
        if len(rows) >= _N_VARIANT:
            break
        for target, archetype in pool:
            if len(rows) >= _N_VARIANT:
                break
            key = (target.id, archetype.id)
            if key in used:
                continue
            anchor_text = _local_text(target, archetype)
            attempted += 1
            try:
                _inj, mutation = _tailor_one(
                    client,
                    model=model,
                    tool_scope=target.tool_scope,
                    arch_id=archetype.id,
                    text=anchor_text,
                    target=target.id,
                )
            except MutationRefused:
                refused += 1
                continue
            used.add(key)
            rows.append(
                {
                    "target": target.id,
                    "archetype": archetype.id,
                    "anchor_text": anchor_text,
                    "mutation_text": mutation,
                }
            )
            idx += 1

    if len(rows) < _N_VARIANT:
        raise RuntimeError(
            f"only generated {len(rows)}/{_N_VARIANT} variant rows after "
            f"{max_passes} passes over {len(all_pairs)} pairs "
            f"({refused} MutationRefused, {attempted} attempts)"
        )

    return rows, refused, attempted


def _build_hard_negative_rows(variant_rows: list[dict]) -> list[dict]:
    rows = []
    for i, row in enumerate(variant_rows):
        target = next(t for t in FLEET if t.id == row["target"])
        different = _different_archetype(row["archetype"], i)
        rows.append(
            {
                "target": row["target"],
                "archetype": row["archetype"],  # SAME label as the anchor, verbatim
                "anchor_text": row["anchor_text"],
                "query_text": _local_text(target, different),
            }
        )
    return rows


def _build_cross_target_rows(variant_rows: list[dict]) -> list[dict]:
    rows = []
    for row in variant_rows[:_N_CROSS_TARGET]:
        target = next(t for t in FLEET if t.id == row["target"])
        archetype = next(a for a in ARCHETYPES if a.id == row["archetype"])
        other = _different_target(target, archetype)
        if other is None:
            continue  # not expected given fleet coverage; skip rather than fabricate
        rows.append(
            {
                "target": row["target"],
                "query_target": other.id,
                "archetype": row["archetype"],
                "anchor_text": row["anchor_text"],
                "query_text": row["mutation_text"],  # SAME mutation — only the label changes
            }
        )
    return rows


def _build_easy_negative_rows(variant_rows: list[dict]) -> list[dict]:
    rows = []
    for i, row in enumerate(variant_rows[:_N_EASY_NEGATIVE]):
        rows.append(
            {
                "target": row["target"],
                "archetype": row["archetype"],
                "anchor_text": row["anchor_text"],
                "query_text": _UNRELATED_SNIPPETS[i % len(_UNRELATED_SNIPPETS)],
            }
        )
    return rows


def main() -> None:
    client = genai.Client(**config.gemini_client_kwargs())
    model = config.GEMINI_MODEL

    print(f"Generating {_N_VARIANT} variant rows via real _tailor_one() calls...")
    variant_rows, refused, attempted = _generate_variant_rows(client, model)
    print(f"  {len(variant_rows)} variant rows, {refused} MutationRefused / {attempted} attempts")

    hard_negative_rows = _build_hard_negative_rows(variant_rows)
    cross_target_rows = _build_cross_target_rows(variant_rows)
    easy_negative_rows = _build_easy_negative_rows(variant_rows)

    records: list[dict] = []

    def _emit(cls: str, expected, rows: list[dict]) -> None:
        for i, row in enumerate(rows):
            records.append(
                {
                    "id": f"{cls}-{i:03d}",
                    "class": cls,
                    "anchor_text": row["anchor_text"],
                    "query_text": row["query_text"] if "query_text" in row else row["mutation_text"],
                    "target": row["target"],
                    "query_target": row.get("query_target", row["target"]),
                    "archetype": row["archetype"],
                    "expected_recognize": expected,
                }
            )

    _emit("variant", True, variant_rows)
    _emit("hard_negative", False, hard_negative_rows)
    _emit("cross_target", None, cross_target_rows)
    _emit("easy_negative", False, easy_negative_rows)

    import os

    os.makedirs("data", exist_ok=True)
    with open(_OUT_PATH, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    print(f"\nWrote {len(records)} records to {_OUT_PATH}")
    print(
        f"  variant={len(variant_rows)} hard_negative={len(hard_negative_rows)} "
        f"cross_target={len(cross_target_rows)} easy_negative={len(easy_negative_rows)}"
    )
    print(f"\nMutationRefused: {refused} / {attempted} attempts ({100 * refused / attempted:.1f}%)")


if __name__ == "__main__":
    main()
