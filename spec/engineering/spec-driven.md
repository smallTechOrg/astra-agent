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

## Anti-patterns

- **Writing code first, updating the spec "to match" after.** This defeats the entire workflow. The spec becomes a post-hoc rationalization of whatever the code happens to do.
- **"I'll spec it later."** No. The spec change is part of the same commit, or a prior commit, not a later one.
- **Making small "obvious" changes without spec updates.** Behavioral changes are never obvious to the next reader. If the change is genuinely spec-neutral (refactor, rename, internal cleanup), no spec update is needed — but verify this is the case before skipping the spec step.

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
