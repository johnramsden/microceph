# Description

The **DSL functional tests** fail intermittently (11.5% over 60 days, per #717) when an LXD VM launches but its agent never responds within the readiness window (`Error: LXD VM agent isn't currently running`). The old `setup_dsl_test()` retried only `lxc launch`, so `wait_for_dsl_vm()` then called `fail()` and aborted the case.

A healthy VM reaches "ready" in ~30 s, so an agent still absent after minutes is a failed boot that only a fresh boot recovers — waiting longer does not help (the wait already ran for the full window before this change). This wraps launch + attach + readiness-wait in a 3-attempt relaunch loop and adds a non-fatal `wait_for_vm_command_nonfatal()`. Each attempt waits up to **300 s** (~10× the healthy ready time), so a dead boot is recycled in ~5 min instead of 10. `create_dsl_volumes` stays outside the loop (volumes persist), and the delete-and-relaunch only runs *between* attempts, so a final exhausted failure leaves the VM intact for the `EXIT` trap's diagnostics.

This extends the launch-command retry that `launch_dsl_vm` already does, and shares the `LXD VM agent isn't currently running` root cause with the **Adopt VM-readiness retry** (PR #<insert PR number here>), which applies the same pattern to a different harness. Note: the Robot `launch_outer_test_vm` outer-VM setup has the same gap (it retries only the launch command, then waits on the agent and fails) and could get the same relaunch treatment as a follow-up. CI evidence: [run 27663269867](https://github.com/canonical/microceph/actions/runs/27663269867/job/81811941445), [run 27734216347](https://github.com/canonical/microceph/actions/runs/27734216347/job/82047574030).

Fixes #773
Fixes #781
Relates to #717

## Type of change

- [x] Clean code (code refactor, test updates; does not introduce functional changes)

## How has this been tested?

`bash -n` and `shellcheck -S error` are clean. Re-entrancy verified (volumes persist; only the VM instance is deleted/relaunched). The ~30 s healthy ready time was measured from a passing run, confirming the 300 s per-attempt budget keeps ~10× headroom; 3 × 300 s fits well under the suite's 14400 s wrapper timeout. Full integration requires a built snap + LXD KVM and runs in CI.

## Contributor checklist

Please check that you have:

- [x] self-reviewed the code in this PR
- [x] added code comments, particularly in less straightforward areas
- [x] checked and added or updated relevant documentation
- [ ] added or updated HTML meta descriptions for any new or modified documentation pages (see [#643](https://github.com/canonical/microceph/pull/643))
- [ ] verified that page title and headings accurately represent page content for new or modified documentation pages
- [ ] checked and added or updated relevant release notes
- [ ] added tests to verify effectiveness of this change
