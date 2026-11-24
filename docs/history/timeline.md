# Timeline

A short chronology. The full evidence is in [runbook.md](runbook.md).

| Date | Milestone |
|---|---|
| 2026-10-09 | First custom BL flashes; v2/v4 prove the flash path and expose the lz4 dialect |
| 2026-10-10 | `DT Load Fail` root-caused from the binary; v5–v8 reduce the chain and find the executor/ABI defects |
| 2026-10-12 | v8–v13 quantify the ABI defects, the tar terminator, and the real Secure Download blocker; control plane pinned |
| 2026-10-12 | v10 flashes and the unlock fires; every boot still aborts at the DT stage |
| 2026-10-19 | Stock-boot restore investigated; AVB root of trust identified |
| 2026-10-27 | v22 known-good; recovery boots; kernel rebuild with container delta |
| 2026-11-06 | Server image v9: Debian 13.7, SSH, Docker, Hermes, Hawser |
| 2026-11-07 | Network moved to DHCP; media stack added; security audit |
| 2026-11-18 | Cpuset cap removed in the kernel source; Camoufox restored; monorepo planned |
| 2026-11-18 | Monorepo export created; guide and tooling migrated; publication checks pending |

## Reading the history

- [runbook.md](runbook.md) — the chronological log, redacted for publication.
- `blogs/` — the narrative blog is kept locally and is intentionally not
  tracked in Git.
- [../unlock/09-failures.md](../unlock/09-failures.md) — the distilled
  do-not-repeat list.
