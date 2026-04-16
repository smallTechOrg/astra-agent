# Rule: tenant isolation patterns

**Scope:** all code that touches tenant state, credentials, or external APIs.

[`../product/03-tenancy.md`](../product/03-tenancy.md) defines the isolation **guarantees** Astra makes to its tenants. This file defines the **engineering patterns** that maintain those guarantees. Violating any of these is a bug, full stop.

Each pattern is tagged with the spec guarantee it backs.

## Patterns

### P1. Always include `WHERE tenant_id = ?` on tenant-scoped tables
*Backs: data isolation.*

The tenant-scoped tables are: `source_state`, `destination_state`, `publish_events`, `distribution_records`, `scheduled_tweets`. Every SELECT, UPDATE, and DELETE against these must include `WHERE tenant_id = ?` in its predicate. No exceptions, including "administrative" reads.

Cross-tenant aggregates (operator-level reports) are explicitly-named functions in a dedicated reporting module, with a docstring that says "reads across all tenants."

### P2. Construct API clients per-tenant per-run
*Backs: credential isolation.*

Do not cache a `LinkedInClient`, `TwitterClient`, or `WordPressClient` and pass it to a different tenant's code path. Build with that tenant's credentials at job start, use, close. The shared exception is the LLM client, only because the LLM API key is operator-wide by default — if a tenant overrides it, they get their own.

### P3. `TenantRunner.tick()` catches `Exception` at the top
*Backs: error isolation.*

Every tenant runner wraps its body in `try/except Exception`, logs `tenant_runner_error` with `tenant_id`, and returns. Uncaught exceptions are bugs in the wrapper itself; log them as `tenant_runner_unhandled_exception` if they ever escape.

### P4. Rate-limit state lives in `destination_state` keyed on `(tenant_id, platform)`
*Backs: rate-limit isolation.*

Never store a backoff timestamp, retry-after, or 429 flag in a module-level or class-level variable. It belongs in the database, scoped per tenant per platform.

### P5. Pass secrets explicitly through function arguments
*Backs: secret isolation.*

Credentials read from a tenant's `.env` are passed as arguments to the functions that use them, never stashed in module-level or class-level state where another tenant's code might see them.

### P6. Bind `tenant_id` on every log line in tenant-scoped code
*Cross-cutting: makes every guarantee debuggable.*

Use `log = logger.bind(tenant_id=tenant.id)` at the top of each tenant-scoped function or class. Without this, "which tenant's run broke" is unanswerable in production.

## Test coverage

Any code that touches tenant state needs a test with **two tenants configured** that verifies state from tenant A is not visible to or affected by tenant B. Single-tenant happy path is not sufficient coverage in this codebase.

## Why these are strict

The whole value proposition of multi-tenancy is that customers' data and failures don't leak. One precedent-setting violation ("we'll just share this one client, it's fine") becomes a dozen within a year. These patterns are cheap to maintain if you never break them and expensive to restore if you do.
