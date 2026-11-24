# 04 — Keys and fuse

The device is fused to a custom key. This chapter explains the key layout, the
one index that matters, and the irreversible step. **No keys or `hmac.bin` are
in this repository.**

## Key layout

The signing set is a directory shaped like the Exynos tooling expects:

```
keys/
├── 4/
│   ├── st1.pem      # ST1 signing key (unencrypted private key)
│   ├── st2t.pem     # ST2 transition key
│   └── st2r.pem     # ST2 root key
└── hmac.bin         # 32-byte secret used for the efuse commitment
```

The project keys are **not** the public keys shipped in the Exynos repository.
They produce different ST2 indexes:

| Key set | ST2 index | Trusted by this device? |
|---|---|---|
| Project `keys/4/*.pem` + project `hmac.bin` | `0x3e96f623` | **yes** |
| Public `Exynos/keys` | `0x3fbd5ba3` | no — the chain halts |

`verify_chain.py image <sboot.bin>` checks the index at the bootload signature
footer. If it reports `0x3fbd5ba3`, you signed with the wrong key set.

## The hmac and the efuse commitment

`hmac.bin` is 32 bytes. The custom payload embeds a commitment derived from the
ST1 public key and the hmac:

```
efuse = HMAC-SHA512(hmac_key, st1_public_key[:136])[:32] XOR hmac_key
```

That 32-byte value is written at payload offset `+0x130`. The payload itself is
embedded into BL1 at `+0x2000` (the region is zeroed in the stock BL1; the code
ends at `+0x1643`). The shipped Exynos payload embeds the **repo** keys'
commitment, which is why it cannot be used with the project keys.

## Generating keys for a new device

1. Generate the three keys in the `keys/4/` layout and a random 32-byte
   `hmac.bin`. Keep them off the device and out of any repository.
2. Build a payload whose `+0x130` commitment matches your ST1 public key and
   hmac.
3. Verify the resulting ST2 index **before** fusing. A wrong index produces a
   chain that the BootROM rejects with no display and no download mode.
4. Fuse only when you are prepared to lose the ability to run any other key.
5. Back up the keys and hmac offline, encrypted, in at least two places.

If you are not prepared to fuse, stop here. Building and signing images is
reversible; burning the fuse is not.

## The fuse step

The fuse payload is part of the ABL patch set (`fuse_boot_key`, patch 18). It
writes the ROM secure boot key to slot 2 and switches the selectors. The fuse is
executed by the bootload in the EUB RAM chain, seconds after the chain is
uploaded.

- Default behaviour of the patch script is to include the fuse payload.
- The project's device is already fused; its later builds use
  `EUB_SHOULD_FUSE_KEY=0` so the payload never runs again.
- The fuse value must be byte-identical to the EUB payload's efuse; the project
  verified this before burning.

## Signing keys are not a secret in the public Exynos sample set

The public `Exynos/keys` private keys are published by the upstream project.
They are useful as a layout reference but they are **not** a trust anchor for
this device. Do not fuse a device to a key whose private half is public unless
you accept that anyone can sign a bootloader for it.

## Storage rules

- Never commit `keys/`, `keys_backup_*/`, `*.pem`, or `hmac.bin`.
- Never paste them into an issue, chat, CI log, or shell history.
- Keep the backup encrypted and offline; the same disk is not a backup.
- The repository's `.gitignore` and CI secret scan are the safety net, not the
  primary control.

## Related

- [Signing](05-signing.md)
- [EUB](02-eub.md)
- [Verification](../reference/checksums.md)
