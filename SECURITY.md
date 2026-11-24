# Security policy

## Key material

- The project's bootloader signing keys and `hmac.bin` are **not** in this
  repository. Never add them.
- The keys are the only way to produce a bootloader this device will run. Keep
  them encrypted and offline, with at least two independent backups.
- The public keys in `henr1kas/Exynos` are sample keys from a public repository.
  They produce a different ST2 index (`0x3fbd5ba3`) and are **not** trusted by a
  device fused to the project key (`0x3e96f623`).
- Do not paste keys, `hmac.bin`, or firmware into issues, discussions, CI logs,
  or chat. Redact device serials, Chip ID/DID values, MACs, and IPs.

## The fuse is irreversible

Burning the custom key cannot be undone. Never flash a stock Samsung bootloader
and never take a One UI OTA. Read [Recovery first](docs/recovery-first.md).

## Reporting a problem

This is a personal research project with no security team. If you find a
problem, open a private security advisory on the repository rather than a public
issue, and include only the minimum reproduction details.

## Scope

The repository contains documentation, host-side scripts, and build tooling. It
does not ship firmware, images, or signing keys. Do not test the instructions on
a device you cannot recover through the EUB test point.

The strict risk and liability disclaimer is in
[docs/risks.md](docs/risks.md). The short version: the fuse is irreversible, the
device can be bricked, the work voids warranty and security guarantees, and
there is no support.
