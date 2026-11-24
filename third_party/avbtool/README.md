# avbtool

Vendored copy of the Android Verified Boot command-line tool, moved out of
`linux/tools/` so its provenance and license are explicit.

- Source: AOSP `external/avb/avbtool.py`
- File header: the AOSP MIT-style permission notice, retained in the file
- Use: `info_image`, `add_hash_footer`, and signature inspection by
  `linux/tools/repack.py`

The file is unmodified apart from its location. If you update it, record the
AOSP revision in `third_party/NOTICE.md`.
