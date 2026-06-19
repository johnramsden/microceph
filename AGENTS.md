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

### What goes where

Robot is good at linear "do this, then check that" sequences and poor at logic.
Split accordingly:

- **Keep in Robot** (a `.resource` keyword or a test body): flat sequences of
  commands and assertions — e.g. SSL certificate generation/rotation, enabling a
  service, a setup that just calls other keywords in order.
- **Move to Python** (a library method): loops, branching, data manipulation,
  output parsing, and polling. Never bury a value-computing
  `... | grep | sed | jq` pipeline in a test body; expose a named keyword
  (`Should Have One Mon`, `Wait For RGW`) instead.

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

### Library conventions

- **Class name == module name** (lowercase), so `Library microceph_harness.py`
  auto-selects the class. A `CamelCase` class silently registers zero keywords
  under a path import.
- Set `ROBOT_LIBRARY_SCOPE = "SUITE"`.
- Read `${OUTER_VM}` / `${SNAP_PATH}` / `${XTRACE}` / `${REPO_ROOT}` **lazily** via
  `get_variable_value`. Do **not** read them in `__init__`: the class is
  instantiated for keyword discovery before a run context exists, which raises
  `RobotNotRunningError`.
- Run commands with an **arg list and `shell=False`**; never build a shell string
  for quoting. For the inner-container hop, write the command to a temp file and
  run it as a `bash` file operand (no `-c`), so no intermediate shell re-interprets it.
- Return command results as a namedtuple exposing `.rc` / `.stdout` / `.stderr`
  (suites read `${result.rc}` etc. via extended-variable syntax — the `rc`
  attribute name is load-bearing; do not rename it `returncode`).
- The exec helper returns a **non-zero rc on timeout** (mirroring Robot's
  `Run Process` terminate behaviour) rather than raising, so pollers keep looping.
- Use the single generic poller
  `_poll_until(predicate, attempts, interval, fail_msg, on_fail=None, between=None, raise_on_timeout=True)`
  for every poll loop instead of re-writing `FOR`/`Sleep`.
- Keep standalone pure helper modules (`snap_services.py`,
  `cephfs_replication.py`, `streaming_process.py`) separate. The class imports
  them, but never re-exports their keyword names — two imported libraries exposing
  the same keyword name is a Robot error.

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