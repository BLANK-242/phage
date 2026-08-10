#!/usr/bin/env python3
"""Demonstrate VACCINATOR's templated-mutation engine against the SAIL fleet.

Shows that payload selection and wording are *visibly different per target* —
driven by each agent's declared tool capabilities — and records whether each
payload was Gemini-tailored or produced by the local fallback.

Self-verifying: exits non-zero if the differentiation/tailoring invariants fail.

Usage:
    uv run python scripts/vaccinate_demo.py            # with Gemini tailoring
    uv run python scripts/vaccinate_demo.py --no-gemini  # deterministic, no network
"""

import sys

from phage.vaccinator import classify_scope, generate_payloads, select_archetypes
from phage.vaccinator.archetypes import Capability

# Coopérative SAIL fleet — deliberately different tool scopes (spec Phase 2a).
FLEET = {
    "ORDER-INTAKE": ["create_order(customer, items)", "lookup_customer(email)"],
    "SUPPLIER-RELAY": ["send_email(to, subject, body)", "read_contacts(name)"],
    "STOCK-KEEPER": ["read_inventory(sku)", "adjust_stock(sku, delta)"],
    "QUOTE-BOT": ["read_pricing(sku)", "send_email(to, subject, body)"],
}


def trunc(s: str, n: int = 170) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> int:
    use_gemini = "--no-gemini" not in sys.argv
    print(f"VACCINATOR demo — Gemini tailoring: {'ON' if use_gemini else 'OFF (local only)'}\n")

    per_target: dict[str, list] = {}
    for name, scope in FLEET.items():
        tools = classify_scope(scope)
        caps = sorted({c.value for t in tools for c in t.caps})
        selected = [a.id for a in select_archetypes(scope)]
        payloads = generate_payloads(scope, use_gemini=use_gemini)
        per_target[name] = payloads

        print("=" * 84)
        print(f"TARGET: {name}")
        print(f"  tools        : {', '.join(scope)}")
        print(f"  capabilities : {', '.join(caps)}")
        print(f"  archetypes   : {len(selected)} -> {', '.join(selected)}")
        print("  payloads:")
        for p in payloads:
            tgt = ",".join(p.target_tools) or "-"
            print(f"    [{p.source:14}] {p.archetype_id:26} ({tgt})")
            print(f"        inj : {trunc(p.injection_text)}")
            if p.paraphrase:
                print(f"        alt : {trunc(p.paraphrase)}")
        print()

    # --- differentiation matrix (archetype x target) --------------------------
    all_arch = [a.id for a in __import__("phage.vaccinator", fromlist=["ARCHETYPES"]).ARCHETYPES]
    print("=" * 84)
    print("Differentiation matrix (✓ = archetype applies to that target)\n")
    header = "archetype".ljust(28) + "".join(n[:12].ljust(14) for n in FLEET)
    print(header)
    sel_by_target = {n: {p.archetype_id for p in ps} for n, ps in per_target.items()}
    for aid in all_arch:
        row = aid.ljust(28) + "".join(("  ✓" if aid in sel_by_target[n] else "  ·").ljust(14) for n in FLEET)
        print(row)
    print()

    # --- self-check invariants ------------------------------------------------
    problems = []
    for name, ps in per_target.items():
        if not ps:
            problems.append(f"{name}: no payloads")
        toolnames = [t.split("(")[0] for t in FLEET[name]]
        if not any(any(tn in p.injection_text for tn in toolnames) for p in ps):
            problems.append(f"{name}: no payload references a target tool name")
        for p in ps:
            if not p.injection_text.strip():
                problems.append(f"{name}/{p.archetype_id}: empty injection_text")

    ids = sel_by_target
    # sink-bearing agents get exfiltration but not tool-coercion; mutate-only get the reverse
    if "data-exfiltration" not in ids["SUPPLIER-RELAY"]:
        problems.append("SUPPLIER-RELAY should have data-exfiltration (has a sink)")
    if "tool-coercion" in ids["SUPPLIER-RELAY"]:
        problems.append("SUPPLIER-RELAY should NOT have tool-coercion (no mutate tool)")
    if "tool-coercion" not in ids["STOCK-KEEPER"]:
        problems.append("STOCK-KEEPER should have tool-coercion (has adjust_stock)")
    if "data-exfiltration" in ids["STOCK-KEEPER"]:
        problems.append("STOCK-KEEPER should NOT have data-exfiltration (no external sink)")
    if ids["ORDER-INTAKE"] == ids["QUOTE-BOT"]:
        problems.append("ORDER-INTAKE and QUOTE-BOT should differ (different capabilities)")

    if problems:
        print("SELF-CHECK: FAIL")
        for pr in problems:
            print("  -", pr)
        return 1
    print("SELF-CHECK: PASS — every target got tailored payloads; selection differs per target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
