# 02 — EUB

EUB (Emergency USB Boot) is the BootROM-level rescue path. It is the reason a
broken UFS bootloader is not a brick, and the reason the signing keys must be
kept offline.

## USB modes

| Mode | VID:PID | Purpose |
|---|---|---|
| EUB / BootROM | `04e8:1100` | upload the RAM chain |
| Old DNW | `04e8:1234` | legacy tooling |
| Download | `04e8:685d` | download-mode session |

Add all three to the host udev rules. On systems without a `dialout` group, use
`GROUP="users"` (the original host needed this).

## What the RAM chain is

The EUB payload is a small boot chain that runs from RAM before UFS is touched:

```
EPBL -> BL2 -> Bootloader -> EL3_MON -> LDFW -> TZSW
```

Once the chain reports ready, the device enters download mode (`04e8:685d`) and
accepts a normal download-mode session. The EUB path is also how the fuse payload is
executed on a device that has not been fused yet.

## Session tools

The project scripts live in `tools/unlock/eub/`:

| Script | Role |
|---|---|
| `eub_chain.py` | resolves the chain directory and prints a sha256 per component |
| `eub_session.py` … `eub_session5.py` | the proven session driver; `5` is the current one |
| `continue_chain.py` | continues an existing session (including the download-mode handoff) |
| `continue_epbl.py` | continues from EPBL |
| `serve_requests.py` | serves the chain over the protocol |

`EUB_SERVE_ROOT=<dir>` overrides the chain directory. `eub_chain.py report`
prints the resolved directory and component hashes; use it before a session so a
transcript proves which build was served.

## The session contract

The chain is sensitive to readiness and short writes. The driver:

1. waits for the `C` readiness signal,
2. sends each component in order,
3. handles short-write continuation recovery,
4. verifies the chain reports `[USB Booting Done]`,
5. leaves the device in download mode.

Do not race the stages. The 22:49 session failure in the history was a race, not
a payload defect.

## Fusing is a separate decision

Embedding the payload and signing a bootloader is reversible. **Burning the
fuse is not.** Read [Keys and fuse](04-keys-and-fuse.md) before running a chain
whose payload has `should_fuse_key` enabled. The project's own device is already
fused; its later builds use `EUB_SHOULD_FUSE_KEY=0`.

## If EUB fails

- Confirm the test point is the correct one and the device is powered off.
- Confirm the host sees `04e8:1100`; a different PID means the device is already
  in download mode or the cable is wrong.
- Confirm the chain directory is the one you think it is: `eub_chain.py report`.
- Confirm the payload is intact: `verify_chain.py session <sboot.bin>`.
- A black device with no USB enumeration is usually a power/charge issue; charge
  first, then retry.

## Related

- [Recovery first](../recovery-first.md)
- [Keys and fuse](04-keys-and-fuse.md)
- [History: the EUB sessions](../history/runbook.md)
