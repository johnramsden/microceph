# Description

`lxc file push` fails transiently with a forkfile socket reset when the LXD VM agent is momentarily busy, aborting suite setup. This caused the intermittent **Test maintenance mode** failure (2.7% over 60 days, per #717) — 6/7 tests passed and the one setup-step push failure cascaded the suite to FAIL.

```
Failed to push script ...: read unix @->/proc/self/fd/22/forkfile.sock: read: connection reset by peer
```

`_lxc_file_push` now retries up to 3 times (10 s backoff) instead of failing on the first non-zero rc, mirroring the existing `launch_outer_test_vm` retry; it still raises after the final attempt.

This is a companion harness-retry fix to the **snap-store retry** (PR #<insert PR number here>); both touch `test_harness_helpers.py` and add the same `from microceph_harness import ExecResult` import, so whichever merges second needs a trivial rebase to drop the duplicate. CI evidence: [run 27827205271](https://github.com/canonical/microceph/actions/runs/27827205271/job/82354673524).

Fixes #773
Fixes #<insert issue number here>
Relates to #717

## Type of change

- [x] Clean code (code refactor, test updates; does not introduce functional changes)

## How has this been tested?

`python3 -m pytest -q tests/robot/resources/test_harness_helpers.py` — **110 passed** (incl. 3 new: first-try, transient-then-success, exhausted-raises). Run in the tox `robot` venv; the harness has no LXD dependency for these tests.

## Contributor checklist

Please check that you have:

- [x] self-reviewed the code in this PR
- [x] added code comments, particularly in less straightforward areas
- [x] checked and added or updated relevant documentation
- [ ] added or updated HTML meta descriptions for any new or modified documentation pages (see [#643](https://github.com/canonical/microceph/pull/643))
- [ ] verified that page title and headings accurately represent page content for new or modified documentation pages
- [ ] checked and added or updated relevant release notes
- [x] added tests to verify effectiveness of this change
