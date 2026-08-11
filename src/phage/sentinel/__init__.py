"""SENTINEL — triage.

Public API:
    triage_firing(target_id, payload, session_id, spans, use_llm=True, client=None) -> TriageResult
    triage_fleet_firings(fleet_payloads, fleet_fire_sessions, exporter, use_llm=True, client=None) -> list[TriageResult]

Judges whether a fired payload's injection actually landed, using the
execute_tool spans MARROW's fire-and-capture loop already produces. Two
deterministic pre-filters (NOT_OBSERVABLE, DECLINED) handle the clear-cut
cases with zero LLM calls; Gemma judges the rest; Gemini is escalated to only
when Gemma's signal is genuinely ambiguous. See triage.py's module docstring
for the full design rationale and the two empirical findings it rests on.
"""

from phage.sentinel.triage import (
    Tier,
    TriageResult,
    Verdict,
    decisive_tool_names,
    gemini_judge,
    gemma_judge,
    matching_tool_spans,
    triage_fleet_firings,
    triage_firing,
)

__all__ = [
    "Tier",
    "TriageResult",
    "Verdict",
    "decisive_tool_names",
    "gemini_judge",
    "gemma_judge",
    "matching_tool_spans",
    "triage_fleet_firings",
    "triage_firing",
]
