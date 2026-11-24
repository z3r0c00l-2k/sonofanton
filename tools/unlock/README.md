# Unlock tooling

Research code for the bootloader work: patchers, EUB session drivers,
verification, and flash helpers. It is provided for reproducibility, not as a
supported product.

> **No firmware and no keys.** Supply your own Samsung firmware and generate your
> own keys. This code can brick the device. Read
> [Recovery first](../../docs/recovery-first.md) and
> [Keys and fuse](../../docs/unlock/04-keys-and-fuse.md) before running it.

## Layout

| Path | Contents |
|---|---|
| `patchers/` | `patch_9840.py`, `patch_9840_igyi3.py`, `patch_igyi3_clean.py`, payload and param helpers |
| `verify/` | `verify_chain.py` — patch contracts, BL1 payload, ST2 index, tar/session checks |
| `eub/` | `eub_chain.py`, `eub_session*.py`, continuation and request servers |
| `flash/` | Odin session manifests and recovery helpers |
| `keys/` | generation notes only; no keys |

## Work directory

Host dependencies are in `requirements.txt` (`capstone` for the contract
verifier, `pyusb` for the EUB sessions). Install them with
`python3 -m pip install -r requirements.txt`.

The scripts operate on a work directory you create:

```
work/
├── Exynos/           # pinned clone
├── houston-pub/      # pinned clone
├── input/            # your split firmware images
├── output/           # split and built chain
└── keys/             # your keys, never committed
```

Set `R9S_WORK` to that directory for the helpers that use it. `EUB_SERVE_ROOT`
selects the chain the EUB tools serve; `eub_chain.py report` prints the resolved
directory and per-component hashes.

## Common commands

```bash
# Fetch the two source tools at their pinned revisions
tools/unlock/fetch-externals.sh

# Patch a split bootload
python3 tools/unlock/patchers/patch_9840.py output/sboot/bootload.bin
# or the IGYI3 variant
python3 tools/unlock/patchers/patch_9840_igyi3.py output/sboot/bootload.bin

# Verify a built chain
python3 tools/unlock/verify/verify_chain.py image output/sboot.bin
python3 tools/unlock/verify/verify_chain.py packed out.tar.md5 \
  --expect-image output/sboot.bin --expect-members 12

# Report the EUB chain that would be served
EUB_SERVE_ROOT=output python3 tools/unlock/eub/eub_chain.py report
```

`verify_chain.py` takes `--key-index` (or `R9S_KEY_INDEX`) so the expected ST2
index is not hardcoded to one device. The default is the project device's
`0x3e96f623`; the public Exynos keys produce `0x3fbd5ba3` and are not trusted by
this chain.

## Rules

- Never commit `keys/`, `hmac.bin`, firmware, images, or signed bootloaders.
- Run from a work directory you control; do not run the patchers in place on a
  stock image you cannot replace.
- Keep the EUB test point available.
- A stock Samsung bootloader and a One UI OTA are never valid targets.
