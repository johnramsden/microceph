# Description

The documentation **Link check** job is the most frequent CI failure on `main` (~70% over 60 days, per the CI Health Report #717): external sites (`canonical.com`, `ubuntu.com`) intermittently return 429 / 502 / read-timeouts that Sphinx marks as broken links, even though the links are valid.

This hardens the linkchecker against those transient infra errors, without hiding real broken links (no `linkcheck_ignore` additions):

- `linkcheck_timeout` 30 → 60
- `linkcheck_retries` 3 → 5
- `linkcheck_rate_limit_timeout` (default 300) → 600

A genuinely dead URL still returns BROKEN on every retry and still fails the build. CI evidence (incl. a retried-then-still-failed attempt): [run 28164041735 att1](https://github.com/canonical/microceph/actions/runs/28164041735/job/83411400793), [att2](https://github.com/canonical/microceph/actions/runs/28164041735/job/83498826379). Full list in the tracking issue.

Fixes #773
Fixes #<insert issue number here>
Relates to #717

## Type of change

- [x] Clean code (code refactor, test updates; does not introduce functional changes)
- [x] Documentation update (change to documentation only)

## How has this been tested?

`docs/conf.py` parses and the three options resolve to `60` / `5` / `600` with `linkcheck_ignore` unchanged. All three are valid Sphinx linkcheck builder options.

## Contributor checklist

Please check that you have:

- [x] self-reviewed the code in this PR
- [x] added code comments, particularly in less straightforward areas
- [x] checked and added or updated relevant documentation
- [ ] added or updated HTML meta descriptions for any new or modified documentation pages (see [#643](https://github.com/canonical/microceph/pull/643))
- [ ] verified that page title and headings accurately represent page content for new or modified documentation pages
- [ ] checked and added or updated relevant release notes
- [ ] added tests to verify effectiveness of this change
