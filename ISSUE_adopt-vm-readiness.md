# Flaky: Adopt test with cephadm fails when the LXD VM agent never comes up

Part of #773 (Reduce Flaky Tests). Data: CI Health Report #717.
Affected job: **Tests / Adopt test with cephadm** — 10.8% over the last 60 days on `main` (largest non-doc failer).

Related flaky issue (same root cause, different harness): the DSL VM-readiness flake — #<insert issue number here>.

## What happens (observed behaviour)

`create_cephadm_vm()` launches the VM once and waits ~200 s; when the agent never responds it `exit 1`s with no relaunch:

```
Error: LXD VM agent isn't currently running
...
Timeout waiting for machine
```

## Steps to reproduce

Intermittent on `main`. Observed instances:

- https://github.com/canonical/microceph/actions/runs/25006847909/job/73232057308
- https://github.com/canonical/microceph/actions/runs/25122463102/job/73626737457
- https://github.com/canonical/microceph/actions/runs/25343841361/job/74307903663

## What were you expecting to happen?

A VM whose agent is briefly slow should be relaunched/retried, not fail adoption setup outright.
