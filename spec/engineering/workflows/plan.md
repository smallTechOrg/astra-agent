# Workflow: draft a plan

Per Boris's "always start with plan mode" tip, every non-trivial multi-file change gets a written plan in [`reports/`](../../../reports/) before any edits land. Solo prompts of the "add a line here" shape do not need this.

## When to plan

- Any change that touches **three or more files**.
- Any change that touches **both spec/ and src/** in the same session.
- Any change that introduces a new capability, abstraction, or schema field.
- Any refactor whose scope is not a single function.

## Plan structure

Write `reports/<YYYY-MM-DD>-<slug>.md` with these sections, in order:

1. **Goal** — one or two sentences. What we're changing, why now.
2. **Spec impact** — which `spec/product/` files need edits? Draft the deltas inline.
3. **Engineering impact** — any rule in `spec/engineering/` affected? Usually no. If yes, flag.
4. **Phases** — numbered, each phase gated by a verifiable test. Example:
   - Phase 1: add DB column + migration; test: migration runs clean on empty + populated DB.
   - Phase 2: wire the column through the domain model; test: unit tests for new field.
   - Phase 3: surface in CLI + config; test: end-to-end `astra ...` invocation.
5. **Out of scope** — explicit non-goals to prevent scope creep during execution.
6. **Risks** — what could break, and how we'll know.

## Procedure

1. Read the relevant product spec files first. If any needed spec doesn't exist, draft it before writing the plan.
2. Interview the user for ambiguities. Use AskUserQuestion when you can — one question at a time is slower; bundle.
3. Write the plan. Keep it terse; a good plan is scannable in under a minute.
4. Save to [`reports/`](../../../reports/) with today's date.
5. Return the path. Do **not** start implementing. The user approves first; then a separate session (or the same, post-approval) executes.

## Constraints

- Do not write code in the plan. Code references (class name, file path) are fine; actual function bodies are not.
- Do not commit to a library or framework choice the spec doesn't already name. If you must, surface as a decision in the plan.
- Do not mark the plan "done" when it's written — it's done when the user approves.
