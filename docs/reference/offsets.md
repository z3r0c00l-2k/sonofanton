# Offsets

Raw offsets in the extracted bootload (`bootload.bin`) unless stated otherwise.
They are firmware-specific; verify against your own image before writing.

## ABL patch sites

| Feature | Offsets |
|---|---|
| signature / secure-download flag | `0x67f88`, flag `0xbeed28` |
| warranty fuse | `0x63380`, `0x65c00` |
| SW / kernel / system / PIT rollback | `0x650d0`, `0x66378`, `0x65e88`, `0x66500` |
| SEAndroid enforcing | `0x63430` |
| AVB ops reader | `0x96cc8` |
| unlock reader | `0x641d8` |
| secure-download value / gate | `0x668b8`, `0xa9e0` |
| DT revision fallback | `0x5e754`, `0x5e764`, `0x5e798`, `0x5e7a0` |
| live bit-3 gate | `0x609ac` |
| recovery rollback gate | `0x958f8`, `0x95a84` |
| recovery secure gate | `0x67214` |
| keypad recovery combo | `0x207588` |
| OEM unlock gate | `0x66930`, `0x66958` |
| executor nops | `0x669d0`, `0x669dc`, `0x669f0` |
| force recovery boot | `0x2b24` → `0xc624c` → `0x2f80` |

## DT stage

| Item | Address / offset |
|---|---|
| validator | `0x5e9c0` |
| DTBO pointer | `[0xbeb518]` |
| DTB pointer | `[0xbeb520]` |
| header version read | `0x94000028` |
| DTBO magic | `0x1eabb7d7` (`d7 b7 ab 1e`) |
| DTBO size limit | `0x08000000` |
| DT entry lookup | `0x5e6f8` |

## Signing and packaging

| Item | Offset |
|---|---|
| BL1 payload | `+0x2000` (stock region zero; code ends `+0x1643`) |
| custom efuse commitment | payload `+0x130` |
| bootload signature footer / ST2 index | `bootload + 0x2a2dfc` |
| dpm splice | `sboot.bin + 0xea000` (after signing) |
| tar terminator | 2048 zero bytes before the md5 footer |

## `param`

`0x700000` env, `0x700200` boot mode, `0x703b00` marker id.

## Related

- [ABL patching](../unlock/03-abl-patching.md)
- [DT stage](../unlock/07-dt-and-recovery.md)
- [Signing](../unlock/05-signing.md)
