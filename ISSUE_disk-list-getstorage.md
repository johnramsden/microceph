# Flaky: `microceph disk list` fails on a udevd /dev/disk/by-id TOCTOU race

Part of #773 (Reduce Flaky Tests). Data: CI Health Report #717.
Affected job: **Tests / DSL WAL-DB cleanup tests** — 9.1% over the last 60 days on `main`.

Same issue as #738

## What happens (observed behaviour)

After an OSD remove, the suite polls `microceph disk list`, which intermittently errors:

```
internal error: unable to fetch available disks: failed listing storage devices:
Failed to find "/dev/disk/by-id/.#scsi-0QEMU_QEMU_HARDDISK_...": lstat ...: no such file or directory
```

LXD's `resources.GetStorage()` enumerates `/dev/disk/by-id` and races udevd, which atomically replaces symlinks via a `.#`-prefixed temp entry — visible in `readdir` then gone on `lstat`. The daemon `/1.0/resources` endpoint called `GetStorage()` with no retry (PR #739 only added a retry on the OSD-add path).

## Steps to reproduce

Intermittent on `main`. Observed instance:

- https://github.com/canonical/microceph/actions/runs/27990395702/job/82841425600

## What were you expecting to happen?

`disk list` succeeds; a transient, self-healing udev symlink rename should not surface as a user-facing error.

## Fix

Routes the `/resources` endpoint through a shared `ceph.GetStorageWithRetry` helper 
