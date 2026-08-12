"""MACROPHAGE — containment engine.

Revokes the specific tool a landed exploit used from that target's LIVE
tool list, so a subsequent fire against that same target can't use it
again. Process-wide per-target, not session-scoped: MARROW gives every
fire a brand-new session, so a session-scoped block would die before the
next fire that needs protecting -- there's no live turn left in an
already-completed session to contain (build brief's Purpose section,
scope decision already made, not reinterpreted here).

Confirmed from source and an actual captured span before writing the
mutation logic below -- not taken from the build brief (its own explicit
requirement):

1. Does TriageResult.supporting_spans actually name the tool that was
   called? Yes, confirmed by the full chain, not assumed:
     - supporting_spans (triage.py:110) is
       tuple(s.name for s in matching) (triage.py:301), where `matching`
       is matching_tool_spans(spans, decisive) (triage.py:286) and each
       span's .name is f"execute_tool {tool.name}" -- installed source,
       google/adk/telemetry/_instrumentation.py:213
       (`span_name = f"execute_tool {tool.name}"`).
     - Confirmed against REAL captured spans, queried directly out of
       phage_traces.db this session: 'execute_tool send_email',
       'execute_tool read_contacts', 'execute_tool read_inventory',
       'execute_tool adjust_stock', 'execute_tool lookup_customer',
       'execute_tool create_order' -- the literal format matches exactly,
       not just the docstring's claim about it.
     - tool.name for a plain-function tool is set to func.__name__
       verbatim: google/adk/tools/function_tool.py, FunctionTool.__init__,
       `if hasattr(func, '__name__'): name = func.__name__`.
     - Confirmed empirically against a real live target agent this
       session: agents.supplier_relay.agent.root_agent.tools is a plain
       Python list of raw function objects (type 'function', not a
       BaseTool/FunctionTool wrapper -- LlmAgent's own
       _pre_validate_tools model_validator passes plain functions through
       unchanged, google/adk/agents/llm_agent.py; wrapping into
       FunctionTool happens later, fresh, inside canonical_tools(), and
       does not mutate self.tools), and each entry's __name__ matched
       exactly ('read_contacts', 'send_email').
   So stripping the "execute_tool " prefix (13 chars, _SPAN_PREFIX below)
   off a supporting_spans entry yields exactly the string needed to match
   against target_tools[i].__name__ for removal -- no translation gap,
   confirmed end to end, not inferred from either side alone.

   supporting_spans can in principle name more than one DISTINCT tool:
   matching_tool_spans keeps every span matching ANY decisive tool for the
   archetype, not just one. Handled generally below: every distinct tool
   name found gets revoked, not just the first -- leaving a second
   exploited tool live because supporting_spans happened to name it second
   would be an incomplete containment, not a simplification.

2. How does MACROPHAGE reach the real target agent to mutate? Not this
   module's concern by design -- this function takes `target_tools: list`
   (the live list to mutate, e.g. _TARGET_AGENTS[target_id].tools) as a
   plain argument, exactly like triage.py takes `spans: list` rather than
   reaching into ADK/OTel machinery itself. Resolving target_id ->
   the actual live list is the ADK wrapper's job (adk_agent.py) -- see
   that module's docstring for the source-confirmed answer, and why.
"""

from __future__ import annotations

from dataclasses import dataclass

_SPAN_PREFIX = "execute_tool "


def exploited_tool_names(supporting_spans) -> list[str]:
    """Bare tool names (e.g. "send_email") named by a landed verdict's
    supporting_spans (e.g. "execute_tool send_email"). Order-preserving,
    de-duplicated. A span name that doesn't carry the expected prefix is
    skipped rather than mis-parsed -- defensive; every real captured span
    observed this session does carry it (module docstring, point 1)."""
    names: list[str] = []
    for span_name in supporting_spans or []:
        if isinstance(span_name, str) and span_name.startswith(_SPAN_PREFIX):
            name = span_name[len(_SPAN_PREFIX) :]
            if name not in names:
                names.append(name)
    return names


@dataclass(frozen=True)
class ContainmentResult:
    """One firing's containment outcome, with the evidence that produced
    it -- auditable, same spirit as TriageResult (triage.py:99-102)."""

    target_id: str
    verdict: str  # the sentinel.verdict value this decision was made from
    tools_revoked: tuple[str, ...]  # empty if verdict != "landed", or nothing matched/already gone
    reasoning: str


def contain(
    *,
    target_id: str,
    verdict: str,
    supporting_spans,
    target_tools: list,
) -> ContainmentResult:
    """Judge and act on one firing's SENTINEL verdict.

    `target_tools` is the LIVE list backing the real target agent's .tools
    field (e.g. _TARGET_AGENTS[target_id].tools) -- mutated IN PLACE (slice
    assignment, not reassignment) so the caller's own reference keeps
    pointing at the same, now-shorter list; this is what makes the
    revocation process-wide rather than local to this call.

    Idempotent per the build brief's explicit requirement: a tool already
    absent from target_tools (e.g. a second landed verdict against the
    same target via a different archetype that used the same tool) is
    simply not found on this pass -- not an error, not double-counted in
    tools_revoked.

    On any verdict other than "landed": no-op, tools_revoked=() -- does
    NOT write a misleading "contained" result for a target that wasn't
    landed (build brief, Scope). No tiered response by verdict severity --
    ambiguous/declined/not_observable are all the same no-op, on purpose
    (build brief, Explicitly out of scope).
    """
    if verdict != "landed":
        return ContainmentResult(
            target_id=target_id,
            verdict=verdict,
            tools_revoked=(),
            reasoning=f"verdict={verdict!r}, not 'landed' — no-op.",
        )

    names = exploited_tool_names(supporting_spans)
    if not names:
        return ContainmentResult(
            target_id=target_id,
            verdict=verdict,
            tools_revoked=(),
            reasoning=(
                "verdict=landed but supporting_spans named no tool — "
                "nothing to revoke."
            ),
        )

    revoked: list[str] = []
    for name in names:
        before = len(target_tools)
        target_tools[:] = [
            t for t in target_tools if getattr(t, "__name__", None) != name
        ]
        if len(target_tools) < before:
            revoked.append(name)
        # else: already absent — idempotent no-op for this name, not an
        # error (e.g. a prior landed verdict against this same target
        # already revoked it).

    return ContainmentResult(
        target_id=target_id,
        verdict=verdict,
        tools_revoked=tuple(revoked),
        reasoning=(
            f"revoked {revoked!r} from target_id={target_id!r}'s live tool list"
            if revoked
            else f"exploited tool(s) {names!r} already absent — idempotent no-op"
        ),
    )
