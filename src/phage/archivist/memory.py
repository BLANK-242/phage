"""ARCHIVIST — semantic signature memory via Vertex AI Memory Bank.

Two operations, both plain functions (no ADK BaseAgent wrapper — MARROW calls
these directly, in-process, per the build brief's Task 3: "MARROW holds no
domain logic. It calls ARCHIVIST and routes the result; the decision logic
lives in ARCHIVIST"):

    recognize(...)  — pre-fire gate: does this payload match a previously
                       recorded LANDED encounter for this target?
    record(...)     — post-triage write: store this encounter's signature,
                       but only on a landed verdict, and only once.

Call signatures for create/retrieve/delete were live-verified against
`agentplatform.Client(...).agent_engines.memories` during the memory recon
(docs/PHAGE_cc_prompt_archivist_memory_recon.md) — re-confirmed fresh from
the installed source at build time, not reconstructed from memory:
  - create:  .venv/lib/python3.12/site-packages/agentplatform/_genai/memories.py:1636-1643
  - retrieve: same file, :1777-1789
  - delete:   same file, :647-652
  - distance field: agentplatform/_genai/types/common.py:11778-11781 —
    "Smaller values indicate more similar memories" (a DISTANCE, the inverse
    direction from a similarity-above-threshold framing — see
    RECOGNITION_DISTANCE_THRESHOLD below).

Memory Bank embeds server-side from a plain `fact` string — there is no
caller-supplied-vector path anywhere in this API (confirmed by reading the
`Memory` proto message field-by-field in the recon). So "the vector" the
master spec describes is never something this module touches directly; what
this module owns is the TEXT that gets embedded, which is why 3.1's
single-shared-function constraint on that text is load-bearing, not
cosmetic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from phage import config

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Threshold — one constant, one place (build brief 3.2). Do not inline this
# value anywhere else in the codebase.
# --------------------------------------------------------------------------- #
RECOGNITION_DISTANCE_THRESHOLD = 0.59  # Tuned against data/recognition_pairs.jsonl
                                       # (scripts/tune_threshold.py, docs/PHAGE_cc_prompt_
                                       # archivist_dataset.md Task 3). variant and
                                       # hard_negative overlap (hard_negative min 0.4101 <
                                       # variant min 0.4257) — NOT cleanly separable, so this
                                       # is the min-FPR threshold subject to TPR>=0.95:
                                       # TPR=1.00, FPR=0.72 on n=25/25. That FPR is real and
                                       # high; see this brief's report for why it points at
                                       # the signature-text format, not just the number.
                                       # Single source of truth: do not inline elsewhere.

# Comparison is STRICTLY `distance < RECOGNITION_DISTANCE_THRESHOLD` — a
# result exactly at the threshold is a MISS. Do not invert this to `>`; the
# field is a distance (smaller = closer), not a similarity score.

_SCOPE_APP_NAME = "phage-archivist"  # Memory Bank `scope.app_name` — this module's
                                      # own namespace, separate from any other
                                      # Memory Bank consumer.

# Single fleet-wide scope, not per-target: recognition is meant to work
# across the fleet ("the fleet learned this attack"), not per-organism. The
# target id still distinguishes encounters — it lives inside the signature
# fact text (_signature_text below), not in the scope.
_FLEET_SCOPE: dict[str, str] = {"app_name": _SCOPE_APP_NAME}


@dataclass(frozen=True)
class RecognitionResult:
    """recognize()'s return — matches the frozen-result-type convention every
    other agent in this codebase already uses (Payload, TriageResult,
    ContainmentResult)."""

    recognized: bool
    distance: Optional[float]
    matched_fact: Optional[str]
    matched_memory_name: Optional[str]
    error: Optional[str] = None  # "{ExceptionClassName}: {message}" on the fail-open
                                  # path below; None on every other path, including a
                                  # clean miss — this is specifically "did the client
                                  # call itself fail", not "was nothing recognized".


_MISS = RecognitionResult(
    recognized=False, distance=None, matched_fact=None, matched_memory_name=None
)


# --------------------------------------------------------------------------- #
# Shared signature-text construction (build brief 3.1 — the non-obvious
# constraint). Memory Bank embeds server-side from this string both at write
# time (record's `fact`) and at query time (recognize's `search_query`); any
# asymmetry between the two construction paths poisons every distance the
# demo puts on screen. Exactly one function; both record() and recognize()
# call it. Do not build either string inline.
#
# Parameterised over format (docs/PHAGE_cc_prompt_signature_format_ab.md
# Task 1) after F0's shared target=/archetype=/tools= boilerplate was found
# to dominate the embedding (FPR 0.72 at TPR 1.00 — see
# RECOGNITION_DISTANCE_THRESHOLD's history). format_id is required, not
# defaulted here, so no call site can silently drift onto an implicit
# format — record()/recognize() pass _SIGNATURE_FORMAT explicitly below;
# scripts A/B-testing formats pass an explicit F0-F3 literal instead.
# --------------------------------------------------------------------------- #
_SIGNATURE_FORMAT = "F0"  # Production default. Task-3-changeable single source of
                          # truth: record()/recognize() read this constant live (by
                          # name, each call) rather than relying on a baked-in
                          # function-default value, so changing this line alone
                          # changes production behaviour with no other edit needed.

_SIGNATURE_FORMATS = ("F0", "F1", "F2", "F3")  # the only valid format_id values


def _signature_text(
    *,
    target_id: str,
    archetype_id: str,
    target_tools: Sequence[str],
    injection_text: str,
    format_id: str,
) -> str:
    """Builds the exact string Memory Bank embeds. format_id selects how much
    of the target/archetype/tools context is embedded alongside the
    injection text (see the format table in
    docs/PHAGE_cc_prompt_signature_format_ab.md):

        F0 - target= + archetype= + tools=[...] prefix, then injection text
        F1 - injection text only, no prefix of any kind
        F2 - archetype= prefix only, then injection text
        F3 - tools=[...] prefix only, then injection text
    """
    tools = ", ".join(target_tools)
    if format_id == "F0":
        return f"target={target_id} archetype={archetype_id} tools=[{tools}]\n{injection_text}"
    if format_id == "F1":
        return injection_text
    if format_id == "F2":
        return f"archetype={archetype_id}\n{injection_text}"
    if format_id == "F3":
        return f"tools=[{tools}]\n{injection_text}"
    raise ValueError(f"unknown signature format {format_id!r}; must be one of {_SIGNATURE_FORMATS}")


def _scope() -> dict[str, str]:
    return dict(_FLEET_SCOPE)  # fresh dict per call, same as before this was fixed


def _engine_name() -> str:
    # Short form, exactly as ADK's own VertexAiMemoryBankService and the
    # memory recon's live-verified round trip both use — NOT
    # config.AGENT_ENGINE_RESOURCE (the fully-qualified projects/.../
    # locations/... form is a different, longer string this API does not
    # take as `name`).
    return f"reasoningEngines/{config.AGENT_ENGINE_ID}"


def _client():
    import agentplatform

    return agentplatform.Client(project=config.PROJECT_ID, location=config.INFRA_LOCATION)


# --------------------------------------------------------------------------- #
# 3.3 — recognize()
# --------------------------------------------------------------------------- #
def recognize(
    *,
    target_id: str,
    archetype_id: str,
    target_tools: Sequence[str],
    injection_text: str,
    top_k: int = 3,
    client=None,
) -> RecognitionResult:
    """Pre-fire recognition gate.

    Fails open: any client exception is logged as a warning and treated as a
    miss, never raised. A recognition subsystem that raises would kill
    MARROW's fire loop, and a false block (withholding a real attack from
    ever being tested because Memory Bank hiccuped) is worse than a missed
    recognition — the demo depends on the loop completing. The exception is
    not just discarded, though: it is captured into the returned result's
    `error` field ("{ExceptionClassName}: {message}") so a caller can tell
    "the client call itself failed" apart from "nothing matched" — every
    other path (clean miss, no-distance result) leaves `error=None`.

    If a returned result has no `distance` field, that is treated as a miss
    rather than assuming a value (a similarity search with no configured
    embedding path could in principle return an un-scored result).
    """
    text = _signature_text(
        target_id=target_id,
        archetype_id=archetype_id,
        target_tools=target_tools,
        injection_text=injection_text,
        format_id=_SIGNATURE_FORMAT,
    )
    resolved_client = client if client is not None else _client()

    try:
        results = resolved_client.agent_engines.memories.retrieve(
            name=_engine_name(),
            scope=_scope(),
            similarity_search_params={"search_query": text, "top_k": top_k},
        )
        nearest = next(iter(results), None)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "ARCHIVIST.recognize: Memory Bank call failed for target=%r archetype=%r: %s"
            " — failing open (recognized=False)",
            target_id,
            archetype_id,
            error,
            exc_info=True,
        )
        return RecognitionResult(
            recognized=False, distance=None, matched_fact=None, matched_memory_name=None,
            error=error,
        )

    if nearest is None:
        return _MISS

    distance = getattr(nearest, "distance", None)
    if distance is None:
        return _MISS

    memory = getattr(nearest, "memory", None)
    fact = getattr(memory, "fact", None) if memory is not None else None
    mem_name = getattr(memory, "name", None) if memory is not None else None

    return RecognitionResult(
        recognized=distance < RECOGNITION_DISTANCE_THRESHOLD,
        distance=distance,
        matched_fact=fact,
        matched_memory_name=mem_name,
    )


# --------------------------------------------------------------------------- #
# 3.4 — record()
# --------------------------------------------------------------------------- #
_LANDED_VERDICT = "landed"  # matches Verdict.LANDED.value (sentinel/triage.py) —
                            # compared as a plain string because that is the shape
                            # a verdict already has by the time it reaches here
                            # (sentinel/adk_agent.py's _serialize_result sets
                            # "verdict": r.verdict.value, and it travels through
                            # JSON-friendly session state from there).

_DEDUP_PAGE_SIZE = 100  # generous relative to this codebase's realistic FLEET-WIDE
                        # encounter count (4 targets x 8 archetypes max today = 32,
                        # scope is fleet-wide as of the scope change below); a single
                        # page comfortably covers it without needing pagination logic.


def record(
    *,
    target_id: str,
    archetype_id: str,
    target_tools: Sequence[str],
    injection_text: str,
    verdict: str,
    client=None,
) -> Optional[str]:
    """Writes this encounter's signature to Memory Bank — but only on a
    `landed` verdict, and only once.

    No-op (returns None) on any other verdict — MARROW calls this
    unconditionally after every triage and lets this check decide, per
    "MARROW holds no domain logic."

    Idempotent: checked via an exact-text match against existing memories in
    the fleet-wide scope before writing (a `simple_retrieval_params` listing,
    not similarity search — this needs an EXACT match, not a nearest
    neighbor). Exact match on the full signature text — which embeds
    target_id — is still specific to one target/archetype/tool combination
    even though the scope itself is no longer per-target. An identical
    signature returns the existing memory's name rather than creating a
    duplicate.

    Does not fail open — unlike recognize(), a Memory Bank failure here is a
    distinct fact from a triage or containment failure and is left to
    propagate so MARROW's own per-payload try/except (matching how it
    already isolates fire/triage/containment failures) reports it as what it
    is, rather than this function absorbing it silently.
    """
    if verdict != _LANDED_VERDICT:
        return None

    text = _signature_text(
        target_id=target_id,
        archetype_id=archetype_id,
        target_tools=target_tools,
        injection_text=injection_text,
        format_id=_SIGNATURE_FORMAT,
    )
    resolved_client = client if client is not None else _client()
    name = _engine_name()
    scope = _scope()

    existing = resolved_client.agent_engines.memories.retrieve(
        name=name,
        scope=scope,
        simple_retrieval_params={"page_size": _DEDUP_PAGE_SIZE},
    )
    for rm in existing:
        memory = getattr(rm, "memory", None)
        if memory is not None and getattr(memory, "fact", None) == text:
            return memory.name

    operation = resolved_client.agent_engines.memories.create(
        name=name,
        fact=text,
        scope=scope,
        config={"wait_for_completion": True},
    )
    response = getattr(operation, "response", None)
    return getattr(response, "name", None) if response is not None else None
