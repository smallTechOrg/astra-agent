# Claude Code entry point

You are working in a spec-driven repo. Read [`spec/README.md`](spec/README.md) every session — it orients you to the product spec ([`spec/product/`](spec/product/)) and the engineering rules ([`spec/engineering/`](spec/engineering/)).

Do not skip it. Do not restate or summarise — link to it.

## Claude-Code-only mechanics

These are mechanics specific to this tool; they are not policy. Policy lives in [`spec/engineering/`](spec/engineering/).

- **Permissions, hooks, env**: [`.claude/settings.json`](.claude/settings.json).
- **Slash commands**: [`.claude/commands/`](.claude/commands/).
- **Subagents**: [`.claude/agents/`](.claude/agents/).
- **Plans directory**: `./reports/` (per `settings.json`).
- **Auto-compact**: triggers at 75% (per `settings.json`). Manually `/compact` earlier if mid-refactor.

## Workflow

- For multi-file work, draft a plan in [`reports/`](reports/) before editing.
- For new capabilities, scaffold with `/spec-new-capability` and have `spec-reviewer` audit before code lands.
- Do not create new commands or agents without the user asking.

## Cross-tool note

This repo is also configured for GitHub Copilot via [`.github/copilot-instructions.md`](.github/copilot-instructions.md). Both tools read the same canonical rules at [`spec/engineering/`](spec/engineering/) — change rules **there**, never in tool-specific files.
