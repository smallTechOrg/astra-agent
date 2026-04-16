---
description: Per Boris's tip — challenge the pending change. "Grill me on these changes and don't approve until I pass your test. Prove this works."
---

You have just finished (or are about to finish) a change. Before I accept it, challenge me:

1. Diff the working tree against `main` (or the base branch if different). Read every hunk.
2. For each non-trivial hunk, pose one hard question:
   - Which spec sentence authorised this change?
   - What's the failure mode I didn't handle?
   - What breaks at the tenant boundary? At the secret boundary?
   - If this ran on an empty DB / full DB / corrupted state, what happens?
   - If I revert only this hunk, does the rest still compile and pass tests?
3. Bundle the questions into a numbered list. Do **not** answer them yourself; return them for me to answer.
4. Only after I respond to every question do you mark the change approved.

Harsher is better. The point is to catch what I glossed over.
