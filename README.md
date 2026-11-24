# SonOfAnton II

A Samsung Galaxy S21 FE (SM-G990E, codename `r9s`) running Debian Linux and
containers from its recovery slot. The bootloader is unlocked with a custom key,
the kernel is rebuilt from the pinned Samsung 5.4 tree, and the Linux root lives
on `userdata`.

This repository is the guide, the build system, and the research record in one
place. It deliberately contains **no firmware images, no recovery images, no
signed bootloaders, and no signing keys**.

> **STOP. This project can permanently destroy the device.**
> The bootloader fuse is irreversible, a stock Samsung bootloader or a One UI
> OTA can leave the device unbootable, and the EUB test point is the only rescue
> path. Read [Recovery first](docs/recovery-first.md) and
> [Risks and disclaimer](docs/risks.md) before flashing anything.

## Base device

| Item | Value |
|---|---|
| Model | Samsung Galaxy S21 FE, SM-G990E (`r9s`) |
| SoC | Exynos 2100 (S5E9840) |
| Base OS | Android 16 (API 36) |
| One UI | 8.0 |
| Build ID (PDA) | `G990EXXSNHZF5` |
| Android build fingerprint | `BP2A.250605.031.A3.G990EXXSNHZF5` |
| Security patch | 2026-06-05 |
| CSC | `G990EODMNHZF5` (INS) |
| Bootloader bit | N (23) |
| Base firmware family | NHZF5 |

The project's running chain is built from the NHZF5 base. The IGYI3
(`G990EXXSIGYI3`, One UI 7) generation is used only for the downgrade
experiments described in the unlock history.

## Why this route

The stock base is **One UI 8.0 / Android 16**. One UI 8 no longer offers the
normal bootloader-unlock path: the OEM unlocking toggle is absent, and the
bootloader reports `androidboot.other.locked=1`. On this device the familiar
"enable OEM unlocking, unlock, flash" route is not available (see
[the device chapter](docs/unlock/01-device.md#why-not-oem-unlock)).

This project therefore does not use OEM unlock. It uses the recovery slot with a
custom-key fused bootloader, reached through the EUB test point. That is a
one-way change:

- the fuse cannot be undone;
- the project keys become the only way to build a bootable bootloader;
- a stock Samsung bootloader can never be restored;
- the EUB test point is the only rescue path.

The IGYI3 (One UI 7) generation appears only in the downgrade history. If you
are looking for a normal OEM-unlock guide, this is not it. Read
[Risks and disclaimer](docs/risks.md) before proceeding.

## Phases

| Phase | What it covers | Start |
|---|---|---|
| 0 — Unlock | EUB rescue, ABL patching, keys and fuse, signing, flashing | [docs/unlock/](docs/unlock/README.md) |
| 1 — Recovery | DT stage, Lineage recovery, vbmeta, the launcher | [docs/unlock/07-dt-and-recovery.md](docs/unlock/07-dt-and-recovery.md) |
| 2 — Linux host | kernel, image pipeline, Debian root, Docker, services | [docs/linux/](docs/linux/README.md) |

## Start here

```
Does the device boot?
├── No  -> docs/recovery-first.md   (EUB test point)
├── Recovery only -> docs/linux/    (this is the normal state)
├── Android       -> docs/unlock/   (unlock / recovery work)
└── Need to rebuild the bootloader?
    -> docs/unlock/05-signing.md + 06-flashing.md
```

- New to the project: [docs/start-here.md](docs/start-here.md)
- Risks and disclaimer: [docs/risks.md](docs/risks.md)
- One page of commands: [docs/cheatsheet.md](docs/cheatsheet.md)
- Current state: [docs/status.md](docs/status.md)
- Exact versions and hashes: [docs/reference/versions.md](docs/reference/versions.md)
- What went wrong: [docs/unlock/09-failures.md](docs/unlock/09-failures.md)

## Repository map

| Path | Contents |
|---|---|
| `docs/` | the guide: unlock, Linux, designs, history, story, reference |
| `tools/unlock/` | research patchers, EUB tools, verification, flash helpers |
| `linux/` | the r9s-linux build tree and launcher (history preserved) |
| `third_party/` | license and pinned-source notices |
| `tests/` | synthetic host-side tests |

## Status

The recovery slot runs the rebuilt kernel, Debian 13.7, SSH, Docker, and the
documented services. The `boot` slot does not boot on this device. The remaining
open work is listed in [docs/linux/operations.md](docs/linux/operations.md) and
[docs/status.md](docs/status.md).

## Warnings

- The bootloader is fused to the project key. Never flash a stock Samsung
  bootloader and never take a One UI OTA.
- All Linux work targets the recovery slot.
- No private keys, `hmac.bin`, firmware, or signed images are distributed here.
- Unlocking and flashing can brick the device. There is no warranty.

## Project

- [Credits](CREDITS.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Notice](NOTICE.md)

## License

Documentation is CC-BY-4.0; original code is MIT. Third-party tools are listed in
[NOTICE.md](NOTICE.md) and [third_party/NOTICE.md](third_party/NOTICE.md).
