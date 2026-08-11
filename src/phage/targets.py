"""SAIL fleet target registry — declared tool scopes VACCINATOR tailors against.

Kept out of config.py deliberately: config.py is environment/runtime
configuration (region split, GEMINI_MODEL); this is fleet DATA that SENTINEL,
MACROPHAGE, and ARCHIVIST will all need to reference later (attribution,
containment scoping, per-target signature history). A separate module avoids a
forced refactor when those three agents get built.

tool_scope values are sourced from the same canonical fleet declaration
MARROW's original single-target seed used: scripts/vaccinate_demo.py:21-26
("Coopérative SAIL fleet — deliberately different tool scopes (spec Phase
2a)"). Not re-derived or invented here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Target:
    id: str
    tool_scope: list[str]


FLEET: list[Target] = [
    Target(
        id="SUPPLIER-RELAY",
        tool_scope=["send_email(to, subject, body)", "read_contacts(name)"],
    ),
    Target(
        id="QUOTE-BOT",
        tool_scope=["read_pricing(sku)", "send_email(to, subject, body)"],
    ),
    Target(
        id="ORDER-INTAKE",
        tool_scope=["create_order(customer, items)", "lookup_customer(email)"],
    ),
    Target(
        id="STOCK-KEEPER",
        tool_scope=["read_inventory(sku)", "adjust_stock(sku, delta)"],
    ),
]
