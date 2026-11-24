# Decisions

Decisions that shape the project, with the reasoning that is easy to lose.
Dates are approximate; the evidence is in the histories and designs.

## ADR-001: Use the recovery slot as the host

**Decision:** all Linux work targets the `recovery` partition. The `boot` slot
is not used.

**Why:** the `boot` slot aborts at the bootloader DT stage, while recovery boots
reliably. The recovery ramdisk already contains a kernel, modules, and a UI; the
Linux root lives on `userdata`, so reflashing recovery does not touch the OS.

**Consequence:** every image is a recovery image. The `boot` slot remains a
known-broken path and is documented as such.

## ADR-002: Burn a custom bootloader key

**Decision:** fuse the BootROM to the project key (ST2 index `0x3e96f623`) and
sign every bootloader with the matching private keys.

**Why:** the stock chain refuses every modified bootloader. A custom key makes
the chain reproducible and independent of Samsung signatures.

**Consequence:** the fuse is irreversible. The private keys are the only way to
produce a bootable bootloader, and they must never be published. A stock
Samsung bootloader can never be restored.

## ADR-003: Never flash a stock bootloader or take a One UI OTA

**Decision:** treat stock bootloader components as forbidden.

**Why:** the BootROM no longer trusts Samsung's key. A stock BL is rejected; an
OTA that writes one can leave the device unbootable except through EUB.

**Consequence:** every future BL change is built and signed from the project
keys. The EUB test point remains the rescue path.

## ADR-004: One monorepo, no images or keys

**Decision:** publish one repository containing the guide, Linux build tree,
unlock tooling, designs, and history. It contains no firmware, recovery images,
signed bootloaders, private keys, or `hmac.bin`.

**Why:** the knowledge is the durable artifact. The artifacts are large,
proprietary, device-specific, and dangerous to redistribute. One repository
keeps the story and the code together.

**Consequence:** the guide records versions and hashes instead of files. Readers
must obtain firmware and generate their own keys.

## ADR-005: Enter the Linux root with `switch_root` semantics

**Decision:** bind the Debian root, `mount --move` it onto the namespace root,
then `chroot`.

**Why:** mounting the new root at an inner path leaves `..` walking back into
the recovery tree and makes `create_user_ns()` return `EPERM`. Moving the root
to the namespace root fixes both.

**Consequence:** container `..` clamps at the container root, and `docker
export` contains no host paths. `pivot_root` from recovery's `rootfs` remains
unusable; the helper is a `switch_root`-style move.

## ADR-006: No PID namespace in the launcher

**Decision:** the launcher does not create a PID namespace.

**Why:** Docker's `userns-remap` needs to create user namespaces, and runc's
`nsexec` is refused when the daemon runs inside a nested PID namespace.
Containers still get their own PID namespace from runc.

**Consequence:** sshd and dockerd share the recovery init's PID namespace;
`r9s-server stop` stops dockerd explicitly.

## ADR-007: No `userns-remap`

**Decision:** run Docker without `userns-remap`.

**Why:** the 5.4 kernel cannot mount or bind cgroup2 inside a user namespace, so
enabling remapping breaks container creation rather than adding isolation.

**Consequence:** isolation comes from the root entry, not UID mapping. Container
data ownership must match the image runtime user.

## ADR-008: Hybrid cgroup v2 with a v1 `devices` controller

**Decision:** use cgroup v2 for cpuset/cpu/io/memory/pids and a v1 `devices`
cgroup alongside it.

**Why:** Docker 29 needs a devices controller, and this 5.4 kernel does not
provide one in cgroup v2.

**Consequence:** the launcher mounts the v1 `devices` hierarchy after the pivot;
`iptables-legacy` is required because `CONFIG_NFT_NAT` is off.

## ADR-009: DHCP by default

**Decision:** the Ethernet watcher uses DHCP unless `/data/linux/net.conf`
exists.

**Why:** the router can reserve an address by MAC, and static addressing created
a second source of truth.

**Consequence:** the old static config is kept as `net.conf.static.bak` for
rollback; the watcher survives replugs and sets the clock via NTP.

## ADR-010: Text-first documentation

**Decision:** the guide is Markdown with ASCII diagrams. Binary images are not
required to understand it.

**Why:** it stays readable in a terminal, diffs cleanly, and does not rot when a
screenshot host disappears.

**Consequence:** the only binary build asset is `linux/assets/logo_sonofanton.png`,
which the recovery build verifies; it is not guide content.

## ADR-011: Keep OpenSpec local, export the designs

**Decision:** the planning machinery stays outside the published repository; the
design documents are exported to `docs/design/`.

**Why:** the OpenSpec tree contains planning metadata and identifiers that are
irrelevant to a reader. The designs are the durable result.

**Consequence:** `docs/design/` is the public record; the change history remains
local.
