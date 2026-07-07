# Flaky: DSL functional tests fail when the LXD VM agent never comes up

Part of #773 (Reduce Flaky Tests). Data: CI Health Report #717.
Affected job: **Tests / DSL functional tests** — 11.5% over the last 60 days on `main`.

Related flaky issue (same root cause, different harness): the Adopt VM-readiness flake.

## What happens (observed behaviour)

An LXD VM launches (`lxc launch` returns 0) but its agent never responds within the readiness window, so the harness times out:

```
[dsl-functest] FAIL: Timed out waiting for VM '...' to be ready
Error: LXD VM agent isn't currently running
```

The old `setup_dsl_test()` retried only `lxc launch`, so the post-launch readiness wait called `fail()` and aborted the whole case.

## Steps to reproduce

Intermittent on `main`. Observed instances:

- https://github.com/canonical/microceph/actions/runs/27663269867/job/81811941445
- https://github.com/canonical/microceph/actions/runs/27734216347/job/82047574030

## What were you expecting to happen?

A VM whose agent is briefly slow should be relaunched/retried, not fail the test case outright.

## Fix

Addressed by PR #<insert PR number here> — wraps launch + attach + readiness wait in a 3-attempt relaunch loop (300 s per attempt; a healthy VM is ready in ~30 s, so waiting longer would not recover a dead-agent boot).

Follow-up: the Robot `launch_outer_test_vm` outer-VM setup has the same agent-never-registers gap (it retries only the `lxc launch` command, then waits on the agent and fails) and could get the same relaunch treatment.
