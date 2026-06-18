"""Robot Framework library: core execution primitives for the MicroCeph harness.

Class-based library exposing the keywords that run commands inside the outer LXD
test VM and the inner LXD containers. Keeping these as Python methods lets the
higher-level harness logic compose them natively (self.run_in_vm(...)) without
BuiltIn().run_keyword() boilerplate.
"""

import json
import re
import subprocess
import tempfile
import time
import os
import uuid
from collections import namedtuple

from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn
from robot.utils import timestr_to_secs

from cephfs_replication import cephfs_replication_list_has_volume
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

    @staticmethod
    def _coerce_xtrace(value):
        """Returns True when *value* represents a truthy XTRACE setting.

        Pure helper so the truthiness rule can be unit-tested without a running
        Robot context. Handles both the Robot bool default ${False} and a CLI
        string like 'True'.
        """
        return str(value).upper() in ("TRUE", "YES", "1")

    def _xtrace(self):
        """Returns True when ${XTRACE} is truthy.

        Handles both the Robot bool default ${False} and a CLI string 'True'.
        """
        return self._coerce_xtrace(BuiltIn().get_variable_value("${XTRACE}", False))

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

    # -----------------------------------------------------------------------
    # Pure parsers
    #
    # All @staticmethod with no self / BuiltIn use, so they can be unit-tested
    # without a running Robot context. Each replaces a jq/grep/sed pipeline that
    # previously computed a value inside the remote command; the remote command
    # is reduced to fetching raw output, and the decision is made here in Python.
    # -----------------------------------------------------------------------

    @staticmethod
    def _safe_int(value):
        """Returns int(value) for a digit-only string, else 0.

        Mirrors the original ``int('...') if '...'.isdigit() else 0`` guard so a
        blank or non-numeric remote output yields 0 rather than raising.
        """
        s = str(value).strip()
        return int(s) if s.isdigit() else 0

    @staticmethod
    def _ceph_osd_counts(status_json):
        """Returns (num_up_osds, num_in_osds) parsed from ``ceph -s -f json`` text.

        Replaces the ``... -f json | jq -r '.osdmap.num_up_osds // 0'`` and the
        matching num_in_osds pipelines. Returns (0, 0) on any parse error or a
        missing osdmap, so a poller keeps waiting instead of crashing.
        """
        try:
            data = json.loads(status_json)
        except (ValueError, TypeError):
            return (0, 0)
        osdmap = data.get("osdmap", {})
        return (int(osdmap.get("num_up_osds", 0)), int(osdmap.get("num_in_osds", 0)))

    @staticmethod
    def _rgw_daemon_count(ceph_status_text):
        """Returns the RGW daemon count from human-readable ``ceph -s`` output.

        Replaces ``grep -F "rgw:" | sed -E "s/.* ([0-9]+) daemon.*/\\1/" || echo 0``.
        Finds the services line containing ``rgw:`` and extracts the leading
        daemon count; returns 0 when there is no rgw line.
        """
        for line in ceph_status_text.splitlines():
            if "rgw:" in line:
                m = re.search(r"(\d+)\s+daemon", line)
                return int(m.group(1)) if m else 0
        return 0

    @staticmethod
    def _cephfs_snaps_synced_total(status_json):
        """Returns the total snaps_synced across all peers' mirror_status entries.

        Replaces ``jq '[.peers[].mirror_status | .[] | .snaps_synced // 0] | add // 0'``.
        ``mirror_status`` may be a list of entries or a dict keyed by something,
        so both forms are iterated. Returns 0 on any parse error.
        """
        try:
            data = json.loads(status_json)
        except (ValueError, TypeError):
            return 0
        total = 0
        for peer in data.get("peers", []):
            mirror_status = peer.get("mirror_status", [])
            if isinstance(mirror_status, dict):
                entries = mirror_status.values()
            else:
                entries = mirror_status
            for entry in entries:
                total += entry.get("snaps_synced", 0)
        return total

    # -----------------------------------------------------------------------
    # Generic poller
    # -----------------------------------------------------------------------

    @staticmethod
    def _poll_until(predicate, attempts, interval, fail_msg, on_fail=None, between=None, raise_on_timeout=True):
        """Call predicate() up to `attempts` times; return on the first truthy result.

        Between probes, run the optional `between` side-effect (a repair step) then
        sleep `interval` (seconds, or a Robot time string like '3s'). On exhaustion run
        the optional `on_fail` diagnostic and, unless raise_on_timeout is False, raise
        AssertionError(fail_msg).
        """
        secs = timestr_to_secs(interval) if isinstance(interval, str) else interval
        for _ in range(int(attempts)):
            if predicate():
                return
            if between is not None:
                between()
            time.sleep(secs)
        if on_fail is not None:
            on_fail()
        if raise_on_timeout:
            raise AssertionError(fail_msg)

    # -----------------------------------------------------------------------
    # VM / cluster pollers (migrated from microceph_harness.resource)
    # -----------------------------------------------------------------------

    def wait_for_vm_agent(self, vm_name):
        """Polls lxc exec until the LXD VM agent responds (60 x 5 s = 5 min max)."""
        logger.info(f"Waiting for VM agent in {vm_name}")
        self._poll_until(
            lambda: self._exec(["lxc", "exec", "-n", vm_name, "--", "true"], 15).rc == 0,
            attempts=60,
            interval=5,
            fail_msg=f"VM agent for {vm_name} did not become ready within 5 minutes",
        )

    def wait_for_cluster_health_ok(self, node="", tries=100, interval="3s"):
        """Polls microceph.ceph health until HEALTH_OK (tries x interval).

        Pass node= (e.g. node-wrk0) to poll inside that LXD container; omit to run
        directly on the outer VM with sudo.
        """
        if node == "":
            cmd = "sudo microceph.ceph health"
            label = "outer VM"
        else:
            cmd = f"lxc exec {node} -- microceph.ceph health"
            label = node
        logger.console(f"[health] Waiting for HEALTH_OK ({label})...")

        def predicate():
            return self.run_in_vm(cmd, 30).stdout.strip() == "HEALTH_OK"

        def on_fail():
            if node == "":
                self.run_in_vm_and_check("sudo microceph.ceph -s", 30)
            else:
                self.run_in_container(node, "microceph.ceph -s", 30)

        def succeeded():
            logger.console("[health] HEALTH_OK")

        # _poll_until does not signal success vs return, so emit the success
        # console line from a wrapping predicate when the check first passes.
        def predicate_with_log():
            ok = predicate()
            if ok:
                succeeded()
            return ok

        self._poll_until(
            predicate_with_log,
            attempts=tries,
            interval=interval,
            fail_msg="Cluster did not reach HEALTH_OK",
            on_fail=on_fail,
        )

    def poll_ceph_status_contains(self, substring, tries=16, sleep="15s"):
        """Polls ceph status on the outer VM until the output contains *substring*."""
        attempt = [0]

        def predicate():
            out = self.run_in_vm("sudo microceph.ceph status", 30).stdout
            logger.info(f"Attempt {attempt[0]}: {out}")
            if substring in out:
                logger.console(f"[status] PASS: '{substring}' found (attempt {attempt[0]})")
                attempt[0] += 1
                return True
            attempt[0] += 1
            return False

        self._poll_until(
            predicate,
            attempts=tries,
            interval=sleep,
            fail_msg=f"ceph status never contained '{substring}' after {tries} attempts",
        )

    def wait_for_n_nodes_in_cluster(self, n, head_node="node-wrk0"):
        """Polls microceph status on *head_node* until at least *n* nodes appear (8 x 2 s)."""
        def predicate():
            status = self.run_in_vm(f"lxc exec {head_node} -- microceph status", 30).stdout
            count = len(re.findall(r"^- node", status, re.M))
            return count >= int(n)

        self._poll_until(
            predicate,
            attempts=8,
            interval=2,
            fail_msg=f"Cluster did not reach {n} node(s) after 16 s",
        )

    def wait_for_pool_crush_rule(self, rule_id, tries=30):
        """Polls osd pool ls detail until at least one pool carries crush_rule *rule_id* (30 x 2 s)."""
        logger.console(f"[crush] Waiting for pool with crush_rule {rule_id}...")
        ls_cmd = 'lxc exec node-wrk0 -- sh -c "microceph.ceph osd pool ls detail 2>/dev/null || true"'

        def predicate():
            if f"crush_rule {rule_id}" in self.run_in_vm(ls_cmd, 30).stdout:
                logger.console(f"[crush] Found pool with crush_rule {rule_id}")
                return True
            return False

        def on_fail():
            self.run_in_vm(ls_cmd, 30)

        self._poll_until(
            predicate,
            attempts=tries,
            interval=2,
            fail_msg=f"No pool reached crush_rule {rule_id} after {tries} tries",
            on_fail=on_fail,
        )

    def node_is_in_mon_list(self, node, head_node="node-wrk0"):
        """Returns "yes" if *node* appears in the mon daemons line of ceph -s via *head_node*.

        Callers compare the result string against "yes", so the literal "yes"/"no"
        return contract is preserved.
        """
        status = self.run_in_vm(f"lxc exec {head_node} -- microceph.ceph -s", 30).stdout
        if re.search(rf"mon: .*daemons.*{re.escape(node)}", status):
            return "yes"
        return "no"

    # -----------------------------------------------------------------------
    # RGW pollers
    # -----------------------------------------------------------------------

    def wait_for_rgw(self, expect, tries=8):
        """Polls until at least *expect* RGW daemons are running on the outer VM."""
        logger.console(f"[rgw] Waiting for {expect} RGW daemon(s)...")

        def predicate():
            text = self.run_in_vm("sudo microceph.ceph -s", 30).stdout
            count = self._rgw_daemon_count(text)
            if count >= int(expect):
                logger.console(f"[rgw] Found {count} RGW daemon(s)")
                return True
            return False

        def on_fail():
            self.run_in_vm_and_check("sudo microceph.ceph -s", 30)

        self._poll_until(
            predicate,
            attempts=tries,
            interval=5,
            fail_msg=f"Never reached {expect} RGW daemon(s)",
            on_fail=on_fail,
        )

    def wait_for_rgw_on_head_node(self, expect, tries=20):
        """Polls until at least *expect* RGW daemons are running on node-wrk0."""
        logger.console(f"[rgw] Waiting for {expect} RGW daemon(s) on node-wrk0...")

        def predicate():
            text = self.run_in_vm("lxc exec node-wrk0 -- microceph.ceph -s", 30).stdout
            return self._rgw_daemon_count(text) >= int(expect)

        self._poll_until(
            predicate,
            attempts=tries,
            interval=5,
            fail_msg=f"Never reached {expect} RGW daemon(s) on head node",
        )

    def wait_for_rgw_ssl_port(self, host="localhost", port=443, tries=60):
        """Polls until the RGW SSL endpoint on *host*:*port* serves a certificate."""
        logger.console(f"[rgw] Waiting for RGW SSL on {host}:{port}...")

        def predicate():
            out = self.run_in_vm(f"echo | openssl s_client -connect {host}:{port} 2>/dev/null", 15).stdout
            return "BEGIN CERTIFICATE" in out

        self._poll_until(
            predicate,
            attempts=tries,
            interval=5,
            fail_msg=f"RGW SSL never started on {host}:{port}",
        )

    def get_rgw_ssl_cn(self, host="localhost", port=443):
        """Returns the certificate CN served by the RGW SSL endpoint on *host*:*port*."""
        subject = self.run_in_vm(
            f"echo | openssl s_client -connect {host}:{port} 2>/dev/null | "
            f"openssl x509 -noout -subject 2>/dev/null",
            30,
        ).stdout
        m = re.search(r"CN\s*=\s*(.+)", subject)
        return m.group(1).strip() if m else ""

    def read_base64_file_from_container(self, container, path):
        """Returns the base64-encoded (no line wrapping) contents of *path* inside *container*."""
        return self.run_in_vm(f'lxc exec {container} -- bash -c "sudo base64 -w0 {path}"', 30).stdout.strip()

    # -----------------------------------------------------------------------
    # OSD pollers
    # -----------------------------------------------------------------------

    def wait_for_osd_count(self, expected_count, tries=10):
        """Polls until num_in_osds >= *expected_count* on the outer VM."""
        logger.console(f"[osd] Waiting for {expected_count} OSD(s) on outer VM...")

        def predicate():
            out = self.run_in_vm("sudo microceph.ceph -s -f json 2>/dev/null", 30).stdout
            _, num_in = self._ceph_osd_counts(out)
            if num_in >= int(expected_count):
                logger.console(f"[osd] Found {num_in} OSD(s)")
                return True
            return False

        def on_fail():
            self.run_in_vm_and_check("sudo microceph.ceph -s", 30)

        self._poll_until(
            predicate,
            attempts=tries,
            interval=5,
            fail_msg=f"Never reached {expected_count} OSD(s) on outer VM",
            on_fail=on_fail,
        )
        # Original logs ceph -s on the success path too.
        self.run_in_vm_and_check("sudo microceph.ceph -s", 30)

    def wait_for_osd_count_up_in(self, expected_count, tries=24):
        """Polls until BOTH num_up_osds AND num_in_osds >= *expected_count* on the outer VM.

        Mirrors bash wait_for_osds_up_in: an OSD that is "in" but not "up" (e.g. a
        LUKS volume that failed to reopen after a restart) must NOT satisfy this gate.
        """
        logger.console(f"[osd] Waiting for {expected_count} OSD(s) up AND in on outer VM...")

        def predicate():
            out = self.run_in_vm("sudo microceph.ceph -s -f json 2>/dev/null", 30).stdout
            up, num_in = self._ceph_osd_counts(out)
            if up >= int(expected_count) and num_in >= int(expected_count):
                logger.console(f"[osd] Found {up} up / {num_in} in OSD(s)")
                return True
            return False

        def on_fail():
            self.run_in_vm_and_check("sudo microceph.ceph -s", 30)

        self._poll_until(
            predicate,
            attempts=tries,
            interval=5,
            fail_msg=(
                f"Never reached {expected_count} OSD(s) up AND in on outer VM "
                f"(up<{expected_count} or in<{expected_count})"
            ),
            on_fail=on_fail,
        )
        self.run_in_vm_and_check("sudo microceph.ceph -s", 30)

    def wait_for_osd_count_head(self, expected_count, tries=20):
        """Polls until num_in_osds >= *expected_count* via node-wrk0.

        The JSON is fetched through the outer VM's lxc exec (jq is not used inside
        the container) so it works regardless of container tool availability.
        """
        logger.console(f"[osd] Waiting for {expected_count} OSD(s) on node-wrk0...")

        def predicate():
            out = self.run_in_vm("lxc exec node-wrk0 -- microceph.ceph -s -f json", 30).stdout
            _, num_in = self._ceph_osd_counts(out)
            if num_in >= int(expected_count):
                logger.console(f"[osd] Found {num_in} OSD(s)")
                return True
            return False

        def on_fail():
            self.run_in_container("node-wrk0", "microceph.ceph -s", 30)

        self._poll_until(
            predicate,
            attempts=tries,
            interval=5,
            fail_msg=f"Never reached {expected_count} OSD(s) on node-wrk0",
            on_fail=on_fail,
        )
        self.run_in_container("node-wrk0", "microceph.ceph -s", 30)

    # -----------------------------------------------------------------------
    # CephFS replication pollers
    # -----------------------------------------------------------------------

    def wait_for_cephfs_replication_list_non_empty(self, node, vol, attempts=50):
        """Polls until the CephFS replication list for *vol* on *node* has a non-empty entry.

        JSON parsing and the present-and-non-empty check are delegated to
        cephfs_replication.py, so an absent volume key counts as "not present yet"
        (keep polling) rather than success.
        """
        def predicate():
            out = self.run_in_vm(f"lxc exec {node} -- sudo microceph replication list cephfs --json", 30).stdout
            return cephfs_replication_list_has_volume(out, vol)

        self._poll_until(
            predicate,
            attempts=attempts,
            interval=5,
            fail_msg=f"CephFS replication list for {vol} still empty or absent after {attempts} attempts",
        )

    def wait_for_cephfs_snaps_synced(self, node, vol, threshold, attempts=100):
        """Polls until total snaps_synced for volume *vol* on *node* reaches *threshold*."""
        def predicate():
            out = self.run_in_vm(f"lxc exec {node} -- microceph replication status cephfs {vol} --json", 30).stdout
            return self._cephfs_snaps_synced_total(out) >= int(threshold)

        self._poll_until(
            predicate,
            attempts=attempts,
            interval=5,
            fail_msg=f"CephFS snaps_synced for {vol} never reached {threshold} after {attempts} attempts",
        )

    # -----------------------------------------------------------------------
    # File / snap-mount helpers
    # -----------------------------------------------------------------------

    def read_file_in_vm(self, path):
        """Returns the ExecResult of running cat *path* on the outer VM.

        Returns the result OBJECT (not just stdout): callers read ${result.stdout.strip()}.
        """
        return self.run_in_vm(f"cat {path}", 10)

    def ensure_snap_mount_healthy(self, container):
        """Verifies the pre-baked microceph snap squashfs mount is alive in *container*, repairing it if not.

        Containers cloned from the pre-baked image mount /snap/microceph/x1 via
        squashfuse at boot, and that FUSE mount intermittently comes up dead
        ("transport endpoint is not connected"), which breaks every subsequent
        snap command. Restarting the mount unit re-establishes it. _poll_until
        checks first, then runs the repair (between) and sleeps, matching the
        original check-then-repair-then-sleep ordering.
        """
        def predicate():
            cmd = f'lxc exec {container} -- sh -c "test -r /snap/microceph/current/meta/snap.yaml"'
            return self.run_in_vm(cmd, 15).rc == 0

        def between():
            logger.console(f"[install] microceph snap mount broken on {container}; restarting mount unit")
            self.run_in_vm(
                f'lxc exec {container} -- sh -c '
                f'"umount -l /snap/microceph/x1 2>/dev/null; systemctl restart snap-microceph-x1.mount"',
                30,
            )

        self._poll_until(
            predicate,
            attempts=6,
            interval=3,
            fail_msg=f"microceph snap mount never became healthy on {container}",
            between=between,
        )
