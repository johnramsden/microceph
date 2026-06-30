# Description

snap operations contact the Snap Store and fail transiently on 408/5xx, aborting suite setup. This caused the intermittent **Regression test for sequential join mon host refresh** failure (2.7% over 60 days, per #717):

```
cannot get nonce from store: store server returned status 408
```

New `run_snap_in_vm_with_retry` / `run_snap_in_container_with_retry` keywords retry up to 3 times (15 s backoff) **only** when the error matches a snap-store-outage signature; a non-store error fails immediately so real failures aren't masked. They are wired into the store-hitting snap ops (`Setup LXD In VM`, `install_microceph_from_store_on_all_nodes`).

This is a companion harness-retry fix to the **lxc file push retry** (PR #<insert PR number here>). CI evidence: [run 27827205271](https://github.com/canonical/microceph/actions/runs/27827205271/job/82354673528).

Fixes #773
Fixes #<insert issue number here>
Relates to #717

## Type of change

- [x] Clean code (code refactor, test updates; does not introduce functional changes)

## How has this been tested?

`python3 -m pytest -q tests/robot/resources/test_harness_helpers.py` — **118 passed** (incl. 8 new: 5 VM-variant + 3 container-variant; the container tests also pin the `(container, cmd, timeout, shell)` argument order). `microceph_harness.resource` parses and the new keyword resolves.

## Contributor checklist

Please check that you have:

- [x] self-reviewed the code in this PR
- [x] added code comments, particularly in less straightforward areas
- [x] checked and added or updated relevant documentation
- [ ] added or updated HTML meta descriptions for any new or modified documentation pages (see [#643](https://github.com/canonical/microceph/pull/643))
- [ ] verified that page title and headings accurately represent page content for new or modified documentation pages
- [ ] checked and added or updated relevant release notes
- [x] added tests to verify effectiveness of this change
