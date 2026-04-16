# Workflow: DRY audit

Find places where the same fact is stated in more than one file, in violation of the repo's golden rule: every fact lives in exactly one canonical file; every other mention is a link.

## Scope

Audit these trees: [`../../`](../../) (spec), [`../../../`](../../../) root files (README.md, CLAUDE.md, .github/, .claude/). Do **not** read `src/` or `tests/` — DRY for code is a separate concern.

## Procedure

1. **Enumerate candidate facts.** Patterns that tend to duplicate:
   - Product identity ("Astra is…", "distribution agent for…")
   - Architectural facts (the four abstractions, tenant_id scoping)
   - Library/tooling choices (canonical lib list, pydantic settings)
   - Rule summaries (spec-first, secret hygiene, commit norms)
   - Path/location facts (where secrets live, where plans live)
   - Template structures (capability template)

2. **For each candidate, grep the repo.** Count occurrences outside the declared canonical home. A paraphrase counts — if two files make the same claim, the shorter one should be a link.

3. **Classify each hit:**
   - ✅ **Link** — mentions the fact but links to the canonical home. Fine.
   - ❌ **Restatement** — states the fact in its own words, no link. Violation.
   - ⚠️ **Drift risk** — partial restatement that adds detail; canonical home may need to absorb it, or this file may need to shrink.

4. **Cross-check canonical mapping.** Confirm each fact's declared home still matches where it actually lives. If a rule was moved but the "canonical home" reference in another file points at the old path, flag it.

## Report format

```
| Fact | Canonical home | Violations | Recommendation |
|---|---|---|---|
| "Astra distributes manually-authored posts" | spec/product/01-vision.md | README.md:3 (restatement), CLAUDE.md:5 (paraphrase) | Replace with links |
| four abstractions | spec/product/02-architecture.md | spec/engineering/code-style.md:12 (restatement) | Delete the enumeration, link |
```

End with a one-line summary: violation count, worst offender file.

## Constraints

- Read-only. Do not edit.
- Do not flag the canonical home itself as a "duplicate" of itself.
- Do not flag literal identical link text across files — that's the point of canonical mapping.
- Keep report under 400 words.
