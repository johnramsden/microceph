*** Settings ***
Documentation    Shared resource for MicroCeph Robot Framework tests.
...    All test commands run directly inside the outer LXD VM (no actionutils.sh dependency).
Library         OperatingSystem
Library         Process
Library         String
Library         Collections
Library         microceph_harness.py
Library         streaming_process.py
Library         snap_services.py
Library         cephfs_replication.py

*** Variables ***
${SNAP_PATH}          ${EMPTY}
${OUTER_VM}           microceph-test-vm
${OUTER_VM_DISK}      50GiB
${REPO_ROOT}          ${CURDIR}/../../..
# Default for bash -x tracing; override with --variable XTRACE:True.
${XTRACE}             ${False}

*** Keywords ***

# ---------------------------------------------------------------------------
# VM lifecycle
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Script and artefact distribution
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Single-node MicroCeph setup
# ---------------------------------------------------------------------------

Install And Bootstrap MicroCeph
    [Documentation]    Installs snap and bootstraps the cluster.
    [Arguments]    ${mon_ip}=${EMPTY}
    Install MicroCeph From Local Snap
    Bootstrap MicroCeph Cluster    ${mon_ip}

Enable DM Crypt
    [Documentation]    Connects the dm-crypt snap interface and restarts microceph.daemon.
    Run In VM And Check    sudo snap connect microceph:dm-crypt    30
    Run In VM And Check    sudo snap restart microceph.daemon    60

# ---------------------------------------------------------------------------
# Multi-node LXD container setup
# ---------------------------------------------------------------------------

Provision Multinode VM
    [Documentation]    Launches the outer VM and provisions LXD + 4 inner MicroCeph nodes.
    ...    The sequence itself is not retried, so setup failures surface instead of being
    ...    masked (Launch Outer Test VM retries the bare lxc launch internally).
    [Arguments]    ${vm_name}    ${disk_size}    ${network_type}=public
    Launch Outer Test VM    vm_name=${vm_name}    disk_size=${disk_size}
    Copy Scripts To VM
    Copy Snap To VM
    Clear IPTables
    Free Runner Disk
    Setup LXD In VM
    Create LXD Containers With Loop Devices    ${network_type}
    Install MicroCeph On All Nodes

Setup LXD In VM
    [Documentation]    Installs and initialises LXD inside the outer VM.
    Log To Console    [setup] Setting up LXD inside ${OUTER_VM} (may take several minutes)...
    ${check}=    Run In VM    sudo snap list | grep -cF "lxd" || true    30
    IF    "${check.stdout.strip()}" != "1"
        Run In VM And Check    sudo snap install lxd    300
    END
    Run In VM And Check    sudo snap refresh    300
    Run In VM And Check    sudo snap set lxd daemon.group=adm    30
    # Force a btrfs (copy-on-write) storage pool. On the default "dir" backend every
    # lxc init / publish is a full rootfs copy, which serializes ~6 x 1.5GB copies in
    # multi-node setup; btrfs makes instance creation a near-instant reflink snapshot.
    # Size the loop file explicitly: the auto default (~20% of free space, capped at
    # 30GB) can be too small for the base image + 4 node rootfs deltas + loop OSDs
    # that replication suites create inside container rootfs.
    Run In VM And Check    sudo lxd init --auto --storage-backend btrfs --storage-create-loop 25    60

# ---------------------------------------------------------------------------
# OSD / disk operations
# ---------------------------------------------------------------------------

Add OSD To Node
    [Documentation]    Adds /dev/sdia as an OSD on the specified inner container.
    [Arguments]    ${container}
    Log To Console    [osd] Adding OSD to ${container}...
    Run In VM And Check    lxc exec ${container} -- microceph disk add /dev/sdia --wipe    120
    Sleep    1s

# ---------------------------------------------------------------------------
# RGW operations
# ---------------------------------------------------------------------------

Enable RGW
    [Documentation]    Enables the Rados Gateway daemon and waits for it to start.
    Log To Console    [rgw] Enabling RGW...
    Run In VM And Check    sudo microceph enable rgw    120
    Wait For RGW    1

Disable RGW
    [Documentation]    Disables the Rados Gateway daemon.
    Log To Console    [rgw] Disabling RGW...
    Run In VM And Check    sudo microceph disable rgw    60

Enable RGW SSL
    [Documentation]    Generates an SSL certificate and enables RGW with SSL.
    Log To Console    [rgw] Generating SSL certificate and enabling RGW with SSL...
    Run In VM And Check    sudo openssl genrsa -out /tmp/ca.key 2048    30
    Run In VM And Check    sudo openssl req -x509 -new -nodes -key /tmp/ca.key -days 1024 -out /tmp/ca.crt -outform PEM -subj "/C=US/ST=Denial/L=Springfield/O=Dis/CN=www.example.com"    30
    Run In VM And Check    sudo openssl genrsa -out /tmp/server.key 2048    30
    Run In VM And Check    sudo openssl req -new -key /tmp/server.key -out /tmp/server.csr -subj "/C=US/ST=Denial/L=Springfield/O=Dis/CN=www.example.com"    30
    Run In VM And Check    bash -c "echo 'subjectAltName = DNS:localhost' > /tmp/extfile.cnf"    10
    Run In VM And Check    sudo openssl x509 -req -in /tmp/server.csr -CA /tmp/ca.crt -CAkey /tmp/ca.key -CAcreateserial -out /tmp/server.crt -days 365 -extfile /tmp/extfile.cnf    30
    ${cert}=    Run In VM    sudo base64 -w0 /tmp/server.crt    30
    ${key}=    Run In VM    sudo base64 -w0 /tmp/server.key    30
    Run In VM And Check    sudo microceph enable rgw --ssl-certificate="${cert.stdout.strip()}" --ssl-private-key="${key.stdout.strip()}"    120
    Wait For RGW    1
    Wait For RGW SSL Port

Exercise RGW
    [Documentation]    Creates an S3 user, uploads a file via s3cmd, and verifies via curl.
    [Arguments]    ${filename}=test
    Log To Console    [rgw] Exercising RGW (HTTP)...
    Run In VM And Check    sudo microceph.ceph status    30
    Run In VM And Check    sudo systemctl status snap.microceph.rgw --no-pager    30
    ${user_exists}=    Run In VM    sudo microceph.radosgw-admin user list | grep -q test && echo yes || echo no    30
    IF    "${user_exists.stdout.strip()}" != "yes"
        Run In VM And Check    sudo microceph.radosgw-admin user create --uid=test --display-name=test    60
        Run In VM And Check    sudo microceph.radosgw-admin key create --uid=test --key-type=s3 --access-key fooAccessKey --secret-key fooSecretKey    30
    END
    Run In VM And Check    bash -c "echo hello-radosgw > ~/${filename}.txt"    10
    Run In VM And Check    s3cmd --host localhost --host-bucket="localhost/%(bucket)" --access_key=fooAccessKey --secret_key=fooSecretKey --no-ssl mb s3://testbucket    30
    Run In VM And Check    s3cmd --host localhost --host-bucket="localhost/%(bucket)" --access_key=fooAccessKey --secret_key=fooSecretKey --no-ssl put -P ~/${filename}.txt s3://testbucket    30
    Run In VM And Check    curl -s http://localhost/testbucket/${filename}.txt | grep -F hello-radosgw    30

Exercise RGW SSL
    [Documentation]    Exercises RGW over HTTPS using the CA cert from enable_rgw_ssl.
    [Arguments]    ${filename}=test
    Log To Console    [rgw] Exercising RGW (HTTPS)...
    Run In VM And Check    sudo microceph.ceph status    30
    Run In VM And Check    sudo systemctl status snap.microceph.rgw --no-pager    30
    ${user_exists}=    Run In VM    sudo microceph.radosgw-admin user list | grep -q test && echo yes || echo no    30
    IF    "${user_exists.stdout.strip()}" != "yes"
        Run In VM And Check    sudo microceph.radosgw-admin user create --uid=test --display-name=test    60
        Run In VM And Check    sudo microceph.radosgw-admin key create --uid=test --key-type=s3 --access-key fooAccessKey --secret-key fooSecretKey    30
    END
    Run In VM And Check    bash -c "echo hello-radosgw-ssl > ~/${filename}.txt"    10
    Run In VM And Check    s3cmd --ca-certs=/tmp/ca.crt --host localhost --host-bucket="localhost/%(bucket)" --access_key=fooAccessKey --secret_key=fooSecretKey mb s3://testbucketssl    30
    Run In VM And Check    s3cmd --ca-certs=/tmp/ca.crt --host localhost --host-bucket="localhost/%(bucket)" --access_key=fooAccessKey --secret_key=fooSecretKey put -P ~/${filename}.txt s3://testbucketssl    30
    Run In VM And Check    CURL_CA_BUNDLE=/tmp/ca.crt curl -s https://localhost/testbucketssl/${filename}.txt | grep -F hello-radosgw-ssl    30

Generate Self Signed CA And Server Cert In Container
    [Documentation]    Generates a self-signed CA and server cert chain inside ${container}.
    ...    Creates /tmp/ca.key, /tmp/ca.crt, /tmp/server.key, /tmp/server.csr,
    ...    /tmp/server.crt, and /tmp/extfile.cnf inside the container.
    [Arguments]    ${container}
    Run In Container    ${container}    sudo openssl genrsa -out /tmp/ca.key 2048 && sudo openssl req -x509 -new -nodes -key /tmp/ca.key -days 1024 -out /tmp/ca.crt -outform PEM -subj '/C=US/ST=Denial/L=Springfield/O=Dis/CN=www.example.com' && sudo openssl genrsa -out /tmp/server.key 2048 && sudo openssl req -new -key /tmp/server.key -out /tmp/server.csr -subj '/C=US/ST=Denial/L=Springfield/O=Dis/CN=www.example.com' && echo 'subjectAltName = DNS:localhost' > /tmp/extfile.cnf && sudo openssl x509 -req -in /tmp/server.csr -CA /tmp/ca.crt -CAkey /tmp/ca.key -CAcreateserial -out /tmp/server.crt -days 365 -extfile /tmp/extfile.cnf    120

Enable RGW Head Node
    [Documentation]    Enables RGW on node-wrk0 and waits for it to start.
    Log To Console    [rgw] Enabling RGW on node-wrk0...
    Run In Container    node-wrk0    microceph enable rgw    120
    Wait For RGW On Head Node    1

Exercise RGW Head Node
    [Documentation]    Exercises RGW on node-wrk0.
    [Arguments]    ${filename}=test
    Log To Console    [rgw] Exercising RGW on node-wrk0...
    Run In Container    node-wrk0    microceph.ceph status    30
    ${user_exists}=    Run In VM    lxc exec node-wrk0 -- bash -c "microceph.radosgw-admin user list | grep -q test && echo yes || echo no"    30
    IF    "${user_exists.stdout.strip()}" != "yes"
        Run In Container    node-wrk0    microceph.radosgw-admin user create --uid=test --display-name=test    60
        Run In Container    node-wrk0    microceph.radosgw-admin key create --uid=test --key-type=s3 --access-key fooAccessKey --secret-key fooSecretKey    30
    END
    Run In Container    node-wrk0    echo hello-radosgw > ~/test.txt    10
    Run In Container    node-wrk0    s3cmd --host localhost --host-bucket=localhost/%\\(bucket\\) --access_key=fooAccessKey --secret_key=fooSecretKey --no-ssl mb s3://testbucket    30
    Run In Container    node-wrk0    s3cmd --host localhost --host-bucket=localhost/%\\(bucket\\) --access_key=fooAccessKey --secret_key=fooSecretKey --no-ssl put -P ~/test.txt s3://testbucket    30
    Run In Container    node-wrk0    curl -s http://localhost/testbucket/test.txt | grep -F hello-radosgw    30

# ---------------------------------------------------------------------------
# Cluster health and config
# ---------------------------------------------------------------------------

Verify Cluster Health
    [Documentation]    Polls microceph.ceph health until HEALTH_OK on the outer VM.
    Wait For Cluster Health OK

Verify Cluster Health Head Node
    [Documentation]    Polls microceph.ceph health until HEALTH_OK via node-wrk0.
    Wait For Cluster Health OK    node-wrk0

Test Cluster Config Operations
    [Documentation]    Verifies rbd_default_features and tests cluster_network config set/reset.
    Log To Console    [config] Testing cluster config set/reset...
    ${rbd_feat}=    Run In VM    sudo microceph.ceph config get mon rbd_default_features    30
    Should Be Equal As Strings    ${rbd_feat.stdout.strip()}    63    msg=rbd_default_features not 63
    ${cip}=    Run In VM    ip -4 -j route | jq -r '.[] | select(.dst | contains("default")) | .prefsrc' | tr -d '[:space:]'    30
    ${ts}=    Run In VM    sudo systemctl show --property ActiveEnterTimestampMonotonic snap.microceph.osd.service | cut -d= -f2    30
    Run In VM And Check    sudo microceph cluster config set cluster_network ${cip.stdout.strip()}/8 --wait    60
    ${ts2}=    Run In VM    sudo systemctl show --property ActiveEnterTimestampMonotonic snap.microceph.osd.service | cut -d= -f2    30
    ${out}=    Run In VM    sudo microceph cluster config get cluster_network | grep -cim1 'cluster_network'    30
    Should Be True    int('${out.stdout.strip()}') >= 1    msg=config check failed
    Should Be True    int('${ts2.stdout.strip()}') >= int('${ts.stdout.strip()}')    msg=OSD service did not restart after config set
    Run In VM And Check    sudo microceph cluster config reset cluster_network --wait    60
    ${ts3}=    Run In VM    sudo systemctl show --property ActiveEnterTimestampMonotonic snap.microceph.osd.service | cut -d= -f2    30
    Should Be True    int('${ts3.stdout.strip()}') >= int('${ts2.stdout.strip()}')    msg=OSD service did not restart after config reset

Test Pool Replication Operations
    [Documentation]    Tests pool replication-factor set/reset operations.
    Log To Console    [pool] Testing pool replication factor operations...
    Run In VM    sudo microceph.ceph osd pool create mypool    30
    Run In VM And Check    sudo microceph pool set-rf --size 1 ""    30
    Run In VM And Check    sudo microceph.ceph config get osd.1 osd_pool_default_size | grep -Fx "1"    30
    Run In VM And Check    sudo microceph pool list | grep "mypool"    30
    Run In VM And Check    sudo microceph pool list | grep "mypool" | grep -F " 3 "    30
    Run In VM And Check    sudo microceph pool set-rf --size 3 mypool    30
    Run In VM And Check    sudo microceph.ceph osd pool get mypool size | grep -F "size: 3"    30
    Run In VM And Check    sudo microceph pool list | grep "mypool" | grep -F " 3 "    30
    Run In VM And Check    sudo microceph pool set-rf --size 1 "*"    30
    Run In VM And Check    sudo microceph.ceph osd pool get mypool size | grep -F "size: 1"    30
    Run In VM And Check    sudo microceph pool list | grep "mypool" | grep -F " 1 "    30

Test Log Level Control
    [Documentation]    Sets log level to warning (3) and verifies.
    Run In VM And Check    sudo microceph log set-level warning    30
    ${result}=    Run In VM    sudo microceph log get-level    30
    Should Be Equal As Strings    ${result.stdout.strip()}    3    msg=Incorrect log level: ${result.stdout}

Test Snap Disable Enable
    [Documentation]    Tests that snap disable/enable re-enables all services.
    ...    Records the names of services that were enabled+active before disable and verifies
    ...    each one by name is restored after re-enable (not just the aggregate count), and
    ...    fails on timeout. Mirrors bash test_snap_disable_enable + check_snap_service_active_enabled.
    Log To Console    [snap] Testing snap disable/enable service restoration...
    ${before_result}=    Run In VM    snap services microceph    30
    @{services_before}=    Enabled Active Services    ${before_result.stdout}
    ${count_before}=    Get Length    ${services_before}
    Log To Console    [snap] ${count_before} enabled+active service(s) before disable: ${services_before}
    Run In VM And Check    sudo snap disable microceph    60
    Run In VM And Check    sudo snap enable microceph    60
    ${restored}=    Set Variable    ${False}
    FOR    ${i}    IN RANGE    30
        ${now_result}=    Run In VM    snap services microceph    30
        @{services_now}=    Enabled Active Services    ${now_result.stdout}
        ${active}=    Get Length    ${services_now}
        IF    ${active} >= ${count_before}
            Log To Console    [snap] All ${count_before} service(s) re-enabled after ${i}s
            ${restored}=    Set Variable    ${True}
            BREAK
        END
        Sleep    1s
    END
    IF    not ${restored}    Fail    Not all services re-enabled after 30s (expected ${count_before})
    # Verify each previously enabled+active service is back, by name.
    FOR    ${svc}    IN    @{services_before}
        ${svc_state}=    Run In VM    snap services ${svc}    30
        Should Contain    ${svc_state.stdout}    enabled    msg=Service ${svc} not enabled after re-enable
        Should Contain    ${svc_state.stdout}    active    msg=Service ${svc} not active after re-enable
    END
    Verify Cluster Health

Test SSL Certificate Rotation
    [Documentation]    Tests RGW SSL certificate rotation (with/without --restart).
    Log To Console    [rgw] Testing SSL certificate rotation...
    Run In VM And Check    sudo openssl genrsa -out /tmp/rotated-cert.key 2048    30
    Run In VM And Check    sudo openssl req -new -key /tmp/rotated-cert.key -out /tmp/rotated-cert.csr -subj "/CN=rotated-cert"    30
    Run In VM And Check    bash -c "echo 'subjectAltName = DNS:localhost' > /tmp/rotated-cert-ext.cnf"    10
    Run In VM And Check    sudo openssl x509 -req -in /tmp/rotated-cert.csr -CA /tmp/ca.crt -CAkey /tmp/ca.key -CAcreateserial -out /tmp/rotated-cert.crt -days 365 -extfile /tmp/rotated-cert-ext.cnf    30
    ${cert}=    Run In VM    sudo base64 -w0 /tmp/rotated-cert.crt    30
    ${key}=    Run In VM    sudo base64 -w0 /tmp/rotated-cert.key    30
    Run In VM And Check    sudo microceph certificate set rgw --ssl-certificate="${cert.stdout.strip()}" --ssl-private-key="${key.stdout.strip()}" --restart    120
    Wait For RGW    1
    Wait For RGW SSL Port
    ${cn}=    Get RGW SSL CN
    Should Be Equal As Strings    ${cn}    rotated-cert    msg=Expected CN=rotated-cert after --restart
    Run In VM And Check    sudo openssl genrsa -out /tmp/rotated-cert-2.key 2048    30
    Run In VM And Check    sudo openssl req -new -key /tmp/rotated-cert-2.key -out /tmp/rotated-cert-2.csr -subj "/CN=rotated-cert-2"    30
    Run In VM And Check    bash -c "echo 'subjectAltName = DNS:localhost' > /tmp/rotated-cert-2-ext.cnf"    10
    Run In VM And Check    sudo openssl x509 -req -in /tmp/rotated-cert-2.csr -CA /tmp/ca.crt -CAkey /tmp/ca.key -CAcreateserial -out /tmp/rotated-cert-2.crt -days 365 -extfile /tmp/rotated-cert-2-ext.cnf    30
    ${cert2}=    Run In VM    sudo base64 -w0 /tmp/rotated-cert-2.crt    30
    ${key2}=    Run In VM    sudo base64 -w0 /tmp/rotated-cert-2.key    30
    Run In VM And Check    sudo microceph certificate set rgw --ssl-certificate="${cert2.stdout.strip()}" --ssl-private-key="${key2.stdout.strip()}"    60
    Sleep    3s
    ${cn}=    Get RGW SSL CN
    Should Be Equal As Strings    ${cn}    rotated-cert    msg=Old cert should still be served without restart
    Run In VM And Check    sudo snap restart microceph.rgw    60
    Wait For RGW    1
    Wait For RGW SSL Port
    ${cn}=    Get RGW SSL CN
    Should Be Equal As Strings    ${cn}    rotated-cert-2    msg=Expected rotated-cert-2 after manual restart
    ${orig_cert}=    Run In VM    sudo base64 -w0 /tmp/server.crt    30
    ${orig_key}=    Run In VM    sudo base64 -w0 /tmp/server.key    30
    Run In VM And Check    sudo microceph certificate set rgw --ssl-certificate="${orig_cert.stdout.strip()}" --ssl-private-key="${orig_key.stdout.strip()}" --restart    120
    Wait For RGW    1
    Wait For RGW SSL Port

Test SSL Certificate Rotation With Target
    [Documentation]    Tests RGW SSL certificate rotation with --target flag.
    [Arguments]    ${target}
    Log To Console    [rgw] Testing certificate rotation with --target ${target}...
    ${addr_result}=    Run In VM    sudo microceph status | grep -F "${target}" | grep -oP '\\(\\K[^)]+' || true    30
    ${target_addr}=    Set Variable    ${addr_result.stdout.strip()}
    Run In VM And Check    sudo openssl genrsa -out /tmp/target-cert.key 2048    30
    Run In VM And Check    sudo openssl req -new -key /tmp/target-cert.key -out /tmp/target-cert.csr -subj "/CN=target-cert"    30
    Run In VM And Check    bash -c "echo 'subjectAltName = DNS:localhost' > /tmp/target-cert-ext.cnf"    10
    Run In VM And Check    sudo openssl x509 -req -in /tmp/target-cert.csr -CA /tmp/ca.crt -CAkey /tmp/ca.key -CAcreateserial -out /tmp/target-cert.crt -days 365 -extfile /tmp/target-cert-ext.cnf    30
    ${cert}=    Run In VM    sudo base64 -w0 /tmp/target-cert.crt    30
    ${key}=    Run In VM    sudo base64 -w0 /tmp/target-cert.key    30
    Run In VM And Check    sudo microceph certificate set rgw --ssl-certificate="${cert.stdout.strip()}" --ssl-private-key="${key.stdout.strip()}" --target ${target} --restart    120
    Wait For RGW    1
    Wait For RGW SSL Port    ${target_addr}
    ${cn}=    Get RGW SSL CN    ${target_addr}
    Should Be Equal As Strings    ${cn}    target-cert    msg=Expected CN=target-cert on ${target}
    ${orig_cert}=    Run In VM    sudo base64 -w0 /tmp/server.crt    30
    ${orig_key}=    Run In VM    sudo base64 -w0 /tmp/server.key    30
    Run In VM And Check    sudo microceph certificate set rgw --ssl-certificate="${orig_cert.stdout.strip()}" --ssl-private-key="${orig_key.stdout.strip()}" --target ${target} --restart    120
    Wait For RGW    1
    Wait For RGW SSL Port    ${target_addr}

Test SSL Certificate Set When Not Running
    [Documentation]    Verifies that certificate set fails when RGW is not running.
    Log To Console    [rgw] Verifying certificate set fails when RGW is not running...
    Run In VM And Check    sudo microceph disable rgw    60
    Sleep    3s
    ${cert}=    Run In VM    sudo base64 -w0 /tmp/server.crt    30
    ${key}=    Run In VM    sudo base64 -w0 /tmp/server.key    30
    Run In VM Must Fail    sudo microceph certificate set rgw --ssl-certificate="${cert.stdout.strip()}" --ssl-private-key="${key.stdout.strip()}"

Test IPv6 Monitor Address Formatting
    [Documentation]    Reinstalls with IPv6 mon-ip and verifies square brackets in ceph.conf.
    [Arguments]    ${mon_ip}=fd42:7273:f336:a22::1
    Log To Console    [mon] Testing IPv6 monitor address formatting...
    Run In VM And Check    sudo snap remove microceph    300
    ${iface_result}=    Run In VM    ip route show default | awk '/default via/ {print $5}' | head -1    30
    ${iface}=    Set Variable    ${iface_result.stdout.strip()}
    Log To Console    [mon] Adding IPv6 address to interface ${iface}...
    Run In VM And Check    sudo ip -6 addr add dev ${iface} ${mon_ip}    30
    Install And Bootstrap MicroCeph    ${mon_ip}
    ${result}=    Run In VM    grep -F "[${mon_ip}]" /var/snap/microceph/current/conf/ceph.conf    30
    Should Be Equal As Integers    ${result.rc}    0    msg=IPv6 address ${mon_ip} not wrapped in brackets in ceph.conf

Verify Ceph Config Has Public Network
    [Documentation]    Checks that all nodes' ceph.conf contains public_network entry.
    Log To Console    [config] Verifying all nodes have public_network in ceph.conf...
    ${nodes}=    Run In VM    lxc ls -c n --format csv    30
    FOR    ${node}    IN    @{nodes.stdout.strip().split('\n')}
        Run In VM And Check    lxc exec ${node.strip()} -- sh -c "grep -q public_network /var/snap/microceph/current/conf/ceph.conf"    30
    END

# ---------------------------------------------------------------------------
# Multi-node specific helpers
# ---------------------------------------------------------------------------

Check Client Configs
    [Documentation]    Sets cluster-wide and per-host client configs, then verifies and resets.
    Log To Console    [config] Checking client config set/reset across nodes...
    Run In Container    node-wrk0    microceph client config set rbd_cache true    30
    FOR    ${id}    IN    1    2
        ${size}=    Evaluate    512 * ${id}
        Run In Container    node-wrk${id}    microceph client config set rbd_cache_size ${size} --target node-wrk${id}    30
    END
    FOR    ${id}    IN    1    2
        ${size}=    Evaluate    512 * ${id}
        ${r1}=    Run In VM    lxc exec node-wrk${id} -- sh -c "cat /var/snap/microceph/current/conf/ceph.conf | grep -c 'rbd_cache = true'"    30
        ${r2}=    Run In VM    lxc exec node-wrk${id} -- sh -c "cat /var/snap/microceph/current/conf/ceph.conf | grep -c 'rbd_cache_size = ${size}'"    30
        Should Be Equal As Strings    ${r1.stdout.strip()}    1    msg=rbd_cache not set on node-wrk${id}
        Should Be Equal As Strings    ${r2.stdout.strip()}    1    msg=rbd_cache_size not set on node-wrk${id}
    END
    Run In Container    node-wrk0    microceph client config reset rbd_cache --yes-i-really-mean-it    30
    Run In Container    node-wrk0    microceph client config reset rbd_cache_size --yes-i-really-mean-it    30
    FOR    ${id}    IN    1    2
        ${r1}=    Run In VM    lxc exec node-wrk${id} -- sh -c "cat /var/snap/microceph/current/conf/ceph.conf | grep -c 'rbd_cache '"    30
        ${r2}=    Run In VM    lxc exec node-wrk${id} -- sh -c "cat /var/snap/microceph/current/conf/ceph.conf | grep -c 'rbd_cache_size'"    30
        Should Be Equal As Strings    ${r1.stdout.strip()}    0    msg=rbd_cache still in ceph.conf on node-wrk${id}
        Should Be Equal As Strings    ${r2.stdout.strip()}    0    msg=rbd_cache_size still in ceph.conf on node-wrk${id}
    END

Test Service Migration
    [Documentation]    Migrates services from src to dst and verifies placement.
    [Arguments]    ${src}    ${dst}
    Log To Console    [cluster] Migrating services from ${src} to ${dst}...
    Run In Container    node-wrk0    microceph cluster migrate ${src} ${dst}    120
    FOR    ${i}    IN RANGE    8
        ${src_ok}=    Run In VM    lxc exec node-wrk0 -- sh -c "microceph status | grep -F -A 1 ${src} | grep -qE '^ {2}Services: osd$' && echo yes || echo no"    30
        ${dst_ok}=    Run In VM    lxc exec node-wrk0 -- sh -c "microceph status | grep -F -A 1 ${dst} | grep -qE '^ {2}Services: mds, mgr, mon$' && echo yes || echo no"    30
        IF    "${src_ok.stdout.strip()}" == "yes" and "${dst_ok.stdout.strip()}" == "yes"
            Log To Console    [cluster] Services migrated successfully
            BREAK
        END
        Sleep    10s
    END
    Run In Container    node-wrk0    microceph status    30
    Run In Container    node-wrk0    microceph.ceph -s    30
    ${src_ok}=    Run In VM    lxc exec node-wrk0 -- sh -c "microceph status | grep -F -A 1 ${src} | grep -qE '^ {2}Services: osd$' && echo yes || echo no"    30
    ${dst_ok}=    Run In VM    lxc exec node-wrk0 -- sh -c "microceph status | grep -F -A 1 ${dst} | grep -qE '^ {2}Services: mds, mgr, mon$' && echo yes || echo no"    30
    Should Be Equal As Strings    ${src_ok.stdout.strip()}    yes    msg=${src} should have only OSD after migration
    Should Be Equal As Strings    ${dst_ok.stdout.strip()}    yes    msg=${dst} should have mds,mgr,mon after migration

Enable Services On Node
    [Documentation]    Enables mon/mds/mgr services on specified node.
    [Arguments]    ${node}
    Log To Console    [cluster] Enabling mon/mds/mgr on ${node}...
    FOR    ${svc}    IN    mon    mds    mgr
        Run In VM And Check    sudo microceph enable ${svc} --target ${node}    120
    END
    FOR    ${i}    IN RANGE    8
        ${result}=    Run In VM    sudo microceph.ceph -s | grep -q "mon: .*daemons.*${node}" && echo yes || echo no    30
        IF    "${result.stdout.strip()}" == "yes"    BREAK
        Sleep    2s
    END
    Run In VM And Check    sudo microceph.ceph -s    30

Remove Node
    [Documentation]    Removes specified node from the cluster.
    [Arguments]    ${node}
    Log To Console    [cluster] Removing node ${node}...
    Run In VM And Check    sudo microceph cluster remove ${node}    120
    FOR    ${i}    IN RANGE    8
        ${result}=    Run In VM    sudo microceph.ceph -s | grep -q "mon: .*daemons.*${node}" && echo yes || echo no    30
        IF    "${result.stdout.strip()}" != "yes"    BREAK
        Sleep    5s
    END
    Sleep    1s
    Run In VM And Check    sudo microceph.ceph -s    30
    Run In VM And Check    sudo microceph status    30

# ---------------------------------------------------------------------------
# NFS operations
# ---------------------------------------------------------------------------

Get Node IP
    [Documentation]    Returns the primary IP of a container (first address from hostname -I).
    [Arguments]    ${container}
    ${result}=    Run In VM    lxc exec ${container} -- bash -c 'hostname -I' | cut -d ' ' -f1    30
    RETURN    ${result.stdout.strip()}

Mount NFS In VM
    [Documentation]    Mounts an NFS share from ${ip}:${export} at ${mountpoint} on the outer VM.
    [Arguments]    ${ip}    ${export}    ${mountpoint}
    Run In VM And Check    sudo mount -t nfs -o rw "${ip}:${export}" ${mountpoint}    30

Write File In VM
    [Documentation]    Writes ${content} to ${path} on the outer VM using sudo tee.
    [Arguments]    ${path}    ${content}
    Run In VM And Check    echo "${content}" | sudo tee ${path}    10

File In VM Should Contain
    [Documentation]    Asserts that ${path} on the outer VM contains ${text}.
    [Arguments]    ${path}    ${text}
    Run In VM And Check    cat ${path} | grep -F "${text}"    10

Enable NFS
    [Arguments]    ${cluster_id}
    Log To Console    [nfs] Enabling NFS cluster ${cluster_id}...
    Run In VM And Check    sudo microceph enable nfs --cluster-id ${cluster_id} --wait    120

Disable NFS
    [Arguments]    ${cluster_id}
    Log To Console    [nfs] Disabling NFS cluster ${cluster_id}...
    Run In VM And Check    sudo microceph disable nfs --cluster-id ${cluster_id}    60

Create NFS FS Volume
    [Arguments]    ${volume_name}
    Log To Console    [nfs] Creating CephFS volume ${volume_name}...
    Run In VM And Check    sudo microceph.ceph fs volume create ${volume_name}    120

Create NFS Export
    [Arguments]    ${cluster_id}    ${fsname}
    Log To Console    [nfs] Creating NFS export for ${cluster_id}/${fsname}...
    Run In VM And Check    sudo microceph.ceph nfs export create cephfs ${cluster_id} /${fsname}dir ${fsname}    60

# ---------------------------------------------------------------------------
# Upgrade helpers
# ---------------------------------------------------------------------------

Upgrade Multi Node
    [Documentation]    Upgrades all 4 inner containers to the local snap build.
    Log To Console    [upgrade] Upgrading all nodes to local snap build...
    FOR    ${container}    IN    node-wrk0    node-wrk1    node-wrk2    node-wrk3
        Log To Console    [upgrade] Upgrading ${container}...
        Run In VM And Check    lxc exec ${container} -- sh -c "sudo snap install --dangerous /mnt/microceph_*.snap"    600
        Run In VM And Check    lxc exec ${container} -- sh -c "snap connect microceph:block-devices && snap connect microceph:hardware-observe && snap connect microceph:mount-observe"    60
        Sleep    15s
        FOR    ${i}    IN RANGE    36
            ${res}=    Run In VM    lxc exec ${container} -- sh -c "microceph.ceph osd status 2>/dev/null | grep -c 'exists,up' || echo 0"    30
            ${count}=    Evaluate    int('${res.stdout.strip()}') if '${res.stdout.strip()}'.isdigit() else 0
            IF    ${count} >= 3    BREAK
            Sleep    10s
        END
        ${res}=    Run In VM    lxc exec ${container} -- sh -c "microceph.ceph osd status 2>/dev/null | grep -c 'exists,up' || echo 0"    30
        ${count}=    Evaluate    int('${res.stdout.strip()}') if '${res.stdout.strip()}'.isdigit() else 0
        Should Be Equal As Integers    ${count}    3    msg=Expected 3 OSD up after upgrading ${container}
    END

Refresh Multi Node Snap
    [Documentation]    Refreshes all 4 inner containers from the Snap Store channel.
    [Arguments]    ${channel}
    FOR    ${container}    IN    node-wrk0    node-wrk1    node-wrk2    node-wrk3
        Run In VM And Check    lxc exec ${container} -- sudo snap refresh microceph --channel ${channel}    300
    END

# ---------------------------------------------------------------------------
# Multi-site replication helpers
# ---------------------------------------------------------------------------

Bootstrap Two Sites
    [Documentation]    Bootstraps sitea (node-wrk0/1) and siteb (node-wrk2/3) each with 2 loop-file OSDs.
    ...    Used by both RBD and CephFS replication suites.
    Log To Console    [replication] Bootstrapping sitea (node-wrk0/1)...
    Run In Container    node-wrk0    microceph cluster bootstrap    120
    Run In Container    node-wrk0    microceph disk add loop,1G,2    120
    ${tok}=    Run In VM    lxc exec node-wrk0 -- microceph cluster add node-wrk1    60
    Run In Container    node-wrk1    microceph cluster join ${tok.stdout.strip()}    120
    Run In Container    node-wrk1    microceph disk add loop,1G,2    120
    Sleep    10s
    Log To Console    [replication] Bootstrapping siteb (node-wrk2/3)...
    Run In Container    node-wrk2    microceph cluster bootstrap    120
    Run In Container    node-wrk2    microceph disk add loop,1G,2    120
    ${tok2}=    Run In VM    lxc exec node-wrk2 -- microceph cluster add node-wrk3    60
    Run In Container    node-wrk3    microceph cluster join ${tok2.stdout.strip()}    120
    Run In Container    node-wrk3    microceph disk add loop,1G,2    120
    Sleep    10s

Exchange Remote Site Tokens
    [Documentation]    Exports tokens from each site and imports them cross-site with --local-name.
    ...    After this call, sitea knows siteb and siteb knows sitea.
    Log To Console    [replication] Exchanging site tokens...
    ${sitea_token}=    Run In VM    lxc exec node-wrk0 -- microceph cluster export siteb    60
    ${siteb_token}=    Run In VM    lxc exec node-wrk2 -- microceph cluster export sitea    60
    Run In Container    node-wrk0    microceph remote import siteb ${siteb_token.stdout.strip()} --local-name=sitea    60
    Run In Container    node-wrk2    microceph remote import sitea ${sitea_token.stdout.strip()} --local-name=siteb    60
    Sleep    15s    reason=Allow remote credentials to propagate across the cluster

Verify Remote Authentication On All Nodes
    [Documentation]    Verifies ceph commands against the remote cluster work on all 4 nodes.
    Log To Console    [replication] Verifying remote authentication on all nodes...
    Run In Container    node-wrk0    microceph.ceph -s    30
    Run In Container    node-wrk0    microceph.ceph -s --cluster siteb --id sitea    30
    Run In VM And Check    lxc exec node-wrk0 -- microceph remote list --json | jq -e 'any(.[]; .name == "siteb")'    30
    Run In Container    node-wrk1    microceph.ceph -s    30
    Run In Container    node-wrk1    microceph.ceph -s --cluster siteb --id sitea    30
    Run In VM And Check    lxc exec node-wrk1 -- microceph remote list --json | jq -e 'any(.[]; .local_name == "sitea")'    30
    Run In Container    node-wrk2    microceph.ceph -s    30
    Run In Container    node-wrk2    microceph.ceph -s --cluster sitea --id siteb    30
    Run In VM And Check    lxc exec node-wrk2 -- microceph remote list --json | jq -e 'any(.[]; .name == "sitea")'    30
    Run In Container    node-wrk3    microceph.ceph -s    30
    Run In Container    node-wrk3    microceph.ceph -s --cluster sitea --id siteb    30
    Run In VM And Check    lxc exec node-wrk3 -- microceph remote list --json | jq -e 'any(.[]; .local_name == "siteb")'    30

Mount CephFS From Container
    [Documentation]    Pulls ceph.conf and keyring from ${container} into /etc/ceph/ on the outer VM,
    ...    then mounts the CephFS volume ${vol} at ${mountpoint}.
    [Arguments]    ${container}    ${mountpoint}    ${vol}
    Run In VM And Check    sudo lxc file pull ${container}/var/snap/microceph/current/conf/ceph.conf /etc/ceph/    30
    Run In VM And Check    sudo lxc file pull ${container}/var/snap/microceph/current/conf/ceph.keyring /etc/ceph/    30
    Run In VM And Check    sudo mkdir -p ${mountpoint}    10
    Run In VM And Check    sudo mount -t ceph :/ ${mountpoint} -o name=admin,fs=${vol}    60

Get Synced Image Count On Node
    [Documentation]    Returns string: total images across all RBD replication entries on ${node}.
    ...    jq expression: '[.[].Images | length] | add // 0'
    [Arguments]    ${node}
    ${result}=    Run In VM    lxc exec ${node} -- sh -c "sudo microceph replication list rbd --json | jq '[.[].Images | length] | add // 0'"    30
    RETURN    ${result.stdout.strip()}

Get Primary Image Count On Node
    [Documentation]    Returns string: count of RBD images where is_primary==true on ${node}.
    [Arguments]    ${node}
    ${result}=    Run In VM    lxc exec ${node} -- sh -c "sudo microceph replication list rbd --json | jq '[.[].Images[] | select(.is_primary==true)] | length'"    30
    RETURN    ${result.stdout.strip()}

Get RBD Mirror Pool Health
    [Documentation]    Returns the summary health string (OK/WARNING/ERROR/UNKNOWN) for ${pool} on ${node}.
    [Arguments]    ${node}    ${pool}
    ${result}=    Run In VM    lxc exec ${node} -- sh -c "sudo microceph.rbd mirror pool status ${pool} --verbose | sed -n 's/^health: //p' | head -1"    30
    ${health}=    Set Variable    ${result.stdout.strip()}
    IF    "${health}" == "${EMPTY}"    RETURN    UNKNOWN
    RETURN    ${health}

Enable Mirror Service On Both Sites
    [Documentation]    Enables the given mirror service (rbd-mirror or cephfs-mirror) on node-wrk0 and node-wrk2.
    [Arguments]    ${service}
    Log To Console    [replication] Enabling ${service} on both sites...
    Run In Container    node-wrk0    microceph enable ${service}    120
    Run In Container    node-wrk2    microceph enable ${service}    120

Disable Mirror Service On Both Sites
    [Documentation]    Disables the given mirror service on node-wrk0 and node-wrk2.
    [Arguments]    ${service}
    Log To Console    [replication] Disabling ${service} on both sites...
    Run In Container    node-wrk0    microceph disable ${service}    60
    Run In Container    node-wrk2    microceph disable ${service}    60

# ---------------------------------------------------------------------------
# Single-node test helpers
# ---------------------------------------------------------------------------

Verify Mount Check
    [Documentation]    Verifies that adding a mounted root device fails with "is currently mounted",
    ...    even when --wipe is specified. Mirrors actionutils.sh verify_mount_check.
    Log To Console    [disk] Testing mount check...
    ${rootdev}=    Run In VM    findmnt --noheadings --output SOURCE /    30
    ${err}=    Run In VM    sudo microceph disk add --wipe ${rootdev.stdout.strip()} 2>&1 || true    30
    Should Contain    ${err.stdout}    is currently mounted    msg=Expected mount check failure for ${rootdev.stdout.strip()}

Test RGW Stale Run Dir Migration
    [Documentation]    Injects a stale run dir into radosgw.conf, restarts the snap, and verifies
    ...    the daemon repairs the config to use the stable 'current' symlink.
    ...    Mirrors actionutils.sh test_rgw_stale_run_dir_migration.
    Log To Console    [rgw] Testing RGW stale run dir migration...
    Run In VM And Check    sudo sed -i 's|run dir = .*|run dir = /var/snap/microceph/1/run|' /var/snap/microceph/current/conf/radosgw.conf    10
    Run In VM And Check    grep "run dir" /var/snap/microceph/current/conf/radosgw.conf    10
    Run In VM And Check    sudo snap stop microceph    120
    Run In VM And Check    sudo snap start microceph    60
    Wait For RGW    1
    Run In VM And Check    grep -q "run dir = /var/snap/microceph/current/run" /var/snap/microceph/current/conf/radosgw.conf    10

# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

Clear IPTables
    [Documentation]    Clears Docker-injected iptables FORWARD rules inside the outer VM.
    Run In VM And Check    sudo iptables -P FORWARD ACCEPT || true    10
    Run In VM And Check    sudo ip6tables -P FORWARD ACCEPT || true    10
    Run In VM And Check    sudo iptables -F FORWARD || true    10
    Run In VM And Check    sudo ip6tables -F FORWARD || true    10

Free Runner Disk
    [Documentation]    Removes large packages from the outer VM to reclaim disk space.
    Run In VM And Check    sudo rm -rf /usr/local/lib/android /usr/local/.ghcup; imgs=$(sudo docker images -q 2>/dev/null || true); [ -n "$imgs" ] && sudo docker rmi $imgs || true    120

Install Hurl
    [Documentation]    Installs hurl HTTP test runner (v5.0.1) on the outer VM.
    Log To Console    [setup] Installing hurl...
    Run In VM And Check    bash -c "curl --location --remote-name https://github.com/Orange-OpenSource/hurl/releases/download/5.0.1/hurl_5.0.1_amd64.deb && sudo dpkg -i ./hurl_5.0.1_amd64.deb"    120

Prepare Disk API Hurl Fixtures
    [Documentation]    Creates loop devices and lists disks for hurl API tests.
    Log To Console    [setup] Preparing disk API hurl fixtures...
    Create Loop Devices
    Run In VM And Check    sudo microceph disk list --json    30

Run Hurl
    [Documentation]    Runs a hurl test file against the MicroCeph control socket.
    [Arguments]    ${hurl_file}
    Log To Console    [hurl] Running ${hurl_file}...
    Run In VM And Check    sudo hurl --unix-socket /var/snap/microceph/common/state/control.socket --test ${hurl_file}    120
