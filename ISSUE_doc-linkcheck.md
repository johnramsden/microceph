# Flaky: documentation Link check fails on transient external-site errors

Part of #773 (Reduce Flaky Tests). Data: CI Health Report #717.
Affected job: **Main Documentation Checks / Link check / Check links in the documentation** — ~70% over the last 60 days on `main`.

## What happens (observed behaviour)

The Sphinx linkchecker marks valid external links as broken when `canonical.com` / `ubuntu.com` return transient **429** (rate limiting), **502/503**, or read-timeouts, failing the docs build. These are infra hiccups, not broken links.

## Steps to reproduce

Intermittent on `main`. Observed instances (note 28164041735 failed on its retry too):

- https://github.com/canonical/microceph/actions/runs/28164041735/job/83411400793 (attempt 1)
- https://github.com/canonical/microceph/actions/runs/28164041735/job/83498826379 (attempt 2)
- https://github.com/canonical/microceph/actions/runs/27600225197/job/81599195573
- https://github.com/canonical/microceph/actions/runs/27559551401/job/81467561175
- https://github.com/canonical/microceph/actions/runs/26900691284/job/79351940258
- https://github.com/canonical/microceph/actions/runs/26865736450/job/79228885623
- https://github.com/canonical/microceph/actions/runs/26801388372/job/79008627366

## What were you expecting to happen?

The link check passes when the target URLs are valid; only genuinely dead links should fail the build.

## Fix

Addressed by PR #<insert PR number here> — raises `linkcheck_timeout`/`linkcheck_retries`/`linkcheck_rate_limit_timeout` so transient errors clear (no `linkcheck_ignore` additions, so real broken links are still caught).
