#!/usr/bin/env bash
# Builds the custom Tivoli Cube firmware from Tivoli's public image and pinned open source code.
# Result: $WORK/cfw/lsimage. Nothing is flashed. Needs: docker, git, curl, python3.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="${WORK:-$ROOT/build}"

FW_URL="https://update.tivoliaudio.org/cube/eu/lsimage"
FW_MD5="d6ce0540eaa4084e393878dda2233247"
SHAIRPORT_SHA="0a34fbda83724cc06266aadcf7c88acc8fef4e7d"
LIBCONFIG_TAG="v1.7.3"
MBEDTLS_TAG="v2.28.8"
POPT_URL="https://github.com/rpm-software-management/popt/archive/refs/tags/popt-1.19-release.tar.gz"
POPT_SHA256="6eb40d650526cb9fe63eb4415bcecdf9cf306f7556e77eff689abc5a44670060"
TOOLCHAIN="muslcc/x86_64:mipsel-linux-muslsf@sha256:ef600e089d5b65302f2038c85d74cac260d51529c1cf3fc6620b7f621a191c28"
BUILDER="rust:latest"  # only used for gcc, make and autotools

USER_ARGS=(--user "$(id -u):$(id -g)")
mkdir -p "$WORK/dl" "$WORK/x/root" "$WORK/cfw"

echo "== Stock firmware"
if [ ! -f "$WORK/dl/lsimage" ]; then
    curl -fsSL --max-time 300 -o "$WORK/dl/lsimage" "$FW_URL"
fi
echo "$FW_MD5  $WORK/dl/lsimage" | md5sum -c - || {
    echo "This firmware is not the known build (p6128). The offsets used here may not apply. Stopping." >&2
    exit 1
}

echo "== Sources"
cd "$WORK/dl"
if [ ! -d shairport-sync/.git ]; then
    git init -q shairport-sync
    git -C shairport-sync remote add origin https://github.com/mikebrady/shairport-sync.git
    git -C shairport-sync fetch -q --depth 1 origin "$SHAIRPORT_SHA"
    git -C shairport-sync checkout -q FETCH_HEAD
fi
[ -d libconfig ] || git clone -q --depth 1 -b "$LIBCONFIG_TAG" https://github.com/hyperrealm/libconfig.git
[ -d mbedtls ] || git clone -q --depth 1 -b "$MBEDTLS_TAG" https://github.com/Mbed-TLS/mbedtls.git
if [ ! -d popt-popt-1.19-release ]; then
    curl -fsSL --max-time 120 -o popt-1.19.tar.gz "$POPT_URL"
    echo "$POPT_SHA256  popt-1.19.tar.gz" | sha256sum -c -
    tar xf popt-1.19.tar.gz
fi

echo "== Toolchain"
if [ ! -e "$WORK/x/root/bin/gcc" ]; then
    docker run --rm --user 0 -v "$WORK/x/root:/out" "$TOOLCHAIN" sh -c \
        "cd / && cp -a bin include lib libexec mipsel-linux-muslsf share usr /out/ && chown -R $(id -u):$(id -g) /out"
fi
echo 'GROUP ( -lgcc_eh )' > "$WORK/x/root/mipsel-linux-muslsf/lib/libunwind.a"

echo "== shairport-sync"
docker run --rm "${USER_ARGS[@]}" -e HOME=/tmp -v "$WORK:/w" -v "$ROOT/tools/airplay:/t" -w /w \
    "$BUILDER" bash /t/build-shairport.sh

echo "== pcmplay"
docker run --rm --network none "${USER_ARGS[@]}" -v "$ROOT/tools/airplay:/src:ro" -v "$WORK:/out" "$TOOLCHAIN" \
    gcc -static -no-pie -s -O2 -march=mips32r2 -msoft-float /src/pcmplay.c -o /out/pcmplay

echo "== Firmware image"
python3 -I "$ROOT/tools/cfw/build_image.py" "$WORK/dl/lsimage" "$WORK/dl/shairport-sync/shairport-sync" \
    "$WORK/pcmplay" "$ROOT/tools/cfw/start-airplay" "$WORK/cfw/lsimage"

echo
echo "Built: $WORK/cfw/lsimage"
