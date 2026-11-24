# 05 — Signing and packaging

> Third-party tools and authors: [CREDITS](../../CREDITS.md).

The build pipeline turns a stock Samsung BL package into a custom-key-signed
chain. Order matters: the BL1 payload is covered by the signature, and the dpm
splice happens after signing.

## Pipeline

```
stock BL tar
   |
   v
split.py s5e9840 <indir> <workdir>
   |
   v
patch bootload.bin       (NHZF5 and/or IGYI3)
   |
   v
embed BL1 payload at +0x2000   # before signing
   |
   v
build.py s5e9840 ../keys <workdir> [RB]
   |
   v
sign BL1 again if the payload was embedded after the first sign
   |
   v
splice stock dpm.img into sboot.bin at 0xea000   # after signing
   |
   v
lz4 frame + tar + md5 footer
```

## Split and patch

Use the pinned Exynos tooling:

```bash
git clone https://github.com/henr1kas/Exynos.git
cd Exynos
python3 scripts/split.py s5e9840 ../input ../output
EUB_SHOULD_FUSE_KEY=0 python3 ../tools/unlock/patchers/patch_9840.py \
    ../output/sboot/bootload.bin
# or the IGYI3 variant:
python3 ../tools/unlock/patchers/patch_9840_igyi3.py \
    ../output/sboot/bootload.bin
```

The stock input partitions are not in this repository. Supply your own and
verify them against [versions](../reference/versions.md).

## BL1 payload

The custom-key payload goes into BL1 at `+0x2000`:

```bash
python3 tools/unlock/patchers/embed_bl1_payload.py <workdir>/sboot/bl1.bin
```

The region is zero in the stock BL1. If the payload is omitted, the device has no
display and no download mode; only EUB remains (v17).

## Sign

```bash
cd Exynos
python3 scripts/build.py s5e9840 ../keys ../output 23
```

`23` is the rollback count (`RB`), matching the device's eFuse value
(`bootloader_rp = 0x17`). Signing an older base with a lower count can be
rejected.

BL1 must be signed **after** the payload is embedded. The inner header checksum
covers `bl1[0x10:]`, and the ST1 signature covers the payload bytes:

```bash
python3 scripts/sign.py ../output/sboot/bl1.bin ../keys st1 --signing-type 4
```

## dpm splice

The pipeline re-signs `dpm.img`. Splice the stock `dpm` into the merged
`sboot.bin` at `0xea000` **after** signing. The v20–v27 shipped tars (including
the flashed v22) instead carried the pipeline-signed dpm in both places; v28
mirrors that. The stock-splice rule remains the cleaner target but was not the
variable that broke v22.

## lz4 and tar

Samsung/Odin expect an lz4 **frame** container:

- magic `04 22 4d 18`
- `FLG=0x6c` (content size present)
- block-size nibble matching the stock member (`sboot` `0x60` = 1 MiB,
  `vbmeta` `0x40`)

`lz4 -l` (legacy) is rejected as `invalid lz4`.

The tar must use the stock member names and order, end with **2048 zero bytes**
(the tar terminator), and append a full md5 line:

```
<32 hex>  <filename>.tar
```

A bare md5 hash is rejected by Odin as `md5 is invalid`. A missing terminator
stalls at `File analysis` (v9).

## Verify

```bash
python3 tools/unlock/verify/verify_chain.py image   <sboot.bin>
python3 tools/unlock/verify/verify_chain.py packed  <tar.md5> --expect-image <sboot.bin>
python3 tools/unlock/verify/verify_chain.py confinement <stock_bootload> <built_bootload>
python3 tools/unlock/verify/verify_chain.py session <sboot.bin>
```

The `image` check verifies the patch contracts, BL1 payload, and ST2 key index.
The `packed` check verifies member count and md5. `confinement` compares the
bootload region against stock; only patch sites and the signing trailer may
differ.

## Related

- [Keys and fuse](04-keys-and-fuse.md)
- [Flashing](06-flashing.md)
- [vbmeta](08-vbmeta.md)
- [Build ladder](10-build-ladder.md)
