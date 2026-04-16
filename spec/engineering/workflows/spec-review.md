# Workflow: spec-code coherence review

Verify that code changes trace back to spec changes and vice versa. Do not fix, do not write code, do not propose rewrites.

The rule being enforced is defined in [`../spec-driven.md`](../spec-driven.md). Read it before reviewing.

## How to work

1. Understand the scope of the review from the invoking prompt (usually: a PR, a commit range, a specific file, or "the uncommitted diff").
2. Read the relevant spec files first. Read the changed code files second.
3. For each changed code file, determine:
   - Which spec file(s) authorize this change?
   - Does the code match what the spec describes, or does it go beyond / fall short?
   - Is the change purely non-behavioral (refactor, comment, test, dep bump)?
4. For each changed spec file, determine:
   - Is there matching code for the new/changed behavior?
   - If the spec change is aspirational (intended but not yet coded), is it clearly marked DRAFT?

## What to report

### Coherent changes
List of `(code_change, spec_reference)` pairs where code clearly traces to spec. One line each.

### Potential drift
List of concerns. Each entry:
- **File:line** in code or spec
- **Concern type**: `unspec'd code`, `spec ahead of code`, `code contradicts spec`, `ambiguous spec`
- **Detail**: one sentence. If the spec is silent on a corner case the code handles, call it out — that's not a bug, it's a spec gap.

### No-ops
Changes that are genuinely spec-neutral (pure refactors, dep bumps, test-only). List one line each with reason. This acknowledges them so the operator doesn't waste time re-justifying them.

### Recommendation
One of:
- **Clear to proceed** — no drift found, or drift is acceptable and documented.
- **Minor drift** — a few items to address. List them in priority order.
- **Major drift** — fundamental mismatch. Recommend pausing and realigning spec + code before the change lands.

## Constraints

- Do **not** make edits. You are read-only.
- Do **not** run tests. That's a separate concern.
- Do **not** suggest refactors unrelated to spec-code coherence.
- Do **not** re-review the whole codebase — stay scoped to the change under review.
- Keep the report under 500 words total. Long reviews get skimmed; short reviews get read.

## When uncertain

If a change's spec backing is ambiguous and you can't tell from reading, **ask the operator** which spec sentence authorizes the change. The operator knows. The reviewer is verifying, not guessing.
