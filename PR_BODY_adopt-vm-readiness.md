# Description

The **Adopt test with cephadm** job is the largest non-doc CI failer on `main` (10.8% over 60 days, per #717), failing with the same root cause as the DSL tests: an LXD VM launches but its agent never responds (`Error: LXD VM agent isn't currently running`). `create_cephadm_vm()` launched once, waited ~200 s, then `exit 1` with no relaunch.

This wraps launch + volume create/attach + readiness wait in a 3-attempt retry loop (delete the VM and its `$name-{1,2,3}` volumes between attempts, exit 1 only after the last). Because three attempts can take ~600 s of waiting, the Robot caller's `create_cephadm_vm` step timeout is raised 600 s → 1200 s so the loop isn't SIGKILLed before the final attempt.

This is the companion to the **DSL VM-readiness retry** (PR #<insert PR number here>) — same failure class, different harness. CI evidence: [25006847909](https://github.com/canonical/microceph/actions/runs/25006847909/job/73232057308), [25122463102](https://github.com/canonical/microceph/actions/runs/25122463102/job/73626737457), [25343841361](https://github.com/canonical/microceph/actions/runs/25343841361/job/74307903663).

Fixes #773
Fixes #<insert issue number here>
Relates to #717

## Type of change

- [x] Clean code (code refactor, test updates; does not introduce functional changes)

## How has this been tested?

`bash -n` and `shellcheck -S error` are clean on `adoptutils.sh`; `cephadm_adopt_tests.robot` parses. The 3 × 200 s readiness budget plus relaunch overhead fits under the raised 1200 s step timeout. Full integration requires a built snap + LXD KVM and runs in CI.

## Contributor checklist

Please check that you have:

- [x] self-reviewed the code in this PR
- [x] added code comments, particularly in less straightforward areas
- [x] checked and added or updated relevant documentation
- [ ] added or updated HTML meta descriptions for any new or modified documentation pages (see [#643](https://github.com/canonical/microceph/pull/643))
- [ ] verified that page title and headings accurately represent page content for new or modified documentation pages
- [ ] checked and added or updated relevant release notes
- [ ] added tests to verify effectiveness of this change
