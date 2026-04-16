# Workflow: spec drift check

Audit the repository for divergence between [`../../product/`](../../product/) and [`src/`](../../../src/), per the rule in [`../spec-driven.md`](../spec-driven.md). Report findings as a punch list, not a narrative.

## Procedure

1. **List all capability specs.** Read every file in [`../../product/04-capabilities/`](../../product/04-capabilities/). For each, extract the component name from the `**Component:**` line and the numbered behavior steps.

2. **Locate each component in code.** For each spec'd component, find the corresponding Python module/class in `src/astra/`. Note any that are missing entirely.

3. **Spot-check behavior steps.** For each capability, check that the numbered behavior steps in the spec are reflected in the code. You don't need to verify every line — focus on:
   - Inputs and outputs (does the function signature match the spec's Inputs/Outputs sections?)
   - Failure modes (are the specified failure modes handled in code?)
   - Invariants (unique constraints, idempotency, tenant scoping)

4. **Reverse check.** For any substantial Python module/class in `src/astra/` not matched by a capability spec, flag it as "unspec'd code."

5. **Check config schema.** Compare keys listed in [`../../product/05-config.md`](../../product/05-config.md) against the pydantic models in config. Flag mismatches.

6. **Check CLI surface.** Compare commands in [`../../product/06-cli.md`](../../product/06-cli.md) against registered `click` commands. Flag missing or extra commands.

7. **Check DB schema.** Compare tables/columns in [`../../product/07-data-model.md`](../../product/07-data-model.md) against the migration/init code.

## Report format

Output a single markdown table plus a short summary. Example:

```
| Area | Type | Finding |
|---|---|---|
| capability: linkedin-distribution | missing behavior | Step 2 (needs_reauth check) not implemented |
| capability: twitter-scheduled-cadence | unspec'd arg | code accepts `dry_run=True` but spec doesn't mention |
| config | missing key | `daemon.startup_grace_seconds` in spec, not in model |
| cli | unspec'd command | `astra generate` still registered; removed in spec pivot |
| db | spec-only table | `destination_state` defined in spec, not in migrations |
```

Summary (1-2 lines): worst category, total count, recommended order of fixes.

## Scope

- Do **not** fix anything during the audit. Report-only.
- Do **not** propose spec changes unless asked — code fixes are almost always the answer when drift is found.
- Do **not** run tests or make external API calls.
- Tenant-scoped files under `config/tenants/<id>/` are user data, not part of the audit.
