# Recovery logo

The menu header is a bitmap, not text. `recovery_ui/screen_ui.cpp` loads
`res/images/logo_image_switch.png` when `ro.boot.dynamic_partitions` is set (this
device) and `res/images/logo_image.png` otherwise, both from the recovery
ramdisk, and draws the result 1:1, horizontally centred, at the top of the
screen.

So a custom logo is a file replacement. Nothing in the C++ changes, and it needs
no recovery rebuild — `tools/make_launcher_ramdisk.py` injects
`assets/logo_sonofanton.png` over both files.

```bash
python3 tools/make_logo.py --name "Your Name"   # or design it yourself
tools/build-recovery.sh --no-build server_vN    # inject, sign, gate, package
```

The shipped asset is a custom design (769×480, white caption). `tools/make_logo.py`
regenerates the project's original wordmark variant in the stock style — note
that it *overwrites* `assets/logo_sonofanton.png`.

## Hard constraints (verified in the decoder)

| rule | why |
| --- | --- |
| PNG, **8 bits per channel** | `minui/resources.cpp` rejects every other depth with `minui doesn't support PNG depth …` |
| **RGB (3 channels)** — no alpha | an RGBA file fails the same check (4 channels), the bitmap never loads, and the header comes up missing |
| palette or 8-bit grayscale also decode | they are expanded to RGB at load time, but `tRNS` is dropped, so transparent palette entries become whatever colour they name |
| paint the background | `gr_blit` is a `memcpy` into the framebuffer: there is no alpha blending, so "transparent" pixels are not composited with anything |
| no interlacing | nothing in the loader calls `png_set_interlace_handling` |

The stock image is 8-bit RGB for these reasons, and so is
`assets/logo_sonofanton.png`.

## Geometry

The panel is 1080×2340 and recovery draws at native resolution, so 1 image pixel
is 1 screen pixel:

| item | value |
| --- | --- |
| canvas | 768×480 (stock); the shipped custom art is 769×480 |
| horizontal placement | centred: 768 wide leaves 156 px of black either side |
| vertical placement | `y = 0`; the logo is the first thing drawn, no top margin |
| space it costs | the menu title, menu items, and the battery/link row all start at `y = 480` |
| safe height | up to ~600 px still leaves room; 480 is one fifth of the panel |
| max useful width | 1080; nothing is scaled, and a centred image wider than the screen starts at `x < 0`, where `gr_blit` skips it entirely |

The logo is drawn whenever a menu is on screen — including the log viewer opened
from a menu item, which keeps the menu object alive underneath its text.
Progress/animation screens have no menu and therefore no logo. fastbootd has its
own `res/images/fastbootd.png` (also 768×480, also not currently replaced).

## Palette and legibility

Taken from the stock wordmark, and worth keeping so the header still looks like
recovery:

| element | value |
| --- | --- |
| background | `#000000` (the UI clears to black) |
| frame | `#7c4dff`, 5 px stroke, 72 px corner radius; the stock frame spans `(1,129)–(766,350)`, this project insets it to `(3,129)–(765,350)` |
| caption | `#f891ff`, 40 px bold, 12 px letter spacing, top around `y = 383` |
| title text | `#ffffff`, 76 px bold, centred in the frame |

Because it is drawn at 1:1 on a 1080 px wide panel:

- type smaller than ~24 px is hard to read from arm's length; the name uses 76 px
- strokes thinner than ~3 px disappear into the black at a glance
- keep at least 8 px clear inside the frame, and 24 px clear at the bottom edge,
  which sits immediately above the first menu line
- the battery, charge state and Ethernet link are drawn at the right edge of the
  line *below* the image, so the bottom-right corner of the artwork needs no
  headroom

## Checking a design before flashing

```bash
python3 - <<'PY'
from PIL import Image
im = Image.open("assets/logo_sonofanton.png")
assert im.mode == "RGB", f"must be RGB, not {im.mode}"
assert im.size == (768, 480), im.size
print("ok", im.mode, im.size)
PY
```

Then `tools/build-recovery.sh --no-build …` — it refuses to package unless the
shipped `res/images/logo_image_switch.png` is byte-identical to
`assets/logo_sonofanton.png`, which catches a forgotten injection or a design
saved with the wrong mode.
