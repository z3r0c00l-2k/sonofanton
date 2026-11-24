# Checksums

Hashes are fingerprints, not artifacts. No image, tar, or firmware file is stored
in this repository. The full build ledger is
[`linux/out/SHA256SUMS`](../../linux/out/SHA256SUMS), which records every
candidate that was built, flashed, or kept as rollback.

## Known-good images

| Artifact | SHA-256 |
|---|---|
| `baseline/LOS_recovery.img` | `06bb5c2a0b363f4af16e027aa795b4f6655d7b3a0a4c2e8adc41875878ec4152` |
| `out/RECOVERY_r9s_server_v9.img` | `640e8c3fc3e928ae6d98025c39ed15b6207827df07997e40c5c595edcdee7ea5` |
| `out/RECOVERY_r9s_server_v9.tar` | `a81cee36d586fe49aa69d84308302ffffbc894e370fe8e02b12b6f7fc711c03e` |
| `out/RECOVERY_r9s_server_v9.tar.md5` | `cb84ee8f27eed1d4a4ab5b1ff3f5563e07e0777b43cd698044a269f2769acc20` |
| `out/RECOVERY_r9s_server_v10.img` | `ba8d4f61d3d30ce1b26342c6e78e341a5d949f53b5f493dbd59d901f681075f5` |
| `out/RECOVERY_r9s_server_v10.tar` | `4a9e14a9925a3643fbb5411d9532821330aec599aa9d4f2cbad01a3844a53145` |
| `out/RECOVERY_r9s_server_v10.tar.md5` | `4d910d572353234cc597bd1c17d8fd4bd66722f3776a5761d80632c37bec0ab3` |

## Bootloader builds

| Artifact | Hash |
|---|---|
| v28 BL tar md5 | `f5adad3532017704f4db9bc0d4d9745d` |
| v28 `sboot_v28.bin` sha256 | prefix `4172ae38`, suffix `a847` (recorded in the patch inventory) |
| v22 BL tar | see the history; previous known-good chain |

The v28 tar is flashed and running. Ordinary power-on selects recovery. The v22
chain remains the known-good fallback.

## Firmware families

The exact firmware hashes depend on the package you obtain. The repository's
`baseline/manifest.txt` and the history record the hashes observed during the
build. Verify a locally obtained copy against the source you trust; do not trust
a hash copied from a web page without checking the provenance.

## Verifying a build

```bash
sha256sum -c linux/out/SHA256SUMS
```

Files that are intentionally absent (images, tars, firmware) will fail the check;
that is expected. The ledger is a record, not a downloadable set.
