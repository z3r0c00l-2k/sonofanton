# Start here

> **This is not a reversible mod.** The fuse, the keys, and the EUB test point
> are one-way. Read [Risks and disclaimer](risks.md) before any flash.

This is the entry point for the whole project. Pick the path that matches the
device's current state.

## Decision tree

```
Is the device alive?
├── No display, no download mode
│   -> Recovery first: EUB test point
│      docs/recovery-first.md
│
├── Download mode works, recovery does not boot
│   -> Unlock / DT-stage work
│      docs/unlock/07-dt-and-recovery.md
│
├── Recovery boots (the normal state)
│   -> Linux host
│      docs/linux/README.md
│
└── Android boots
    -> Unlock guide
       docs/unlock/README.md
```

## What this project is

```
locked bootloader
      |
      |  EUB + patched ABL + custom-key fuse
      v
custom bootloader  --->  recovery slot  --->  Debian + Docker
                              |
                              +--> Lineage recovery UI (optional)
```

The `boot` slot is not usable on this device. Everything runs from the
`recovery` slot.

## Read in this order

1. [Risks and disclaimer](risks.md) — what can destroy the device and what you
   are accepting.
2. [Recovery first](recovery-first.md) — the rescue path and the two things
   that can make the device unrecoverable.
3. [Status](status.md) — what is actually proven on the device today.
4. [Unlock guide](unlock/README.md) — EUB, ABL patching, keys, signing, flashing.
5. [Linux host](linux/README.md) — kernel, image pipeline, Debian root, Docker.
6. [Reference](reference/versions.md) — versions, hashes, partitions, offsets.

## Designs

- [Ground-up unlock](design/ground-up-unlock.md)
- [DT stage](design/dt-stage.md)
- [Restore stock boot](design/restore-stock.md)
- [Linux kernel](design/linux-kernel.md)

## What is not here

No firmware, recovery images, signed bootloaders, private keys, or `hmac.bin`.
The guide records what to obtain and how to verify it, not the artifacts
themselves.

## If you only read one page

Read [Recovery first](recovery-first.md). The fuse and the EUB test point are the
only things that cannot be undone or rebuilt.
