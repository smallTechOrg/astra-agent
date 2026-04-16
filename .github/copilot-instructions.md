# GitHub Copilot entry point

You are working in a spec-driven repo. Behaviour is defined in [`spec/product/`](../spec/product/); engineering rules are in [`spec/engineering/`](../spec/engineering/). Read [`spec/README.md`](../spec/README.md) for orientation.

When generating code, cite the spec file that authorises the behaviour (e.g. "per `spec/product/04-capabilities/linkedin-distribution.md`"). When suggesting a behavioural change, propose the spec edit first as a separate diff.

## Scoped instructions

Files in [`instructions/`](instructions/) auto-apply to matching paths via their `applyTo` frontmatter. Each is a thin pointer to the canonical rule in [`spec/engineering/`](../spec/engineering/).

## Cross-tool note

This repo is also configured for Claude Code via [`CLAUDE.md`](../CLAUDE.md) at repo root. Canonical rules are shared — change them in [`spec/engineering/`](../spec/engineering/), never here.
