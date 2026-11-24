# Tests

Synthetic host-side tests only. No firmware, images, or Samsung binaries belong
in this tree.

- `tests/unlock/` — parser and contract fixtures for the unlock tools.
- `tests/linux/` — host-side helpers for the Linux build pipeline.

Run them from the repository root:

```
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The fixtures are generated in memory or in a temporary directory. The unlock
test builds the instruction window the patch locator matches, so it proves the
patch and the verifier agree without carrying a bootloader image.

The full build and device tests are documented in
[`docs/linux/build.md`](../docs/linux/build.md) and
[`docs/unlock/05-signing.md`](../docs/unlock/05-signing.md); they need the
toolchain and a device, so they are not part of CI.
