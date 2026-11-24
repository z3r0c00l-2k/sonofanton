# Contributing

This repository is primarily a personal knowledge base. Contributions that
improve accuracy, clarity, or reproducibility are welcome.

## Ground rules

- **Never commit** private keys, `hmac.bin`, key backups, firmware, recovery
  images, signed bootloaders, raw logs with identifiers, or device serials.
- Use placeholder values in examples: `<phone-ip>`, `<device-serial>`,
  `<chip-id>`, `<mac>`.
- Keep the guide text-first. Use ASCII diagrams; do not require screenshots.
- Do not add a prebuilt image or a vendor blob. Link to the source and record the
  pinned revision and hash instead.

## Documentation

- Put unlock material under `docs/unlock/`, Linux material under `docs/linux/`,
  and reference data under `docs/reference/`.
- Link to deeper evidence instead of duplicating a long explanation.
- Update [docs/status.md](docs/status.md) when a claim changes from unverified to
  verified, or the reverse.

## Code

- Run the checks before opening a change:

```bash
python3 -m py_compile $(git ls-files '*.py')
bash -n $(git ls-files '*.sh')
```

- Keep device-specific values as arguments or environment variables, not
  hardcoded constants.
- Add a synthetic fixture when a parser or patcher needs a test; never commit a
  Samsung binary.

## Pull requests

Describe the device, firmware, and build tag you tested. If the change came from
a real device run, include the redacted command and the result. If it is
documentation-only, say so.
