# Keys

This directory is intentionally empty of key material.

The unlock chain needs:

```
keys/
├── 4/
│   ├── st1.pem
│   ├── st2t.pem
│   └── st2r.pem
└── hmac.bin         # 32 random bytes
```

Generate your own keys in this layout and keep them outside the repository. The
public sample keys in `henr1kas/Exynos` are **not** the project keys and produce a
different ST2 index.

- Project keys: `0x3e96f623` (trusted by this device)
- Public Exynos keys: `0x3fbd5ba3` (rejected by this device)

See [Keys and fuse](../../../docs/unlock/04-keys-and-fuse.md) for the index check,
the hmac/efuse commitment, the fuse warning, and storage rules.

Do not add files here. The root `.gitignore` already excludes `keys/`, `*.pem`,
and `hmac.bin`.
