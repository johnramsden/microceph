# MicroCeph CI flaky-failure fixes — issue + PR creation guide

Six fixes drive down the most frequent non-`govulncheck` CI failures on `main`
(CI Health Report [#717](https://github.com/canonical/microceph/issues/717),
60-day window). All six roll up to the flaky-test master tracker
[#773 "Reduce Flaky Tests"](https://github.com/canonical/microceph/issues/773).

Each fix lives on its own branch in this repo (origin = `johnramsden`), as a
single commit with an `Assisted-by:` trailer and **no** `Signed-off-by:` (you add
that — Step 3). The branches are **local only**; nothing has been pushed.

This repo root also holds, per fix, a tracking-issue body (`ISSUE_*.md`) and a PR
body (`PR_BODY_*.md`).

## Placeholders to fill

The body files contain literal placeholders for numbers that don't exist yet:

- `#<insert issue number here>` — the per-fix tracking issue (created in Step 1).
- `#<insert PR number here>` — a sibling PR cross-reference (known after Step 4).

Replace them with `gh issue edit` / `gh pr edit`, or with `sed` before creating.
Every PR body also already references the master tracker as `Fixes #773` (see the
note below).

## What each fix is

| Branch | Title | Failing job (60-day rate) | Issue body | PR body |
|---|---|---|---|---|
| `fix/doc-linkcheck-infra-flakiness` | docs: harden linkcheck against transient external site failures | Link check (69.6%) | `ISSUE_doc-linkcheck.md` | `PR_BODY_doc-linkcheck.md` |
| `fix/disk-list-getstorage-retry` | fix: retry GetStorage at the daemon /resources endpoint (disk-list TOCTOU) | DSL WAL-DB cleanup (9.1%) | `ISSUE_disk-list-getstorage.md` | `PR_BODY_disk-list-getstorage.md` |
| `fix/dsl-vm-readiness-retry` | test: retry DSL VM launch when the agent fails to come up | DSL functional tests (11.5%) | `ISSUE_dsl-vm-readiness.md` | `PR_BODY_dsl-vm-readiness.md` |
| `fix/adopt-vm-readiness-retry` | test: retry cephadm adopt VM launch when the agent fails to come up | Adopt test with cephadm (10.8%) | `ISSUE_adopt-vm-readiness.md` | `PR_BODY_adopt-vm-readiness.md` |
| `fix/lxc-file-push-retry` | test: retry lxc file push on transient forkfile socket reset | Test maintenance mode (2.7%) | `ISSUE_lxc-file-push.md` | `PR_BODY_lxc-file-push.md` |
| `fix/snap-store-retry` | test: retry snap operations on transient snap-store errors | Regression sequential join mon (2.7%) | `ISSUE_snap-store.md` | `PR_BODY_snap-store.md` |

**Cross-references already wired in the bodies:** `fix/dsl-vm-readiness-retry` ↔
`fix/adopt-vm-readiness-retry` (same `LXD VM agent isn't currently running` root
cause), and `fix/lxc-file-push-retry` ↔ `fix/snap-store-retry` (companion harness
retries; shared test file — see merge-order note).

## A note on `Fixes #773`

Every PR body references the master tracker with `Fixes #773`, as requested.
Because #773 is an umbrella issue, **the first PR merged will auto-close it**. If
you'd rather it stay open until all six land, change `Fixes #773` to
`Part of #773` in each `PR_BODY_*.md` before creating the PRs. Each PR also
`Fixes #<insert issue number here>` — its own per-fix tracking issue from Step 1.

## Step 1 — Create the per-fix tracking issues

Each `gh issue create` prints the new issue URL/number — record it for Step 2.
(`--label` is optional; add one like `bug` only if it exists in the repo.)

```bash
gh issue create --repo canonical/microceph \
  --title "Flaky: documentation Link check fails on transient external-site errors" \
  --body-file ISSUE_doc-linkcheck.md            # --label "<insert label here>"

gh issue create --repo canonical/microceph \
  --title "Flaky: microceph disk list fails on a udevd /dev/disk/by-id TOCTOU race" \
  --body-file ISSUE_disk-list-getstorage.md

gh issue create --repo canonical/microceph \
  --title "Flaky: DSL functional tests fail when the LXD VM agent never comes up" \
  --body-file ISSUE_dsl-vm-readiness.md

gh issue create --repo canonical/microceph \
  --title "Flaky: Adopt test with cephadm fails when the LXD VM agent never comes up" \
  --body-file ISSUE_adopt-vm-readiness.md

gh issue create --repo canonical/microceph \
  --title "Flaky: Test maintenance mode fails on a transient lxc file push socket reset" \
  --body-file ISSUE_lxc-file-push.md

gh issue create --repo canonical/microceph \
  --title "Flaky: sequential-join-mon test fails on transient snap-store 408/5xx" \
  --body-file ISSUE_snap-store.md
```

## Step 2 — Fill the issue numbers into the PR bodies

For each fix, replace `#<insert issue number here>` in its `PR_BODY_*.md` with the
issue number from Step 1, e.g.:

```bash
sed -i 's/#<insert issue number here>/#774/' PR_BODY_doc-linkcheck.md
# ...repeat per body with the matching issue number
```

The two VM-readiness issue bodies cross-reference each other (and all six PR
bodies cross-reference their sibling PR); fill those `#<insert ... here>` the same
way, or backfill the PR numbers in Step 5.

## Step 3 — Add your DCO sign-off (required before pushing)

Commits carry `Assisted-by: claude-code:claude-opus-4-8` but **not**
`Signed-off-by:` — per `AGENTS.md`, only you can make the DCO attestation, and it
must be the **last** trailer. Each branch is a single commit:

```bash
for b in fix/doc-linkcheck-infra-flakiness fix/disk-list-getstorage-retry \
         fix/dsl-vm-readiness-retry fix/adopt-vm-readiness-retry \
         fix/lxc-file-push-retry fix/snap-store-retry; do
  git checkout "$b"
  git commit --amend --no-edit -s   # appends your Signed-off-by after Assisted-by
done
git checkout main
```

## Step 4 — Push each branch and open the PR

`gh pr create` reads the body from the matching file. Run from the repo root.
(Adjust `--head <fork>:` if you push somewhere other than the `johnramsden` origin.)

```bash
# 1. docs linkcheck
git push -u origin fix/doc-linkcheck-infra-flakiness
gh pr create --repo canonical/microceph --base main \
  --head johnramsden:fix/doc-linkcheck-infra-flakiness \
  --title "docs: harden linkcheck against transient external site failures" \
  --body-file PR_BODY_doc-linkcheck.md

# 2. GetStorage /resources retry (the real bug fix)
git push -u origin fix/disk-list-getstorage-retry
gh pr create --repo canonical/microceph --base main \
  --head johnramsden:fix/disk-list-getstorage-retry \
  --title "fix: retry GetStorage at the daemon /resources endpoint (disk-list TOCTOU)" \
  --body-file PR_BODY_disk-list-getstorage.md

# 3. DSL VM readiness retry
git push -u origin fix/dsl-vm-readiness-retry
gh pr create --repo canonical/microceph --base main \
  --head johnramsden:fix/dsl-vm-readiness-retry \
  --title "test: retry DSL VM launch when the agent fails to come up" \
  --body-file PR_BODY_dsl-vm-readiness.md

# 4. Adopt VM readiness retry
git push -u origin fix/adopt-vm-readiness-retry
gh pr create --repo canonical/microceph --base main \
  --head johnramsden:fix/adopt-vm-readiness-retry \
  --title "test: retry cephadm adopt VM launch when the agent fails to come up" \
  --body-file PR_BODY_adopt-vm-readiness.md

# 5. lxc file push retry
git push -u origin fix/lxc-file-push-retry
gh pr create --repo canonical/microceph --base main \
  --head johnramsden:fix/lxc-file-push-retry \
  --title "test: retry lxc file push on transient forkfile socket reset" \
  --body-file PR_BODY_lxc-file-push.md

# 6. snap-store retry
git push -u origin fix/snap-store-retry
gh pr create --repo canonical/microceph --base main \
  --head johnramsden:fix/snap-store-retry \
  --title "test: retry snap operations on transient snap-store errors" \
  --body-file PR_BODY_snap-store.md
```

## Step 5 (optional) — Backfill sibling PR cross-references

Once the PRs exist, replace the remaining `#<insert PR number here>` placeholders
in the sibling cross-references (`gh pr edit <n> --body-file ...` after editing, or
`gh pr comment`). These are cosmetic links between the DSL/Adopt pair and the
lxc-push/snap-store pair.

## Merge-order note: lxc-push and snap-store touch the same test file

`fix/lxc-file-push-retry` and `fix/snap-store-retry` both add the line
`from microceph_harness import ExecResult` to
`tests/robot/resources/test_harness_helpers.py`, at the same spot. Their
`microceph_harness.py` changes are in **separate methods** and do not conflict.
Whichever merges **second** needs a one-line rebase to drop the duplicate import:

```bash
git checkout fix/snap-store-retry      # the second-to-merge branch
git rebase main                        # resolve: keep a single ExecResult import
```

## Local validation already run (per fix)

- **linkcheck** — `conf.py` parses; values are `timeout=60`, `retries=5`, `rate_limit_timeout=600`; `linkcheck_ignore` intact.
- **GetStorage retry** — `go vet ./ceph/ ./api/` clean; `go test ./ceph/ -run GetStorageWithRetry` (new tests, incl. the exact CI error string) pass; existing `TestOSD/TestGetStorageWithRetry` still passes after the delegation refactor.
- **DSL / Adopt** — `bash -n` + `shellcheck -S error` clean on both scripts; `cephadm_adopt_tests.robot` parses.
- **lxc-file-push** — `pytest test_harness_helpers.py` = 110 passed (3 new).
- **snap-store** — `pytest test_harness_helpers.py` = 118 passed (8 new: 5 VM + 3 container); `.resource` parses; keyword resolves.

Note: this environment has `core.autocrlf=true`, so working-tree files show CRLF,
but every committed blob is LF-clean (verified) and will match upstream.

## Known-remaining failures (not addressed here)

These appear in the #717 report but are out of scope for this batch (candidates
for follow-up issues under #773):

- **Run static checks (7.7%) / Run Unit tests (3.8%)** — dqlite PPA apt download `connection timed out` (`ppa.launchpadcontent.net`). Pure infra; would need an apt-retry wrapper around the `ppa:dqlite/dev` install step. Examples: [static checks](https://github.com/canonical/microceph/actions/runs/25343841361/job/74307761081), [unit tests](https://github.com/canonical/microceph/actions/runs/25332146427/job/74268210144).
- **Multi node testing (8.1%)** — `Failed to execute pre-remove hook ... Error getting cluster members: context canceled` followed by `snap "microceph" not found`. Needs deeper root-causing (teardown/timing), not a simple retry. Example: [27190502484](https://github.com/canonical/microceph/actions/runs/27190502484/job/80270248684).
- **Test reef upgrades (5.4%)** — `actionutils.sh: line 1225/1238: [: =: unary operator expected`. Looks like a real shell-quoting bug in an upgrade helper worth a separate fix. Example: [26629804798](https://github.com/canonical/microceph/actions/runs/26629804798/job/78475634151).
- **Test MicroCeph RBD Remote Replication (5.4%)** — `rbd mirror pool disable pool_one: exit status 16 (mirror peers still registered)`. Possible teardown-ordering bug (disable before deregistering peers). Example: [28072470999](https://github.com/canonical/microceph/actions/runs/28072470999/job/83109836876).
