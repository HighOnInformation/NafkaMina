#!/usr/bin/env bash
# export-image.sh — build dirdiff, export it for air-gap transfer, and verify it
# on the far side.
#
#   ./export-image.sh export        build and save dirdiff.tar.gz + .sha256
#   ./export-image.sh verify        check the tarball against its checksum
#   ./export-image.sh load          verify, then load into the local daemon
#   ./export-image.sh selftest      run the packaged test suite inside the image
#
# Copy the tarball, the .sha256 file AND this script to the closed network:
# `verify` is the only thing standing between a corrupt USB transfer and a
# report you would have trusted.

set -euo pipefail

IMAGE="${DIRDIFF_IMAGE:-dirdiff}"
TARBALL="${DIRDIFF_TARBALL:-dirdiff.tar.gz}"
CHECKSUM="$TARBALL.sha256"

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

need_docker() {
    command -v docker > /dev/null 2>&1 || die "docker is not installed or not on PATH"
    docker info > /dev/null 2>&1 || die "cannot talk to the docker daemon (is it running, are you in the docker group?)"
}

# sha256sum on Linux, shasum on macOS. Neither is guaranteed; fail loudly rather
# than silently skipping the integrity check.
sha_tool() {
    if command -v sha256sum > /dev/null 2>&1; then echo "sha256sum"
    elif command -v shasum > /dev/null 2>&1; then echo "shasum -a 256"
    else die "no sha256sum or shasum available — cannot verify the transfer"
    fi
}

do_export() {
    need_docker
    echo "==> building $IMAGE"
    docker build -t "$IMAGE" .

    echo "==> saving $TARBALL"
    docker save "$IMAGE" | gzip > "$TARBALL"

    echo "==> writing $CHECKSUM"
    $(sha_tool) "$TARBALL" > "$CHECKSUM"

    echo
    echo "Built $TARBALL ($(du -h "$TARBALL" | cut -f1))"
    echo "Transfer these three files to the closed network:"
    echo "    $TARBALL"
    echo "    $CHECKSUM"
    echo "    $(basename "$0")"
    echo "Then run:  ./$(basename "$0") load"
}

do_verify() {
    [ -f "$TARBALL" ]  || die "$TARBALL not found"
    [ -f "$CHECKSUM" ] || die "$CHECKSUM not found — cannot verify this transfer"
    echo "==> verifying $TARBALL"
    $(sha_tool) --check "$CHECKSUM" || die "checksum MISMATCH — the transfer is corrupt, do not load this image"
    echo "checksum ok"
}

do_load() {
    do_verify
    need_docker
    echo "==> loading into the local daemon"
    docker load < "$TARBALL"
    cat <<EOF

Loaded. Verify the packaged suite still passes on this box:

    ./$(basename "$0") selftest

Then compare two directories. --user makes the reports land owned by you
instead of by root:

    mkdir -p out
    docker run --rm --user "\$(id -u):\$(id -g)" \\
      -v "\$PWD/v1:/work/v1:ro" \\
      -v "\$PWD/v2:/work/v2:ro" \\
      -v "\$PWD/config.json:/work/config.json:ro" \\
      -v "\$PWD/out:/work/out" \\
      $IMAGE v1 v2 -c config.json \\
        -o out/report.md -H out/report.html -j out/report.json \\
      2> out/report.warnings

Read out/report.warnings first: warnings never appear in the report, and some
of them change how much you should trust it.
EOF
}

do_selftest() {
    need_docker
    echo "==> running the packaged suite inside the image"
    docker run --rm --entrypoint python "$IMAGE" \
        -m unittest discover -s /opt/dirdiff/tests
    echo "==> checking the bundled tools"
    docker run --rm --entrypoint sh "$IMAGE" -c \
        'git --version && clang-format --version && gcc --version | head -1'
}

case "${1:-export}" in
    export)   do_export ;;
    verify)   do_verify ;;
    load)     do_load ;;
    selftest) do_selftest ;;
    -h|--help|help)
        sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
        ;;
    *) die "unknown command '${1}' — try: export | verify | load | selftest" ;;
esac
