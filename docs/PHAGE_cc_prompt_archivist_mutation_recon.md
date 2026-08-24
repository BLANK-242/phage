# PHAGE — ARCHIVIST Mutation-Transform Recon (read-only)

> **Build-history record.** Written during construction and left unedited.
> Figures and `file:line` citations here may be superseded. `docs/writeup.md`
> and `README.md` are the current, audited statements.

## Purpose

Session 4 decided ARCHIVIST owns the deterministic mutation step, because
Gemini's paraphrase field proved unreliable for it. Before building
anything, locate where VACCINATOR's payload generation actually lives
and where a mutation step would insert — don't assume the hook point.

**No code writes this pass. Recon only — every finding cited file:line.**

## What to inspect

1. **VACCINATOR's payload-generation code.** Likely under
   `src/phage/vaccinator/`, following the pattern `marrow/`, `sentinel/`,
   and `macrophage/` all use — but confirm the actual path rather than
   assuming it from this brief.
2. **The historical unreliable-paraphrase call.** Locate the actual code
   path where Gemini's paraphrase field was called, even if it's now
   dead or unused, and what it actually returned when it was unreliable
   (Session 4's own finding) — understand the shape of the problem
   ARCHIVIST is replacing, not just the fact that it was replaced.
3. **The payload data structure at the point mutation would apply.** Is
   there a single, localized field (e.g. one "injected instruction"
   string) where swapping in an alternate framing would be a clean,
   contained change — or does mutation touch more of the payload's
   structure than that?
4. **Where a small library of framing templates would naturally live**
   (direct-command, authority-override, fake-tool-output-style framings
   of the same underlying instruction) — following whatever pattern this
   codebase already uses for similar fixed catalogs, e.g. how
   `targets.py`'s `FLEET` registry or SENTINEL's tier logic organize
   structured, deterministic content.

## Output format

- File:line citations for VACCINATOR's actual generation code and the
  historical paraphrase call.
- A plain answer on where the mutation hook would go and how invasive
  the change would be — touches one field vs. touches the payload
  structure broadly.
- No code, no template library contents. That's the build's job, not
  this recon's.
