#!/usr/bin/env python3
"""Single source of truth for the EUB-served bootloader chain.

`eub_session5.py` (full session) and `continue_chain.py` (phase-C continuation)
serve the same chain, so they must not resolve it independently - they used to
disagree (`igyi3_out/` vs `output/`), which means a transcript could not prove
which build was actually served.

Resolution order:

1. the `EUB_SERVE_ROOT` environment variable, when set (use it to serve a
   candidate build, e.g. the reduced chain from group 5);
2. `DEFAULT_SERVE_ROOT`, the proven download-mode-serving chain.

`report()` prints the resolved directory and a sha256 per component, so a serve
transcript identifies the build it served.
"""

import hashlib
import os

SERVE_ENV = "EUB_SERVE_ROOT"
# Neutral default for a public checkout; set EUB_SERVE_ROOT to select a build.
DEFAULT_SERVE_ROOT = "output"

# component name -> path relative to the serve root
COMPONENTS = {
    "bl1": "sboot/bl1.bin",
    "epbl": "sboot/epbl.bin",
    "bl2": "sboot/bl2.bin",
    "bootload": "sboot/bootload.bin",
    "el3_mon": "sboot/el3_mon.bin",
    "ldfw": "ldfw/ldfw.bin",
    "tzsw": "tzsw/tzsw.bin",
}

# the request/upload order the device asks for, after bl1 (sent in the exploit)
CHAIN = ["epbl", "bl2", "bootload", "el3_mon", "ldfw", "tzsw"]


def resolve_serve_root(env=None):
    env = os.environ if env is None else env
    return env.get(SERVE_ENV) or DEFAULT_SERVE_ROOT


def files_for(root=None):
    root = resolve_serve_root() if root is None else root
    return {name: os.path.join(root, rel) for name, rel in COMPONENTS.items()}


def sha256(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def report(root=None, stream=print):
    """Print the resolved serve root and per-component hashes; return the map."""
    root = resolve_serve_root() if root is None else root
    files = files_for(root)
    stream(f"[serve] chain root: {root} "
           f"(env {SERVE_ENV} overrides; default {DEFAULT_SERVE_ROOT})")
    for name, path in files.items():
        try:
            stream(f"[serve]   {name:9s} {path}  sha256={sha256(path)}")
        except OSError as exc:
            stream(f"[serve]   {name:9s} {path}  MISSING ({exc})")
    return files
