# Changelog

## 2026-11-25 — public repository

- Published the monorepo as the public `sonofanton` repository, squashed to a
  single initial commit.
- Added host tests for the force-recovery patch contracts and the charge guard.
  CI now runs them and parses the extensionless device scripts.
- Declared the host dependencies in `requirements.txt` and installed them in CI.
- Replaced example LAN addresses with the `192.0.2.0/24` documentation range and
  removed local absolute paths from the docs and the baseline manifest.
- Corrected the `avbtool.py` location to `third_party/avbtool/` and noted where
  the public AOSP test key comes from.

## 2026-11-18 — first public guide

- Created the single `sonofanton` monorepo: guide, unlock tooling, Linux build
  tree, designs, history, story, and reference.
- Imported the sanitized `r9s-linux` history as `linux/`.
- Added the unlock guide (`docs/unlock/`), Linux guide (`docs/linux/`), design
  exports, timeline, and redacted history.
- Added publication boundaries: no firmware, images, signed bootloaders, private
  keys, or `hmac.bin`.
- Recorded the cpuset-cap kernel fix and the DHCP/network state.
- Added documentation and code checks; no image builds.
- Added the One UI 8 OEM-unlock rationale and a strict
  [risks and disclaimer](docs/risks.md) page linked from the guide.
- Added [CREDITS.md](CREDITS.md) with repository and author links for the
  unlock and kernel/device/recovery tools.
- Moved the blog narrative to local-only `blogs/` (ignored by Git).
