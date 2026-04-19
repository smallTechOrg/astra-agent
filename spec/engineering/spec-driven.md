# Rule: spec-driven development

**Scope:** applies everywhere, always.

## The rule

> **Change the spec first. Then change the code to match. Never the reverse.**

The [`../product/`](../product/) tree is the source of truth for what Astra does. Code is a mechanical translation. When the two disagree, the spec is correct and the code is a bug.

## What this means in practice

### When the user asks for a new feature
1. Draft or update the relevant [`../product/04-capabilities/`](../product/04-capabilities/) file using the [capability template](../README.md#capability-template).
2. If the change affects config, update [`../product/05-config.md`](../product/05-config.md). If it affects the CLI, update [`../product/06-cli.md`](../product/06-cli.md). Etc.
3. Get alignment from the user on the spec.
4. **Then** write the code.

### When the user asks to fix a bug
1. Determine whether the bug is "code doesn't match spec" or "spec itself is wrong."
2. If the spec is wrong, update it first.
3. Fix the code to match.

### When you notice code doing something the spec doesn't describe
- Stop. Either the spec is missing a rule (update it) or the code shouldn't exist (remove it).
- Do not add commentary or docstrings to explain undocumented behavior. The spec is the documentation.

### When you notice the spec describes something the code doesn't do
- This is drift. Surface it to the user.
- Either the spec is aspirational (mark it as DRAFT or remove) or the code is incomplete (add to a todo list).

## Feasibility gate

> **No capability spec may proceed to implementation without a documented feasibility assessment.**

Every capability spec that depends on an external platform, paid API, or third-party approval process **must** include a `## Feasibility` section that answers:

1. **API access model.** Is write access free, paid, or gated behind an approval process? What tier is required? What does it cost as of the spec date?
2. **Approval lead time.** Does the platform require an app review, partner agreement, or manual approval? How long does it take? Is it per-app or per-tenant?
3. **Rate limits and quotas.** What are the published limits for the required tier? Are they sufficient for the planned usage pattern?
4. **Terms of Service risks.** Does the intended use (automated posting via an agent) comply with the platform's ToS and developer agreement? Are there anti-automation clauses?
5. **Alternatives if blocked.** If the primary API path is too expensive or too slow to approve, what are the fallback options? Are there free-tier platforms that serve the same audience?

A capability whose feasibility section shows a hard blocker (e.g. minimum $200/month API cost for a product that targets free/cheap operation, or 30-day approval lead time with no workaround) **must not** proceed to implementation. It should be marked `Status: BLOCKED` with the reason, and the spec should document what would unblock it.

**This rule exists because building code against an API you cannot actually call is wasted work.** The spec-driven process is only valuable if the spec reflects reality, not aspirations.

## Anti-patterns

- **Writing code first, updating the spec "to match" after.** This defeats the entire workflow. The spec becomes a post-hoc rationalization of whatever the code happens to do.
- **"I'll spec it later."** No. The spec change is part of the same commit, or a prior commit, not a later one.
- **Making small "obvious" changes without spec updates.** Behavioral changes are never obvious to the next reader. If the change is genuinely spec-neutral (refactor, rename, internal cleanup), no spec update is needed — but verify this is the case before skipping the spec step.
- **Speccing against an API you haven't verified.** If a capability requires a third-party API, the spec author must verify access requirements (cost, tier, approval process) before writing the behavior section. "It probably has a free API" is not verification.

## README

`README.md` is the public entry point to the repo. It must stay accurate.

Any change that affects **install steps, config layout, CLI commands, quick-start workflow, or architectural assumptions described in `README.md`** requires a README update in the same PR. Treat a stale README the same as a stale spec — it is a bug.

The README is *not* a spec. It summarises the specs for newcomers. When in doubt, keep it short and link to the canonical spec file.

## Exceptions

The only changes that don't require spec updates:
- Pure refactors with identical observable behavior.
- Dependency bumps that don't change API surface.
- Bug fixes where the code already fails to do what the spec says (the spec was already correct).
- Test additions/improvements (tests validate the spec; they don't define it).

Formatting, naming, and internal structure are not spec'd and don't need spec changes.

## How this rule interacts with tools

- **Claude Code**: if a user asks for a change, the first tool call should typically be to read the relevant spec file(s).
- **GitHub Copilot**: when generating code, reference the spec filename that authorizes the behavior (e.g. "per `spec/product/04-capabilities/linkedin-distribution.md`").
- Both tools: when proposing a change that affects observable behavior, propose the spec edit first as its own diff.
