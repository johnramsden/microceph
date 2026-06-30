# Flaky: transient snap-store 408/5xx

Part of #773 (Reduce Flaky Tests). Data: CI Health Report #717.
Affected job: **Tests / Regression test for sequential join mon host refresh** — 2.7% over the last 60 days on `main`.

Related flaky issue (companion harness-retry fix): the lxc file push socket-reset flake — #<insert issue number here>.

## What happens (observed behaviour)

A snap operation in suite setup fails when the Snap Store returns 408/5xx, so every test in the suite fails with "Parent suite setup failed":

```
error: cannot perform the following tasks:
- Fetch and check assertions for snap "snapd" (...) (cannot get nonce from store: store server returned status 408)
```

## Steps to reproduce

Intermittent on `main`. Observed instance:

- https://github.com/canonical/microceph/actions/runs/27827205271/job/82354673528

## What were you expecting to happen?

A transient Snap Store outage during `snap install` / `snap refresh` should be retried, not abort suite setup. A genuine error (e.g. bad channel) should still fail immediately.
