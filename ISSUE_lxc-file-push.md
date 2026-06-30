# Flaky: Test maintenance mode fails on a transient lxc file push socket reset

Part of #773 (Reduce Flaky Tests). Data: CI Health Report #717.
Affected job: **Tests / Test maintenance mode** — 2.7% over the last 60 days on `main`.

Related flaky issue (companion harness-retry fix): the snap-store outage flake — #<insert issue number here>.

## What happens (observed behaviour)

A single `lxc file push` during suite setup fails with a forkfile socket reset and cascades the whole suite to FAIL (6/7 tests had passed):

```
Failed to push script to node-wrk1: Error: error receiving version packet from server:
read unix @->/proc/self/fd/22/forkfile.sock: read: connection reset by peer
```

## Steps to reproduce

Intermittent on `main`. Observed instance:

- https://github.com/canonical/microceph/actions/runs/27827205271/job/82354673524

## What were you expecting to happen?

A momentary VM-agent socket reset on `lxc file push` should be retried, not abort suite setup.


