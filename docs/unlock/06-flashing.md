# 06 — Flashing

The device accepts a Samsung BL tar through Odin in download mode. The same
package format is used for recovery images.

## Before you flash

- Battery above the floor; do not flash at low charge.
- The image is signed with **your** project keys and carries `RB >= 23`.
- The tar has the stock member order, the 2048-byte terminator, and the md5
  footer.
- `verify_chain.py packed` passes.
- The EUB test point is accessible and you know the rescue path.
- You are not flashing a stock Samsung bootloader or an OTA.

## Download mode

1. Power off.
2. Hold Vol+ and Vol−, then connect USB-C.
3. The host should see `04e8:685d`.
4. Use Odin with the BL tar in the appropriate slot.

The recovery image is flashed to the recovery slot; the boot slot is not used.
After the flash, **cold boot** with the power key only. A warm reboot can latch
the previous boot mode.

## Package shape

```
BL_<device>_<tag>.tar.md5
├── member order copied from the stock package
├── sboot.bin / sboot.bin.lz4
├── keystorage, ldfw, tzsw, harx, ...
├── 2048 zero bytes (tar terminator)
└── <md5>  <filename>.tar\n
```

The tar is deterministic enough to compare across builds; `package_odin.sh`
produces the md5 footer and the Linux image pipeline appends hashes to
`out/SHA256SUMS`.

## Verify on the host

```bash
sha256sum -c out/SHA256SUMS
python3 tools/unlock/verify/verify_chain.py packed <tar.md5> \
  --expect-image <sboot.bin> --expect-members <N>
```

## Verify on the device

- The recovery slot boots to the project launcher.
- The kernel string matches the built kernel.
- The module vermagic matches the kernel.
- `r9s-server status` reports the expected state.
- Docker can create a container.

## Rollback

- Keep the untouched recovery image and the last known-good BL tar offline.
- The v28 BL is flashed and running; ordinary power-on selects recovery. v22
  remains the known-good fallback.
- A failed BL flash is recoverable through EUB; a stock BL is not.
- Never overwrite the bootloader with a Samsung-signed component.

## If the flash fails

| Symptom | Likely cause |
|---|---|
| Odin stalls at `File analysis` | missing tar terminator or wrong member order |
| `md5 is invalid` | bare hash or wrong footer |
| `invalid lz4` | legacy lz4 frame or wrong block size |
| `SW REV. CHECK FAIL` | image rollback count below the device eFuse |
| `SECURE CHECK FAIL : (SUPER)` | live bit-3 gate not patched (see chapter 03) |
| No display, no download mode | BL1 payload missing or wrong key; use EUB |

## Related

- [Recovery first](../recovery-first.md)
- [Signing](05-signing.md)
- [Failures](09-failures.md)
