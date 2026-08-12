"""MACROPHAGE — containment.

Public API:
    contain(*, target_id, verdict, supporting_spans, target_tools) -> ContainmentResult
    exploited_tool_names(supporting_spans) -> list[str]

On a SENTINEL verdict of "landed", revokes whichever tool(s) the landed
firing's supporting_spans name from the target's LIVE tool list —
process-wide, for the rest of the run (not session-scoped — MARROW gives
every fire a brand-new session, so nothing session-scoped would still be
alive by the next fire that needs protecting). See containment.py's module
docstring for the full design rationale and the source citations it rests
on.
"""

from phage.macrophage.containment import (
    ContainmentResult,
    contain,
    exploited_tool_names,
)

__all__ = [
    "ContainmentResult",
    "contain",
    "exploited_tool_names",
]
