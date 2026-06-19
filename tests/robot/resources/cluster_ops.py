"""Robot Framework library: multi-node cluster test scenarios (RBD-cache client
config, service migration). Kept out of the shared harness because these are
suite-specific test bodies; they compose the harness exec helpers."""

import time

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
        self._h.run_in_container(NODES[0], "microceph client config set rbd_cache true", 30)
        for id in (1, 2):
            size = 512 * id
            self._h.run_in_container(
                f"node-wrk{id}", f"microceph client config set rbd_cache_size {size} --target node-wrk{id}", 30
            )
        for id in (1, 2):
            size = 512 * id
            r1 = self._h.run_in_container_unchecked(
                f"node-wrk{id}", f"cat {CEPH_CONF} | grep -c 'rbd_cache = true'", 30
            )
            r2 = self._h.run_in_container_unchecked(
                f"node-wrk{id}", f"cat {CEPH_CONF} | grep -c 'rbd_cache_size = {size}'", 30
            )
            if r1.stdout.strip() != "1":
                raise AssertionError(f"rbd_cache not set on node-wrk{id}")
            if r2.stdout.strip() != "1":
                raise AssertionError(f"rbd_cache_size not set on node-wrk{id}")
        self._h.run_in_container(NODES[0], "microceph client config reset rbd_cache --yes-i-really-mean-it", 30)
        self._h.run_in_container(NODES[0], "microceph client config reset rbd_cache_size --yes-i-really-mean-it", 30)
        for id in (1, 2):
            r1 = self._h.run_in_container_unchecked(
                f"node-wrk{id}", f"cat {CEPH_CONF} | grep -c 'rbd_cache '", 30
            )
            r2 = self._h.run_in_container_unchecked(
                f"node-wrk{id}", f"cat {CEPH_CONF} | grep -c 'rbd_cache_size'", 30
            )
            if r1.stdout.strip() != "0":
                raise AssertionError(f"rbd_cache still in ceph.conf on node-wrk{id}")
            if r2.stdout.strip() != "0":
                raise AssertionError(f"rbd_cache_size still in ceph.conf on node-wrk{id}")

    def test_service_migration(self, src, dst):
        """Migrates services from *src* to *dst* and verifies placement."""
        logger.console(f"[cluster] Migrating services from {src} to {dst}...")
        head = NODES[0]
        self._h.run_in_container(head, f"microceph cluster migrate {src} {dst}", 120)
        for _ in range(8):
            src_ok = self._h.run_in_container_unchecked(
                head, f"microceph status | grep -F -A 1 {src} | grep -qE '^ {{2}}Services: osd$' && echo yes || echo no", 30
            )
            dst_ok = self._h.run_in_container_unchecked(
                head, f"microceph status | grep -F -A 1 {dst} | grep -qE '^ {{2}}Services: mds, mgr, mon$' && echo yes || echo no", 30
            )
            if src_ok.stdout.strip() == "yes" and dst_ok.stdout.strip() == "yes":
                logger.console("[cluster] Services migrated successfully")
                break
            time.sleep(10)
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
