"""Robot Framework library: multi-node cluster test scenarios (RBD-cache client
config, service migration). Kept out of the shared harness because these are
suite-specific test bodies; they compose the harness exec helpers."""

from robot.api import logger

from microceph_harness import microceph_harness, NODES, CEPH_CONF


# class name == module name so `Library cluster_ops.py` auto-selects it.
class cluster_ops:
    ROBOT_LIBRARY_SCOPE = "SUITE"

    def __init__(self):
        self._h = microceph_harness()

    # check_client_configs and test_service_migration go here.

    def check_client_configs(self):
        """Sets cluster-wide and per-host client configs, then verifies and resets."""
        logger.console("[config] Checking client config set/reset across nodes...")
        # Per-host configs are exercised on the two non-head worker nodes (NODES[1:3]).
        # Derive node names and sizes from NODES so adding a node cannot silently bypass
        # the check; size scales 512 * position (node-wrk1 -> 512, node-wrk2 -> 1024).
        workers = list(enumerate(NODES[1:3], start=1))
        self._h.run_in_container(NODES[0], "microceph client config set rbd_cache true", 30)
        for i, node in workers:
            size = 512 * i
            self._h.run_in_container(
                node, f"microceph client config set rbd_cache_size {size} --target {node}", 30
            )
        for i, node in workers:
            size = 512 * i
            r1 = self._h.run_in_container_unchecked(
                node, f"cat {CEPH_CONF} | grep -c 'rbd_cache = true'", 30
            )
            r2 = self._h.run_in_container_unchecked(
                node, f"cat {CEPH_CONF} | grep -c 'rbd_cache_size = {size}'", 30
            )
            if r1.stdout.strip() != "1":
                raise AssertionError(f"rbd_cache not set on {node}")
            if r2.stdout.strip() != "1":
                raise AssertionError(f"rbd_cache_size not set on {node}")
        self._h.run_in_container(NODES[0], "microceph client config reset rbd_cache --yes-i-really-mean-it", 30)
        self._h.run_in_container(NODES[0], "microceph client config reset rbd_cache_size --yes-i-really-mean-it", 30)
        for i, node in workers:
            r1 = self._h.run_in_container_unchecked(
                node, f"cat {CEPH_CONF} | grep -c 'rbd_cache '", 30
            )
            r2 = self._h.run_in_container_unchecked(
                node, f"cat {CEPH_CONF} | grep -c 'rbd_cache_size'", 30
            )
            if r1.stdout.strip() != "0":
                raise AssertionError(f"rbd_cache still in ceph.conf on {node}")
            if r2.stdout.strip() != "0":
                raise AssertionError(f"rbd_cache_size still in ceph.conf on {node}")

    def test_service_migration(self, src, dst):
        """Migrates services from *src* to *dst* and verifies placement."""
        logger.console(f"[cluster] Migrating services from {src} to {dst}...")
        head = NODES[0]
        self._h.run_in_container(head, f"microceph cluster migrate {src} {dst}", 120)
        src_cmd = f"microceph status | grep -F -A 1 {src} | grep -qE '^ {{2}}Services: osd$' && echo yes || echo no"
        dst_cmd = f"microceph status | grep -F -A 1 {dst} | grep -qE '^ {{2}}Services: mds, mgr, mon$' && echo yes || echo no"

        def migrated():
            src_ok = self._h.run_in_container_unchecked(head, src_cmd, 30)
            dst_ok = self._h.run_in_container_unchecked(head, dst_cmd, 30)
            if src_ok.stdout.strip() == "yes" and dst_ok.stdout.strip() == "yes":
                logger.console("[cluster] Services migrated successfully")
                return True
            return False

        # raise_on_timeout=False: the explicit post-poll assertions below are the failure gate.
        self._h._poll_until(migrated, attempts=8, interval=10, fail_msg="", raise_on_timeout=False)
        self._h.run_in_container(head, "microceph status", 30)
        self._h.run_in_container(head, "microceph.ceph -s", 30)
        src_ok = self._h.run_in_container_unchecked(
            head, f"microceph status | grep -F -A 1 {src} | grep -qE '^ {{2}}Services: osd$' && echo yes || echo no", 30
        )
        dst_ok = self._h.run_in_container_unchecked(
            head, f"microceph status | grep -F -A 1 {dst} | grep -qE '^ {{2}}Services: mds, mgr, mon$' && echo yes || echo no", 30
        )
        if src_ok.stdout.strip() != "yes":
            raise AssertionError(f"{src} should have only OSD after migration")
        if dst_ok.stdout.strip() != "yes":
            raise AssertionError(f"{dst} should have mds,mgr,mon after migration")
