# Description

The daemon `/1.0/resources` endpoint called LXD's `resources.GetStorage()` once with no retry. `GetStorage()` enumerates `/dev/disk/by-id` and hits a udevd TOCTOU race (a `.#`-prefixed temp symlink is seen in `readdir` then vanishes on `lstat`), so `microceph disk list` fails intermittently. This surfaced in the **DSL WAL-DB cleanup** suite (9.1% over 60 days, per #717):

```
failed listing storage devices: Failed to find "/dev/disk/by-id/.#scsi-...": lstat ...: no such file or directory
```

PR #739 added this retry to the OSD-add path but not to the daemon `/resources` endpoint that `disk list` hits directly. This extracts a shared `ceph.GetStorageWithRetry` helper (3 attempts, linear backoff), routes both `cmdResourcesGet` and `OSDManager.getStorageWithRetry` through it, and adds unit tests.

CI evidence: [run 27990395702](https://github.com/canonical/microceph/actions/runs/27990395702/job/82841425600).

Fixes #773
Fixes #779
Relates to #717

## Type of change

- [x] Bug fix (non-breaking change which fixes an issue)

## How has this been tested?

New `ceph/storage_test.go` tests inject the exact CI error string and assert the retry absorbs it (and that it exhausts/returns correctly); the existing OSD-path `TestGetStorageWithRetry` still passes after the delegation refactor.

## Contributor checklist

Please check that you have:

- [x] self-reviewed the code in this PR
- [x] added code comments, particularly in less straightforward areas
- [x] checked and added or updated relevant documentation
- [ ] added or updated HTML meta descriptions for any new or modified documentation pages (see [#643](https://github.com/canonical/microceph/pull/643))
- [ ] verified that page title and headings accurately represent page content for new or modified documentation pages
- [ ] checked and added or updated relevant release notes
- [x] added tests to verify effectiveness of this change
