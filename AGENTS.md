# AGENTS.md

## Layout

All Go source lives under `microceph/`. There is no top-level `Makefile` — use `microceph/Makefile`.

## Commit conventions

- Commits must be signed off (`Signed-off-by:` trailer) **by the human**. Agents must never add a `Signed-off-by:` trailer on the human's behalf — the DCO sign-off is an attestation only the human can make.
- Agents must include an `Assisted-by:` trailer identifying the agent and model.
- Order trailers as: `Assisted-by:` first, then the human's `Signed-off-by:` last (added by the human).

Format:

```
Assisted-by: AGENT_NAME:MODEL_VERSION
```

- `AGENT_NAME` — the AI tool or framework (e.g. `claude-code`, `opencode`, `codex`, `pi`, …).
- `MODEL_VERSION` — the specific model version used (e.g. `claude-sonnet-4-6`, `gpt-5.5`).

Example:

```
Assisted-by: opencode:gpt-5.5
```

Other commit rules:

- Commit messages must be ASCII only.
- Keep PRs small and focused; don't mix trivial and controversial changes.
- Squash into logical commits (API / docs / CLI / daemon / tests / CI) for non-trivial PRs.
- Maintain a linear git history.

## Coding conventions

Follow the [Go Style Guide](https://google.github.io/styleguide/go/guide), plus:

### Imports

Three groups, alphabetised (run `go fmt`): standard library, third-party, MicroCeph.

```go
import (
    "fmt"
    "os"

    "github.com/pborman/uuid"

    "github.com/canonical/microceph/microceph/common"
    "github.com/canonical/microceph/microceph/database"
)
```

### Avoid one-line assign/test

Use:

```go
err := doStuff()
if err != nil {
    return err
}
```

Not:

```go
if err := doStuff(); err != nil {
    return err
}
```

### Doc comments

Every exported (capitalised) name needs a doc comment immediately preceding the declaration with no intervening blank lines.

### Injectable function variables

When extracting a function as a package-level `var` so tests can override it, suffix the variable name with `Func` (e.g. `getMonitorCountFunc`). This makes it obvious at the call site that the symbol is an injectable variable, not a plain function.

### Atomic file writes

When writing config files, write to a `.tmp` path and `os.Rename` into place so a failed write can't leave partial state on disk:

```go
tmpFile := destPath + ".tmp"
err := os.WriteFile(tmpFile, data, 0644)
if err != nil {
    return err
}
err = os.Rename(tmpFile, destPath)
if err != nil {
    os.Remove(tmpFile)
    return err
}
```

## Building and installing locally

Build the snap:

```bash
snapcraft pack -v
```

Install the locally built snap (the `--dangerous` flag is required for unsigned local builds):

```bash
sudo snap install --dangerous microceph_*.snap
```

Locally built snaps do **not** auto-connect plugs. Connect them manually:

```bash
sudo snap connect microceph:block-devices
sudo snap connect microceph:hardware-observe
sudo snap connect microceph:mount-observe
sudo snap connect microceph:load-rbd
sudo snap connect microceph:microceph-support
sudo snap connect microceph:network-bind
sudo snap connect microceph:process-control
sudo snap connect microceph:dm-crypt
sudo snap restart microceph.daemon
```

## Unit tests and lint

From `microceph/`:

```bash
make check-unit      # unit tests
make check-static    # lint / static checks
```

## Robot Framework integration tests

See [tests/robot/README.md](tests/robot/README.md) for the full suite layout and
harness conventions, and [Designing Robot Framework tests](#designing-robot-framework-tests)
below for how to structure new suites and harness keywords.

Two suites run on the host with no extra dependencies. Use `tox`, which installs
the dependencies into an isolated venv rather than the system Python (matches CI):

```bash
tox -e robot -- --test-suite static-checks   # golangci-lint + go vet
tox -e robot -- --test-suite unit-tests       # go test ./...
```

All other suites are integration tests that launch LXD VMs.  To run them locally
you need:

1. **LXD initialised** on the host (`lxd init --auto` if not already done).
2. **Internet access from LXD VMs** — suite setup runs `apt-get install s3cmd jq`
   and other package installs inside the VMs.  If the LXD bridge has no outbound
   route, package downloads will fail.
3. **A built snap** — produce one with `snapcraft pack -v` at the repo root.

Run a single suite:

```bash
tox -e robot -- --snap-path /path/to/microceph_*.snap \
    --test-suite cluster-tests
```

Run every suite sequentially:

```bash
tox -e robot -- --snap-path /path/to/microceph_*.snap
```

Results land in `output.xml`, `log.html`, and `report.html` in the working
directory.  Each suite tears down its own LXD VM on completion (or failure).

## Designing Robot Framework tests

How to structure new suites and harness keywords. The reference implementation is
the class library `tests/robot/resources/microceph_harness.py` plus the thin
`tests/robot/resources/microceph_harness.resource`.

### Architecture

- Shared keywords live in a **class-based Python library**
  (`microceph_harness.py`). `microceph_harness.resource` is **thin**: a
  `*** Variables ***` block and `Library` imports, nothing else.
- Suites import the `.resource`. Robot maps a method `run_in_vm_and_check` to the
  keyword `Run In VM And Check` (case/space/underscore-insensitive), so moving a
  keyword body between Robot and Python never touches a suite — as long as the
  keyword name is preserved.

### What goes where — three layers

Separate test scenarios, reusable helpers, and area-specific logic:

- **Suites** (`tests/robot/<suite>/*.robot`) own **test bodies**: a sequence of
  actions *plus the assertions that validate one feature*. If a keyword does work
  **and** asserts the outcome, it is a test body — put it in the calling suite's
  `*** Keywords ***` (or the test case itself), not the shared harness. Prefer
  readable Robot here; a linear "set this, check that" scenario gains nothing from
  Python.
- **The harness** (`microceph_harness.py` + the thin `.resource`) holds
  **area-agnostic reusable helpers** only: exec primitives, pollers,
  lifecycle/distribution, parsers, `_poll_until`. No whole test scenarios.
- **Area modules** (siblings to `snap_services.py` / `cephfs_replication.py`) hold
  **area-coupled reusable logic** shared across suites — e.g. `rbd_replication.py`,
  `cluster_ops.py`, `replication.resource`. Area-specific logic does not belong in
  the monolithic harness.

Within a keyword, move loops, branching, parsing, and polling to Python; keep linear
"do this, then check that" in Robot. Don't inline a value-computing pipeline in a
test body — give it a named keyword. But "non-linear" alone does not put something in
the harness: a one-suite scenario goes to that suite (and may stay Robot).

### Purify: fetch raw, decide in Python

When a check parses command output, do not compute the value in the remote shell:

- The remote command does the **minimal I/O** (`microceph.ceph -s -f json`,
  `snap services microceph`).
- The **decision/parse** happens in a pure Python helper (`@staticmethod` or
  module-level — no `self`, no `BuiltIn`) using `json.loads`/regex, so it is
  unit-testable.
- Keep only irreducible remote *actions* as commands. Preserve the resulting
  *value*, not the literal `jq`/`grep` string.

### Never call `BuiltIn().run_keyword()`

Compose Python natively. Because the core primitives (`run_in_vm`,
`run_in_container`, `_poll_until`, ...) are themselves methods, higher-level logic
calls `self.run_in_vm(...)` directly — there is no need to invoke Robot keywords
from Python.

- Allowed `BuiltIn` uses: `get_variable_value(...)` (a read) and
  `set_suite_variable(...)` (e.g. the `${OUTER_VM}` bridge during a mixed migration).
- Replace `Log` / `Log To Console` with `robot.api.logger.info` / `.console`,
  `Sleep` with `time.sleep`, and `Should *` / `Fail` with
  `raise AssertionError(msg)` (preserve the message text).

### Surface configuration, don't bury it

Magic values must be visible and changeable, not hidden mid-method:

- **Run/environment-varying values → Robot `*** Variables ***`** (overridable with
  `--variable`), read lazily in Python via `get_variable_value`: outer-VM
  cpu/memory/image/disk, inner-node image series, LXD storage size, upgrade
  channel, tool versions.
- **Structural lists and fixed paths → named module-level constants** grouped at
  the **top** of the library (one source of truth; not per-run overrides): the node
  tuple, the snap-interface sets, the apt tool list, the hurl fixtures, the
  `ceph.conf`/data-dir paths, base-image aliases, the builder name, the `raw.lxc`
  block.
- **Derive, don't repeat.** Compute from one source: worker loops/counts from
  `NODES` (`NODES[1:]`, `len(NODES)` — not `range(4)`/`(1,2,3)`), the head node as
  `NODES[0]`, the conf path from one `MICROCEPH_DATA` base. Adding a node, plug, or
  path is then a one-line change.
- Drive repetitive file copies from a **declarative manifest** (`(src, dest, +x)`
  tuples) plus one copy helper, keeping per-suite groups selectable — don't bake
  each path into its own keyword.

### Route container commands through the exec helpers

Never hand-build a nested `lxc exec <node> -- sh -c "..."` string and pass it to
`run_in_vm`. Run a command in an inner container through a container-exec helper
(built on `_ct_argv`), not by embedding `lxc exec` in an outer-VM command:

- Use a direct-argv helper for a single command (no inner shell), and an
  inner-shell variant for pipelines.
- Sites whose **non-zero rc is a valid outcome** (`grep -c`, `... || echo 0`,
  `... && echo yes || echo no`) need a **non-raising** variant, and must **not**
  run under `bash -eo pipefail` (errexit/pipefail would abort before the trailing
  `|| echo ...` and change the captured output).
- The temp-file-push helper (`run_in_container`) is only for arbitrary script bodies
  a shell would mangle; it does three round-trips per call, so never use it in poll
  loops — use the direct helpers there.

This removes the fragile nested quoting/escaping and keeps one model: "run X in the
outer VM" versus "run X in a node".

### Library conventions

- **Class name == module name** (lowercase), so `Library microceph_harness.py`
  auto-selects the class. A `CamelCase` class silently registers zero keywords
  under a path import.
- Set `ROBOT_LIBRARY_SCOPE = "SUITE"`.
- Read `${OUTER_VM}` / `${SNAP_PATH}` / `${XTRACE}` / `${REPO_ROOT}` **lazily** via
  `get_variable_value`. Do **not** read them in `__init__`: the class is
  instantiated for keyword discovery before a run context exists, which raises
  `RobotNotRunningError`.
- Run commands via an **arg-list subprocess (`shell=False`)** — never build a host
  shell string for quoting. (Node commands go through the container-exec helpers; see
  "Route container commands through the exec helpers".)
- Return command results as a namedtuple exposing `.rc` / `.stdout` / `.stderr`
  (suites read `${result.rc}` etc. via extended-variable syntax — the `rc`
  attribute name is load-bearing; do not rename it `returncode`).
- The exec helper returns a **non-zero rc on timeout** (mirroring Robot's
  `Run Process` terminate behaviour) rather than raising, so pollers keep looping.
- Use the single generic poller
  `_poll_until(predicate, attempts, interval, fail_msg, on_fail=None, between=None, raise_on_timeout=True)`
  for every poll loop instead of re-writing `FOR`/`Sleep`.
- Keep standalone pure helper modules (`snap_services.py`, `cephfs_replication.py`,
  `rbd_replication.py`, `streaming_process.py`) separate. The class imports them but
  never re-exports their keyword names — two imported libraries exposing the same
  keyword name is a Robot error.

### Preserve behaviour when migrating an existing keyword

- Keep the keyword **name**, the **return shape** (a bare string vs. the result
  object — match what callers consume), the **timeouts**, **sleeps**, and the
  **assertion-message text** byte-for-byte. Only the extraction pipeline is rewritten.
- If you find a dead argument or an unreachable keyword, **flag it** for a
  maintainer — do not silently "fix" it inside a behaviour-preserving migration.

### Verify

- Add pytest tests for every pure helper in
  `tests/robot/resources/test_harness_helpers.py`; they run from the `unit-tests`
  suite and need no LXD.
- `tox -e robot -- --dryrun ...` proves keyword resolution across the suites.
- Actual integration behaviour (anything touching LXD) runs in CI, not locally.