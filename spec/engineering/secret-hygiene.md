# Rule: secret hygiene

**Scope:** everywhere, always. This is the rule most likely to cause real-world harm if violated.

## What is a secret

Anything that authenticates, authorizes, or can be used to impersonate. The product-level list (which credentials Astra recognises per tenant) lives in [`../product/03-tenancy.md`](../product/03-tenancy.md#secrets) and [`../product/05-config.md`](../product/05-config.md).

For code purposes, treat any field whose name matches `*_token`, `*_secret`, `*_password`, `*_key`, or `*_credential` as a secret.

## Where secrets live

| Location | Secrets allowed? |
|---|---|
| `operator_secrets` / `tenant_secrets` DB tables | ✅ Yes (primary store) |
| `config/.env` | ✅ Yes (bootstrap only: `DATABASE_URL`, `ASTRA_UI_PASSWORD`) |
| OS environment variables | ✅ Yes |
| Source code | ❌ Never, including tests |
| Git history | ❌ Never |
| Commit messages, PR descriptions, logs | ❌ Never |

## Rules for code

### Never log a secret
```python
# BAD
log.info("linkedin_call", token=access_token)

# GOOD
log.info("linkedin_call", token_present=bool(access_token))
```

No exceptions for "just debugging." A debug log that accidentally ships to production has revealed customer secrets before and will again.

### Never include secrets in exception messages
```python
# BAD
raise ValueError(f"LinkedIn auth failed with token {token}")

# GOOD
raise ValueError("LinkedIn auth failed. Check ASTRA_TENANT__<id>__LINKEDIN_ACCESS_TOKEN.")
```

### Never accept secrets as YAML values — reject at load time
Per [`../product/05-config.md`](../product/05-config.md), any YAML key ending in `_token`, `_secret`, `_password`, or `_key` is rejected at config load. Fields that hold secrets live in `.env` and are referenced in YAML by their env-var name (e.g. `app_password_env: "WP_APP_PASSWORD"`).

### Never `print()` or `repr()` a config object that may contain secrets
Config models use pydantic. Secret fields must use pydantic's `SecretStr` type. `SecretStr.get_secret_value()` is the only way to extract the raw value, and it should be called at the boundary where the secret is actually used, not earlier.

## Rules for `.gitignore`

The repo's [`.gitignore`](../../.gitignore) is the enforcement point: it must cover every location where a secret could ever exist (root `.env`, per-tenant `.env`, future stores). If you introduce a new secret-bearing location, **add it to `.gitignore` before creating the file**.

## Rules for commits

Before every commit involving new or changed files:

1. Scan the diff for strings that look like tokens (length > 20, mix of alphanumerics, common prefixes like `sk-`, `AQU`, `gsk_`, `ya29.`, `ghp_`, `xox[bp]-`).
2. If anything matches, **stop**. Do not include in the commit. Rotate the secret if it was real.
3. `git diff --cached` is your friend.

A pre-commit hook that runs `gitleaks` or `trufflehog` is recommended. Installing one is a low-cost, high-value one-time action.

## Rules for AI agents

- **Never read a `.env` file** unless the user explicitly asks you to (e.g. "why is my LinkedIn token not working").
- **Never echo, print, or paste a secret value** into your response, even if you've been asked to verify it. Confirm by presence (`LINKEDIN_ACCESS_TOKEN is set` / `is empty`).
- **Never commit a file that contains a secret** even if the user asks. Push back, rotate, continue.

## If a secret leaks

1. Rotate the secret immediately at the provider (LinkedIn dashboard, Twitter developer console, Groq console, etc.).
2. Update the relevant `.env` with the new value.
3. Purge from git history if it was committed: `git filter-repo` or `bfg`. Force-push (with operator approval).
4. Note the incident in the commit message that rotates the secret, without repeating the leaked value.
