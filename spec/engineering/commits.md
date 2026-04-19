# Rule: commits and pull requests

**Scope:** all git operations.

## Commit philosophy

- **One logical change per commit.** Not "one file per commit" — sometimes a logical change spans files (spec + code + test are often one change). Not "one commit per session" either — if you've done three things, make three commits.
- **Commit every hour.** If a task is done, commit it — don't batch a day's work into one commit. Frequent commits keep the diff reviewable and make `git revert` / `git bisect` precise tools instead of blunt ones.
- **AI agents: commit before finishing.** When an AI agent completes a logical unit of work (tests pass, lint clean), it must commit and push before ending the interaction. Never leave completed work uncommitted in the working tree.
- **Never amend published commits.** Create a new commit instead.
- **Never `--force` push to `main`.** Ask first for any branch.
- **Never `--no-verify`** to bypass a pre-commit hook. Fix the underlying issue.

## Message format

Subject line: ≤70 chars, imperative mood, no trailing period.

```
linkedin: record needs_reauth on 401 response

Previously a 401 from LinkedIn caused repeated failed distribution
attempts for the same tenant. The spec at
spec/product/04-capabilities/linkedin-distribution.md calls for flipping
destination_state.needs_reauth and skipping until the operator
runs astra auth linkedin --tenant <id>. This implements that.
```

Rules for the body:
- Wrap at 72 chars.
- Explain **why** more than **what** — the diff already shows what.
- Reference the spec file(s) that authorize the change. This is how we trace code back to spec.
- When fixing a bug, include repro or root cause in one sentence.
- When adding a feature, link the capability spec file.

## When the change touches the spec

If the change updates both spec and code, the commit message should call this out:

```
linkedin: add image attachment support (spec + code)

spec/product/04-capabilities/linkedin-distribution.md now describes image
attachment behavior. Implementation follows.
```

Spec-only changes are fine as standalone commits and preferred when the spec is evolving before implementation.

## Co-authorship

When an AI agent materially authored the change, attribute it. Examples:

- Claude Code: `Co-Authored-By: Claude <noreply@anthropic.com>`
- GitHub Copilot: attribute in the body with a note, not a trailer.

Don't over-claim: trivial autocompletions don't warrant a trailer. A multi-file refactor performed by an agent does.

## Pull requests

This is a solo repo today but will see PRs as the customer base grows. When the first PR workflow starts:

- PR title mirrors the commit subject style.
- PR body has a **Summary** (2–3 bullets) and **Test plan** (checklist).
- Link spec file(s) affected.
- Draft PRs are fine for "in progress"; mark ready only when tests pass and spec is updated.

### Size and cadence

- **Keep PRs small and focused.** Target p50 ≈ 100–150 lines changed. One feature per PR. A large PR is almost always two or more PRs hiding — split it before asking for review.
- **Squash-merge every PR.** `main` stays a linear history of one-commit-per-feature. That makes `git revert <sha>` and `git bisect` first-class operations instead of archeological digs.
- **The squash commit message is the PR body.** Don't leave it as the default list of WIP subjects. Rewrite it to the spec-linking message format above before merging.

## Branches

- `main` is the release branch.
- Feature branches: `feat/<short-slug>` (e.g. `feat/mastodon-destination`).
- Fix branches: `fix/<short-slug>`.
- Spec-only branches: `spec/<short-slug>` — useful for iterating on a spec before implementation.

## What not to commit

The authoritative list is the repo's [`.gitignore`](../../.gitignore). For secrets specifically, see [`secret-hygiene.md`](secret-hygiene.md). If you find yourself wanting to commit something not covered, update `.gitignore` first.
