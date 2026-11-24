#!/usr/bin/env bash
# Build the r9s kernel from the recovered baseline configuration plus the
# container delta. Produces build/arch/arm64/boot/Image and the module set.
#
#   JOBS=8 tools/build-kernel.sh            # configure + build
#   tools/build-kernel.sh --config-only     # stop after the config gate
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KERNEL="$ROOT/sources/kernel-samsung-universal2100"
OUT="$ROOT/build"
JOBS="${JOBS:-8}"
FRAGMENT="$ROOT/configs/docker.config"

export PATH="$ROOT/tools/host/bin:$PATH"   # local bc
mkdir -p "$OUT"

# Pinned toolchain, vendor-style: CLANG_PREBUILT_BIN on PATH, CC/LD explicit.
# Kernel and modules must come from one toolchain: mismatched clang versions
# disagree on CFI type-id hashes and __cfi_check fails at module load.
TOOLCHAIN="${TOOLCHAIN:-}"
if [ -n "$TOOLCHAIN" ]; then
  export PATH="$TOOLCHAIN/bin:$PATH"
  export CLANG_PREBUILT_BIN="$TOOLCHAIN/bin"
  export CC=clang LD=ld.lld AR=llvm-ar NM=llvm-nm OBJCOPY=llvm-objcopy STRIP=llvm-strip
  echo "== toolchain: $TOOLCHAIN"
  clang --version | head -1
  ld.lld --version | head -1
else
  echo "== toolchain: system"
  clang --version | head -1
fi

CFI_PERMISSIVE="${CFI_PERMISSIVE:-1}"

# Build-compat patches against the vendor tree (idempotent).
for p in "$ROOT"/patches/*.patch; do
  [ -e "$p" ] || continue
  if git -C "$KERNEL" apply --reverse --check "$p" 2>/dev/null; then
    echo "== patch already applied: $(basename "$p")"
  else
    git -C "$KERNEL" apply "$p"
    echo "== applied patch: $(basename "$p")"
  fi
done

echo "== baseline config"
cp "$ROOT/baseline/kernel.config" "$OUT/.config"

echo "== applying delta fragment: ${FRAGMENT#$ROOT/}"
cat "$FRAGMENT" >> "$OUT/.config"

if [ "$CFI_PERMISSIVE" = "0" ]; then
  echo "== CFI_PERMISSIVE disabled for this build (testing an enforcing kernel)"
  echo "# CONFIG_CFI_PERMISSIVE is not set" >> "$OUT/.config"
fi

echo "== resolving (olddefconfig, LLVM=1)"
make -C "$KERNEL" ARCH=arm64 O="$OUT" LLVM=1 olddefconfig

echo "== config gate: delta present?"
missing=0
while IFS='=' read -r sym val; do
  case "$sym" in ''|'#'*) continue ;; esac
  if [ "$CFI_PERMISSIVE" = "0" ] && [ "$sym" = "CONFIG_CFI_PERMISSIVE" ]; then
    continue
  fi
  if ! grep -qx "$sym=$val" "$OUT/.config"; then
    echo "  MISSING: $sym=$val"
    missing=1
  else
    echo "  ok: $sym=$val"
  fi
done < <(grep -E '^CONFIG_[A-Z0-9_]+=' "$FRAGMENT")

if [ "$missing" -ne 0 ]; then
  echo "config gate FAILED: at least one delta option did not survive resolution" >&2
  exit 1
fi

if [ "${1:-}" = "--config-only" ]; then
  echo "config only; stopping"
  exit 0
fi

echo "== building Image + modules (-j$JOBS)"
# The vendor Makefile adds a blanket -Werror (Makefile:496). The recorded
# toolchain was clang 21; the available clang is 23, whose new diagnostics
# (e.g. -Wuninitialized-const-pointer) would otherwise abort the build.
# Demote errors to warnings here rather than patching the vendor tree.
make -C "$KERNEL" ARCH=arm64 O="$OUT" LLVM=1 -j"$JOBS" \
     KCFLAGS="-Wno-error" Image modules

echo "== done"
ls -l "$OUT/arch/arm64/boot/Image"
