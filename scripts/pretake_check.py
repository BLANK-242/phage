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

Finally, probes both inference models live, so a 404 or a quota wall is
caught here rather than discovered in playback. The probe deliberately
reuses SENTINEL's exact client construction and call path — a probe that
built its own client or called generate_content directly would prove
nothing about the path the take actually runs:

  - client:  genai.Client(**config.gemini_client_kwargs())
             (src/phage/sentinel/triage.py:321, :370)
  - call:    llm.generate_with_backoff(client, model=..., contents=...,
             config=types.GenerateContentConfig(...))
             (triage.py:189 for Gemma, :230 for Gemini)

The probe is read-only with respect to Memory Bank: it issues no memory
call of any kind and never touches a scope.

Exit code: 0 if both model probes PASS, 1 if either FAILs. The scope purge
and verification above are unchanged, including their reporting — this
script had no exit-code convention before (main() returned None and was
called bare, so it always exited 0); the non-zero exit added here is scoped
to model-probe failure only.
"""

from __future__ import annotations

from google.genai import types

from phage import config
from phage.archivist.memory import _client, _engine_name, _scope
from phage.llm import generate_with_backoff

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


def _probe_model(genai_client, model: str, max_output_tokens: int) -> bool:
    """Prove one model actually answers. PASS only on non-empty text back.

    An exception, an empty string, or a None .text is a FAIL — a model that
    returns nothing is as useless to a take as one that 404s.

    max_output_tokens mirrors SENTINEL's own per-tier value (16 for Gemma at
    triage.py:189, 128 for Gemini at :230) rather than a smaller invented
    number: gemini-3.5-flash can spend the whole budget on thinking tokens
    and hand back empty text, which would be a false FAIL here.
    """
    cfg = types.GenerateContentConfig(
        temperature=0.0, max_output_tokens=max_output_tokens
    )
    try:
        resp = generate_with_backoff(
            genai_client, model=model, contents="Reply with the single word: OK", config=cfg
        )
        text = (getattr(resp, "text", None) or "").strip()
    except Exception as exc:  # noqa: BLE001 -- any failure is a FAIL, reported honestly
        print(f"  {model}: FAIL — {type(exc).__name__}: {exc}")
        return False
    if not text:
        print(f"  {model}: FAIL — empty response (no text returned)")
        return False
    print(f"  {model}: PASS — {text!r}")
    return True


def probe_models() -> bool:
    """Probe both inference tiers. Issues no Memory Bank call of any kind."""
    print("\n=== model reachability ===")
    from google import genai

    genai_client = genai.Client(**config.gemini_client_kwargs())
    gemini_ok = _probe_model(genai_client, config.GEMINI_MODEL, 128)
    gemma_ok = _probe_model(genai_client, config.GEMMA_MODEL, 16)
    return gemini_ok and gemma_ok


def main() -> int:
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

    # Model probes run LAST, after the purge and its verification, so nothing
    # above can be skipped or short-circuited by a probe outcome.
    models_ok = probe_models()
    if not models_ok:
        print(
            "\nMODEL PROBE FAILED — DO NOT PROCEED WITH THE TAKE. "
            "At least one model did not answer; recording now would burn a "
            "take on a 404 or a quota wall."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
