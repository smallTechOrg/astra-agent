# Workflow: scaffold a new capability spec

Create a new capability spec file at `spec/product/04-capabilities/<slug>.md` following the template defined in [`../../README.md`](../../README.md#capability-template). That template's section headings are the contract — use them verbatim.

## Procedure

1. If no slug argument was provided, ask the user for:
   - The capability slug (lowercase-kebab-case, e.g. `mastodon-distribution`, `rss-publish-detection`)
   - The one-sentence purpose
   - The component name (e.g. `MastodonDestination`)
   - Which abstraction it implements (per [`../../product/02-architecture.md`](../../product/02-architecture.md))
   - The trigger type (scheduled cron / event-driven / manual CLI)

2. Check that `spec/product/04-capabilities/<slug>.md` does not already exist. Refuse if it does.

3. Create the file using the template structure from [`../../README.md`](../../README.md#capability-template). Status starts as `DRAFT`. Fill in what the user provided; leave `TODO` markers in every other section so the user knows what to complete.

4. After writing the file, update the capability list in [`../../product/02-architecture.md`](../../product/02-architecture.md) if appropriate.

5. Do **not** write any code. Spec-first: code comes later, after the capability spec is reviewed.

## Reminders

- Failure modes must cover auth errors, rate limits, 5xx, and malformed responses at minimum.
- Numbered behaviour steps describe **observable** behaviour, not implementation detail.
- "Out of scope" should be explicit — it prevents scope creep better than silence.
