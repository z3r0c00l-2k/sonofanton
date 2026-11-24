# Partitions

The partitions that matter to the unlock and the Linux host. Sizes are not
reproduced here because they vary with the firmware package; use your own
device's GPT/PIT.

| Partition | Role |
|---|---|
| `sboot` | bootloader chain: `bl1`, `bl2`, `el3_mon`, `bootload`, `ldfw`, `tzsw`, `harx`, `keystorage`, `dpm`, … |
| `recovery` | host slot: kernel, modules, recovery ramdisk, launcher |
| `boot` | not usable; aborts at the DT stage |
| `dtbo` | DTBO table; entries keyed by revision (0–16, 17, 18–32) |
| `vbmeta` | Android verified boot metadata |
| `super` | dynamic partitions for stock Android |
| `misc` | BCB; this ABL has no parser for it |
| `userdata` | unencrypted f2fs; Debian root and container data |
| `param` | Samsung environment store |

## `param` layout

| Field | Offset |
|---|---|
| env struct | `0x700000` |
| `param[0]` (boot mode) | `0x700200` |
| marker string id `0x47` | `0x703b00` |

`tools/unlock/patchers/param_bootmode.py get|set {0|4}` reads or writes the boot
mode.

## Boot modes

| `param[0]` | Result |
|---|---|
| `0` | normal boot (v28 redirects this edge to recovery) |
| `4`, `5` | recovery block |
| `6` | restore path (unchanged) |

## Image sizes seen

| Image | Kernel | Ramdisk | Tail |
|---|---|---|---|
| Lineage recovery | 30,673,408 | 25,129,330 → 78,316,032 | 11,300,864 (DTBO table) |
| TWRP | 28,738,048 | 25,492,195 → 88,917,760 | 1,105,936 |
| OrangeFox | 28,738,048 | 34,416,795 → 104,416,768 | 1,105,936 |

The Lineage recovery is the coherent pair (kernel and modules match). TWRP and
OrangeFox carry stock Samsung modules with a different vermagic; only built-in
drivers work there.
