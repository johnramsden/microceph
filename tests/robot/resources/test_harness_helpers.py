"""Unit tests for the pure helpers in the MicroCeph Robot Framework harness.

These cover the @staticmethod parsers and the generic _poll_until poller on the
microceph_harness class, plus the standalone snap_services / cephfs_replication
helpers. The helpers are pure (no self, no BuiltIn), so importing the module and
calling them needs no running Robot context -- only that robotframework is
importable (microceph_harness imports robot.api at module top).

Run with pytest:
    pytest tests/robot/resources/test_harness_helpers.py
"""

import json

from microceph_harness import microceph_harness as H
from snap_services import enabled_active_services
from cephfs_replication import cephfs_replication_list_has_volume, verify_cephfs_list_entry_types


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------

def test_safe_int_plain_digits():
    assert H._safe_int("3") == 3


def test_safe_int_strips_whitespace():
    assert H._safe_int(" 5 ") == 5


def test_safe_int_empty_is_zero():
    assert H._safe_int("") == 0


def test_safe_int_non_numeric_is_zero():
    assert H._safe_int("x") == 0


def test_safe_int_negative_is_zero():
    # isdigit() is False for a leading '-', so this falls back to 0.
    assert H._safe_int("-1") == 0


# ---------------------------------------------------------------------------
# _coerce_xtrace
# ---------------------------------------------------------------------------

def test_coerce_xtrace_bool_false():
    assert H._coerce_xtrace(False) is False


def test_coerce_xtrace_string_true():
    assert H._coerce_xtrace("True") is True


def test_coerce_xtrace_yes():
    assert H._coerce_xtrace("yes") is True


def test_coerce_xtrace_one():
    assert H._coerce_xtrace("1") is True


def test_coerce_xtrace_off():
    assert H._coerce_xtrace("off") is False


def test_coerce_xtrace_empty():
    assert H._coerce_xtrace("") is False


def test_coerce_xtrace_bool_true():
    assert H._coerce_xtrace(True) is True


# ---------------------------------------------------------------------------
# _ceph_osd_counts
# ---------------------------------------------------------------------------

def test_ceph_osd_counts_valid():
    payload = json.dumps({"osdmap": {"num_up_osds": 3, "num_in_osds": 2}})
    assert H._ceph_osd_counts(payload) == (3, 2)


def test_ceph_osd_counts_missing_osdmap():
    assert H._ceph_osd_counts(json.dumps({})) == (0, 0)


def test_ceph_osd_counts_empty_string():
    assert H._ceph_osd_counts("") == (0, 0)


def test_ceph_osd_counts_garbage():
    assert H._ceph_osd_counts("not json at all") == (0, 0)


# ---------------------------------------------------------------------------
# _rgw_daemon_count
# ---------------------------------------------------------------------------

def test_rgw_daemon_count_present():
    text = (
        "  services:\n"
        "    mon: 1 daemons, quorum node-wrk0\n"
        "    rgw: 2 daemons active (1 hosts, 1 zones)\n"
    )
    assert H._rgw_daemon_count(text) == 2


def test_rgw_daemon_count_no_rgw_line():
    text = (
        "  services:\n"
        "    mon: 1 daemons, quorum node-wrk0\n"
        "    osd: 3 osds: 3 up, 3 in\n"
    )
    assert H._rgw_daemon_count(text) == 0


# ---------------------------------------------------------------------------
# _cephfs_snaps_synced_total
# ---------------------------------------------------------------------------

def test_cephfs_snaps_synced_total_list():
    payload = json.dumps(
        {
            "peers": [
                {"mirror_status": [{"snaps_synced": 2}, {"snaps_synced": 3}]},
                {"mirror_status": [{"snaps_synced": 5}]},
            ]
        }
    )
    assert H._cephfs_snaps_synced_total(payload) == 10


def test_cephfs_snaps_synced_total_dict():
    payload = json.dumps(
        {
            "peers": [
                {"mirror_status": {"a": {"snaps_synced": 4}, "b": {"snaps_synced": 6}}},
            ]
        }
    )
    assert H._cephfs_snaps_synced_total(payload) == 10


def test_cephfs_snaps_synced_total_missing_field_defaults_zero():
    payload = json.dumps({"peers": [{"mirror_status": [{}, {"snaps_synced": 7}]}]})
    assert H._cephfs_snaps_synced_total(payload) == 7


def test_cephfs_snaps_synced_total_empty_string():
    assert H._cephfs_snaps_synced_total("") == 0


def test_cephfs_snaps_synced_total_garbage():
    assert H._cephfs_snaps_synced_total("garbage") == 0


# ---------------------------------------------------------------------------
# _poll_until
# ---------------------------------------------------------------------------

def test_poll_until_returns_when_predicate_true_on_third_call():
    calls = []

    def predicate():
        calls.append(1)
        return len(calls) == 3

    H._poll_until(predicate, attempts=10, interval=0, fail_msg="boom")
    assert len(calls) == 3


def test_poll_until_raises_after_attempts_when_always_false():
    calls = []

    def predicate():
        calls.append(1)
        return False

    raised = False
    try:
        H._poll_until(predicate, attempts=4, interval=0, fail_msg="never happened")
    except AssertionError as exc:
        raised = True
        assert str(exc) == "never happened"
    assert raised
    assert len(calls) == 4


def test_poll_until_invokes_between_between_probes():
    between_calls = []

    def predicate():
        return False

    def between():
        between_calls.append(1)

    try:
        H._poll_until(
            predicate,
            attempts=3,
            interval=0,
            fail_msg="x",
            between=between,
        )
    except AssertionError:
        pass
    # between runs after each failed probe -> once per attempt.
    assert len(between_calls) == 3


def test_poll_until_invokes_on_fail_on_exhaustion():
    on_fail_calls = []

    def predicate():
        return False

    def on_fail():
        on_fail_calls.append(1)

    try:
        H._poll_until(
            predicate,
            attempts=2,
            interval=0,
            fail_msg="x",
            on_fail=on_fail,
        )
    except AssertionError:
        pass
    assert len(on_fail_calls) == 1


def test_poll_until_no_raise_when_raise_on_timeout_false():
    def predicate():
        return False

    # Should simply return without raising.
    H._poll_until(
        predicate,
        attempts=2,
        interval=0,
        fail_msg="should not be raised",
        raise_on_timeout=False,
    )


# ---------------------------------------------------------------------------
# enabled_active_services (snap_services.py)
# ---------------------------------------------------------------------------

def test_enabled_active_services_filters_enabled_and_active():
    output = (
        "Service                 Startup   Current   Notes\n"
        "microceph.daemon        enabled   active    -\n"
        "microceph.mds           enabled   inactive  -\n"
        "microceph.mgr           disabled  active    -\n"
        "microceph.osd           enabled   active    -\n"
    )
    assert enabled_active_services(output) == ["microceph.daemon", "microceph.osd"]


# ---------------------------------------------------------------------------
# cephfs_replication_list_has_volume (cephfs_replication.py)
# ---------------------------------------------------------------------------

def test_cephfs_replication_list_has_volume_present_nonempty():
    payload = json.dumps({"myfs": [{"resource_path": "/a", "resource_type": "directory"}]})
    assert cephfs_replication_list_has_volume(payload, "myfs") is True


def test_cephfs_replication_list_has_volume_absent_key():
    payload = json.dumps({"otherfs": [{"resource_path": "/a"}]})
    assert cephfs_replication_list_has_volume(payload, "myfs") is False


def test_cephfs_replication_list_has_volume_empty_object():
    assert cephfs_replication_list_has_volume(json.dumps({}), "myfs") is False


def test_cephfs_replication_list_has_volume_bad_json():
    assert cephfs_replication_list_has_volume("not json", "myfs") is False


# ---------------------------------------------------------------------------
# verify_cephfs_list_entry_types (cephfs_replication.py) -- imported per spec
# ---------------------------------------------------------------------------

def test_verify_cephfs_list_entry_types_ok():
    lines = "\n".join(
        [
            json.dumps({"resource_path": "/volumes/sub", "resource_type": "subvolume"}),
            json.dumps({"resource_path": "/data", "resource_type": "directory"}),
        ]
    )
    items = verify_cephfs_list_entry_types(lines)
    assert len(items) == 2


def test_verify_cephfs_list_entry_types_mismatch_raises():
    line = json.dumps({"resource_path": "/volumes/sub", "resource_type": "directory"})
    raised = False
    try:
        verify_cephfs_list_entry_types(line)
    except AssertionError:
        raised = True
    assert raised
