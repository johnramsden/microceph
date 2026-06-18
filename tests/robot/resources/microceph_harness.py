"""Robot Framework library: core execution primitives for the MicroCeph harness.

Class-based library exposing the keywords that run commands inside the outer LXD
test VM and the inner LXD containers. Keeping these as Python methods lets the
higher-level harness logic compose them natively (self.run_in_vm(...)) without
BuiltIn().run_keyword() boilerplate.
"""

import subprocess
import tempfile
import os
import uuid
from collections import namedtuple

from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn

from streaming_process import run_streaming_process

# Attribute names are load-bearing: Robot suites read ${result.rc}, ${result.stdout},
# ${result.stderr} via extended-variable syntax, so these must be ATTRIBUTES (namedtuple),
# and the rc field must be named `rc` (NOT `returncode`).
ExecResult = namedtuple("ExecResult", ["rc", "stdout", "stderr"])


# The class name intentionally matches the module name (microceph_harness) so that
# Robot Framework's "Library microceph_harness.py" path import auto-selects this class
# as the library. A differently-named class (e.g. MicroCephHarness) would require the
# resources/ dir on PYTHONPATH for the dotted "module.ClassName" import form, which the
# path-based import does not provide.
class microceph_harness:
    """Core execution primitives for the MicroCeph Robot Framework harness.

    Runs commands inside the outer LXD test VM and the inner LXD containers,
    mirroring the keyword bodies previously defined in microceph_harness.resource.
    """

    ROBOT_LIBRARY_SCOPE = "SUITE"

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _outer_vm(self):
        """Returns the current outer VM name from the Robot ${OUTER_VM} variable.

        Read lazily on every call rather than cached in __init__: calling BuiltIn()
        during library import raises RobotNotRunningError (the class is instantiated
        for keyword discovery before a run context exists), and the still-in-Robot
        Launch Outer Test VM keyword updates ${OUTER_VM} at runtime via
        Set Suite Variable, so the primitives must observe the current value.
        """
        return BuiltIn().get_variable_value("${OUTER_VM}", "microceph-test-vm")

    def _vm_argv(self, *rest):
        """Builds the argv that runs *rest* inside the outer VM via lxc exec."""
        return ["lxc", "exec", "-n", self._outer_vm(), "--", *rest]

    def _ct_argv(self, container, *rest):
        """Builds the argv that runs *rest* inside *container* via the outer VM."""
        return ["lxc", "exec", "-n", self._outer_vm(), "--", "lxc", "exec", "-n", container, "--", *rest]

    def _exec(self, argv, timeout):
        """Runs *argv* with shell=False and returns an ExecResult. No logging.

        On timeout the child (and, since it is not a new session, only the child)
        is terminated and a non-zero ExecResult is returned rather than raising.
        This mirrors Robot Framework's ``Run Process`` default ``on_timeout=terminate``
        behaviour that the original keywords relied on -- a timed-out command yields
        a result with a non-zero rc, so callers polling via Run In VM keep looping
        instead of crashing.
        """
        try:
            cp = subprocess.run(argv, capture_output=True, text=True, timeout=int(timeout))
            return ExecResult(cp.returncode, cp.stdout, cp.stderr)
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return ExecResult(124, out, f"{err}\nCommand timed out after {timeout}s")

    def _xtrace(self):
        """Returns True when ${XTRACE} is truthy.

        Handles both the Robot bool default ${False} and a CLI string 'True'.
        """
        return str(BuiltIn().get_variable_value("${XTRACE}", False)).upper() in ("TRUE", "YES", "1")

    # -----------------------------------------------------------------------
    # Host dependency checking
    # -----------------------------------------------------------------------

    def require_host_commands(self, *commands):
        """Fails immediately if any listed command is absent from the host PATH.

        Call this in Suite Setup for tests that run directly on the host runner.
        For VM-based tests, lxc is checked automatically inside Launch Outer Test VM.
        """
        for cmd in commands:
            res = subprocess.run(["bash", "-c", f"command -v '{cmd}' >/dev/null 2>&1"])
            if res.returncode != 0:
                raise AssertionError(
                    f"Missing host dependency: '{cmd}' not found in PATH. "
                    "Install it before running this suite."
                )

    # -----------------------------------------------------------------------
    # Core execution helpers
    # -----------------------------------------------------------------------

    def run_in_vm(self, bash_cmd, timeout=300):
        """Runs an arbitrary bash command inside the outer VM (no fail on non-zero).

        bash -eo pipefail: pipe failures and early command failures propagate to the exit code,
        mirroring the set -e behaviour of the original bash CI steps.
        lxc exec -n (--disable-stdin) wires the command's stdin to /dev/null. Without it the
        command inherits Robot's stdin (a tty on interactive runs, Robot Framework >= 7.0), and
        commands that read stdin to EOF when it is not a tty -- notably lxc init / lxc launch,
        which slurp instance config YAML from stdin -- block forever on a tty that never EOFs.
        """
        res = self._exec(self._vm_argv("bash", "-eo", "pipefail", "-c", bash_cmd), timeout)
        logger.info(f"VM cmd rc={res.rc}: {res.stdout}")
        logger.info(f"STDERR: {res.stderr}")
        return res

    def run_in_vm_and_check(self, bash_cmd, timeout=300):
        """Runs a bash command inside the outer VM and fails on non-zero rc."""
        res = self.run_in_vm(bash_cmd, timeout)
        if res.rc != 0:
            raise AssertionError(
                f"Command failed (rc={res.rc}):\nSTDERR: {res.stderr}\nSTDOUT: {res.stdout}"
            )
        return res

    def run_in_vm_must_fail(self, bash_cmd, timeout=120):
        """Runs a bash command inside the outer VM and fails if it SUCCEEDS (expects non-zero)."""
        res = self.run_in_vm(bash_cmd, timeout)
        if res.rc == 0:
            raise AssertionError(f"Expected failure but command succeeded: {bash_cmd}")
        return res

    def run_in_container(self, container, cmd, timeout=300):
        """Runs cmd inside an inner LXD container via the outer VM.

        ${cmd} is written to a temp file by the local runner using Python file I/O
        and pushed into the container with lxc file push, so it is never interpreted
        by any intermediate shell regardless of what characters it contains.
        bash -eo pipefail: mirrors set -e semantics so any failing command or pipe stage
        inside the container fails the keyword immediately.
        """
        logger.console(f"[{container}] {cmd[:80]}")
        name = f"rf_cmd_{uuid.uuid4().hex[:8]}.sh"
        remote = f"/tmp/{name}"
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write(cmd)
            local = f.name
        try:
            push = self._exec(["lxc", "file", "push", local, f"{self._outer_vm()}{remote}"], 30)
            if push.rc != 0:
                raise AssertionError(f"Failed to push script to outer VM: {push.stderr}")
            push = self._exec(self._vm_argv("lxc", "file", "push", remote, f"{container}{remote}"), 30)
            if push.rc != 0:
                raise AssertionError(f"Failed to push script to {container}: {push.stderr}")
            res = self._exec(self._ct_argv(container, "bash", "-eo", "pipefail", remote), timeout)
            logger.info(f"Container cmd rc={res.rc}: {res.stdout}")
            logger.info(f"STDERR: {res.stderr}")
        finally:
            try:
                self._exec(self._ct_argv(container, "rm", "-f", remote), 10)
            except Exception:
                pass
            try:
                self._exec(self._vm_argv("rm", "-f", remote), 10)
            except Exception:
                pass
            try:
                os.unlink(local)
            except OSError:
                pass
        if res.rc != 0:
            raise AssertionError(
                f"Command failed (rc={res.rc}):\nSTDERR: {res.stderr}\nSTDOUT: {res.stdout}"
            )
        return res

    def run_in_head_node(self, cmd, timeout=300):
        """Runs cmd inside node-wrk0 container."""
        return self.run_in_container("node-wrk0", cmd, timeout)

    def run_script_in_vm_with_trace(self, script, args="", timeout=3600):
        """Runs a script inside the outer VM, honouring ${XTRACE}.

        Output streams in real time via streaming_process.py. When ${XTRACE}
        is truthy the script runs under bash -x, tracing the whole script
        body. The -x must sit on the bash that executes the script file --
        a wrapping "bash -x -c '...'" would only trace the single dispatch
        line because the script then runs as an untraced child process.
        No bash -c wrapper is used, so ${script} must be an absolute path
        (lxc exec spawns no shell, hence no tilde expansion).
        """
        runner = "bash -x" if self._xtrace() else "bash"
        return run_streaming_process(
            f"lxc exec {self._outer_vm()} -- {runner} {script} {args}",
            timeout=timeout, xtrace=False,
        )

    def get_public_network_cidr(self):
        """Returns the CIDR of the LXD public network (e.g. 10.0.0.0/24) from the outer VM."""
        return self.run_in_vm("lxc network list --format=csv | grep 'public' | cut -d, -f4", 30).stdout.strip()

    def get_vm_hostname(self):
        """Returns the hostname of the outer VM."""
        return self.run_in_vm("hostname").stdout.strip()

    def get_vm_ip(self):
        """Returns the primary IP of the outer VM (first address from hostname -I)."""
        return self.run_in_vm("hostname -I | cut -d ' ' -f1", 10).stdout.strip()
