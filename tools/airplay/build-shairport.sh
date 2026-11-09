#!/bin/bash
# Cross-compiles shairport-sync (AirPlay 1 only) as a static soft-float MIPS binary.
# Normally run by ../../build.sh inside a Docker container, with the work directory at /w.
#
# Expects in the mounted /w:
#   /w/x/root   toolchain copied out of muslcc/x86_64:mipsel-linux-muslsf (bin/gcc etc.)
#   /w/dl/{shairport-sync,libconfig,mbedtls,popt-popt-1.19-release}
set -e

mkdir -p /w/x/wrap
for t in gcc g++ ar ranlib strip nm ld objdump; do
  printf '#!/bin/sh\nexec /w/x/root/bin/%s "$@"\n' "$t" > /w/x/wrap/mipsel-linux-muslsf-$t
  chmod +x /w/x/wrap/mipsel-linux-muslsf-$t
done

export PATH=/w/x/wrap:$PATH
H=mipsel-linux-muslsf
CC=$H-gcc
FL="-Os -march=mips32r2 -mtune=24kc -msoft-float -D_GNU_SOURCE -w"
PF=/w/p
mkdir -p $PF/include $PF/lib/pkgconfig $PF/obj

# popt (its release tarball has no configure script, so compile directly)
cd /w/dl/popt-popt-1.19-release/src
cat > config.h <<'CH'
#define PACKAGE "popt"
#define VERSION "1.19"
#define PACKAGE_NAME "popt"
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_UNISTD_H 1
#define HAVE_FCNTL_H 1
#define HAVE_FLOAT_H 1
#define HAVE_LIBGEN_H 1
#define HAVE_FNMATCH_H 1
#define HAVE_GLOB_H 1
#define HAVE_LANGINFO_H 1
#define HAVE_STPCPY 1
#define HAVE_STRERROR 1
#define HAVE_VASPRINTF 1
#define HAVE_SRANDOM 1
#define HAVE_SETREUID 1
#define POPT_SYSCONFDIR "/etc"
CH
for f in popt poptconfig popthelp poptint poptparse; do
  $CC $FL -DHAVE_CONFIG_H -I. -c $f.c -o $PF/obj/$f.o
done
$H-ar rcs $PF/lib/libpopt.a $PF/obj/popt*.o
cp popt.h $PF/include/

# libconfig (generated parser files are checked in)
cd /w/dl/libconfig/lib
for f in libconfig grammar scanner scanctx strbuf strvec util; do
  [ -e $f.c ] && $CC $FL -DLIBCONFIG_STATIC -I. -c $f.c -o $PF/obj/cfg_$f.o
done
$H-ar rcs $PF/lib/libconfig.a $PF/obj/cfg_*.o
cp libconfig.h $PF/include/

# mbedtls 2.28 LTS
cd /w/dl/mbedtls
make -C library clean >/dev/null 2>&1 || true
CC=$CC AR=$H-ar RANLIB=$H-ranlib CFLAGS="$FL" make -j12 -C library static >/dev/null 2>&1
cp library/libmbed*.a $PF/lib/
cp -r include/mbedtls include/psa $PF/include/

for n in popt:popt libconfig:config; do
  a=${n%:*}; l=${n#*:}
  printf 'Name: %s\nDescription: %s\nVersion: 1\nCflags: -I%s/include\nLibs: -L%s/lib -l%s\n' $a $a $PF $PF $l > $PF/lib/pkgconfig/$a.pc
done
export PKG_CONFIG_PATH=$PF/lib/pkgconfig PKG_CONFIG_LIBDIR=$PF/lib/pkgconfig

# shairport-sync: AirPlay 1, built-in integer ALAC decoder, stdout output, built-in mDNS
cd /w/dl/shairport-sync
[ -x configure ] || autoreconf -fi
ac_cv_func_malloc_0_nonnull=yes ac_cv_func_realloc_0_nonnull=yes \
CFLAGS="$FL -I$PF/include" CPPFLAGS="-I$PF/include" LDFLAGS="-static -no-pie -L$PF/lib" \
LIBS="-lmbedtls -lmbedx509 -lmbedcrypto" \
  ./configure --host=$H --with-ssl=mbedtls --with-stdout --with-pipe --with-tinysvcmdns --with-pkg-config \
    --without-ffmpeg --with-hammerton
make -j12
$H-strip shairport-sync
ls -la shairport-sync
