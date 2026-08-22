"""Pre-take Memory Bank scope check.

Run before every demo take (docs/demo_script.md's pre-take procedure), and
this brief's Preflight (docs/PHAGE_cc_prompt_demo_script.md). If a
signature matching the demo payload is sitting in the PRODUCTION scope
when scene 1 rolls, recognition fires on the first exposure and the whole
two-scene spine collapses.

Retrieves and prints everything in the production scope
({"app_name": "phage-archivist"}), deletes it, and verifies 0 results.
Then checks every eval scope this project has ever used and reports its
count — 0 expected everywhere (each eval script cleans up after itself;
this is a belt-and-suspenders check before a take, not a fix for a
script that failed to clean up).
"""

from __future__ import annotations

from phage.archivist.memory import _client, _engine_name, _scope

_EVAL_SCOPES = [
    {"app_name": "phage-eval"},
    {"app_name": "phage-eval-f0"},
    {"app_name": "phage-eval-f1"},
    {"app_name": "phage-eval-f2"},
    {"app_name": "phage-eval-f3"},
    {"app_name": "phage-eval-loao-verify"},
    {"app_name": "phage-eval-loao-data-exfiltration"},
    {"app_name": "phage-eval-loao-indirect-injection"},
    {"app_name": "phage-eval-loao-indirect-injection-readonly"},
    {"app_name": "phage-eval-loao-instruction-override"},
    {"app_name": "phage-eval-loao-obfuscation-encoding"},
    {"app_name": "phage-eval-loao-persona-maintenance-mode"},
    {"app_name": "phage-eval-loao-scope-escalation"},
    {"app_name": "phage-eval-loao-tool-coercion"},
]


def _list_scope(client, scope: dict[str, str]) -> list:
    res = client.agent_engines.memories.retrieve(
        name=_engine_name(), scope=scope, simple_retrieval_params={"page_size": 100}
    )
    return list(res)


def main() -> None:
    client = _client()
    prod_scope = _scope()
    print(f"=== PRODUCTION scope {prod_scope} ===")
    items = _list_scope(client, prod_scope)
    print(f"found {len(items)} memories")
    for rm in items:
        m = getattr(rm, "memory", None)
        if m is not None:
            print(f"  {m.name}: fact={m.fact!r}")

    if items:
        print(f"Deleting {len(items)} production memories...")
        for rm in items:
            m = getattr(rm, "memory", None)
            if m is not None:
                client.agent_engines.memories.delete(name=m.name)
        remaining = _list_scope(client, prod_scope)
        print(f"post-delete count: {len(remaining)} (expect 0)")
    else:
        print("production scope already empty — no delete needed")

    print("\n=== eval scopes ===")
    all_clean = True
    for scope in _EVAL_SCOPES:
        scope_items = _list_scope(client, scope)
        status = "OK" if not scope_items else "CONTAMINATED"
        if scope_items:
            all_clean = False
        print(f"  {scope}: {len(scope_items)} results [{status}]")

    print(f"\nAll eval scopes clean: {all_clean}")


if __name__ == "__main__":
    main()
