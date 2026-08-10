"""VACCINATOR — tailored prompt-injection payload synthesis.

Public API:
    generate_payloads(tool_scope, client=None, use_gemini=True) -> list[Payload]

The engine is a templated-mutation design (see docs / Phase 1.5b diagnostic):
a curated library of injection *archetypes* is deterministically instantiated
against a target's declared tool scope, and Gemini is used only to
parameterize/paraphrase those instantiations via a structured register. If the
model declines or a call fails, local instantiation still produces a valid,
tool-specific payload. Nothing is authored from scratch by the model.
"""

from phage.vaccinator.archetypes import (
    ARCHETYPES,
    Archetype,
    Capability,
    Tool,
    classify_tool,
)
from phage.vaccinator.engine import (
    Payload,
    classify_scope,
    generate_payloads,
    select_archetypes,
)

__all__ = [
    "ARCHETYPES",
    "Archetype",
    "Capability",
    "Tool",
    "classify_tool",
    "Payload",
    "classify_scope",
    "select_archetypes",
    "generate_payloads",
]
