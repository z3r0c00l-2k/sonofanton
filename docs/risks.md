# Risks and disclaimer

> **This project can permanently destroy the device. It is not a reversible mod,
> a supported product, or a normal OEM-unlock guide. Read this page before you
> run anything.**

## The short version

```
one-way fuse
    |
    +--> only project-key-signed bootloaders will ever run
    +--> a stock Samsung bootloader can never be restored
    +--> losing the keys means no future bootloader can be built
    |
    +--> EUB test point is the only rescue path
    +--> a failed write can leave only that path
```

## Why this route exists

The stock base is One UI 8.0 / Android 16. One UI 8 no longer exposes the OEM
unlocking path: the toggle is absent and the bootloader reports
`androidboot.other.locked=1`. The normal "enable OEM unlocking, unlock, flash"
route is therefore unavailable, which is why this project uses the recovery slot
and a custom-key fused bootloader. That is also why the risks below are
unavoidable rather than optional.

## Risk table

| Risk | Severity | What it means |
|---|---|---|
| Irreversible bootloader fuse | **critical** | Burning the custom key cannot be undone. There is no stock BL fallback. |
| Lost signing keys | **critical** | The keys and `hmac.bin` are the only way to sign a bootloader this device accepts. Lose them and no future BL can be built. |
| Hard brick | **critical** | A bad write can leave a device that only the EUB test point can recover. If the test point is inaccessible or the RAM chain is wrong, the device may be unrecoverable. |
| Stock BL or OTA | **critical** | A Samsung-signed BL is rejected by the fused BootROM. A One UI OTA can leave the device unbootable. |
| Data loss | **high** | The documented route reformats `userdata` as unencrypted f2fs and retires Android. Back up anything you care about first. |
| Device-specific instructions | **high** | Offsets, firmware, keys, rollback counts, and the fuse are specific to this model and firmware. Do not follow blindly on another device. |
| Security downgrade | **high** | Verified boot is disabled, the bootloader is custom, the kernel is 5.4 (EOL), and the device is no longer a secure daily driver. Do not store sensitive data on it. |
| Charging / USB / test-point damage | **high** | Opening the device, probing the test point, or flashing at low charge can damage hardware. Use the charge guard and a known-good cable. |
| Warranty, carrier, and Knox | **high** | Unlocking and flashing can void warranty, break carrier features, and trip Knox/KnoxGuard. The device may be refused by banking or enterprise apps. |
| Legal / anti-circumvention | **medium–high** | Bootloader modification may violate terms of service or local law. This is not legal advice; you are responsible for your jurisdiction. |
| No support or updates | **medium** | Samsung does not support this configuration. The project has no security team, no update commitment, and no liability. |
| Key exposure | **high** | If the signing keys or `hmac.bin` leak, someone with physical access can sign a bootloader this device trusts. Keep them offline and encrypted. |

## What you are accepting

By following this guide you accept that:

- The fuse is one-way and the device may become unusable.
- The authors provide **no warranty**, no support, and no guarantee of
  recoverability.
- You are responsible for backing up data and for complying with the law,
  warranty, carrier, and service terms that apply to you.
- The device is not a secure phone after this work. Do not use it for banking,
  personal data, or anything that depends on verified boot.
- The EUB test point and the signing keys are part of the recovery plan; if
  either is unavailable, do not proceed.

## What this repository does not provide

- No firmware, recovery images, or signed bootloaders.
- No private keys, `hmac.bin`, or key backups.
- No guarantee that a build here will boot on your device or firmware.
- No legal advice or permission to bypass a lock.

If any of the above is unacceptable, stop here and do not flash anything.
