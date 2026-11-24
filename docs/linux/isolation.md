# Isolation

The Linux root is entered `switch_root`-style, not with a plain `chroot` mounted
at an inner path. The launcher:

1. makes the mount tree private,
2. bind-mounts the Debian root,
3. `mount --move`s it onto the namespace root,
4. `chroot`s into it,
5. drops the old root and starts `sshd`/`dockerd` from the new root.

This is what fixed two separate failures:

| Failure | Cause | Result of the root-entry change |
|---|---|---|
| A container's `..` reached the host root | the new root was a bind mount at a subdirectory, so `..` walked back into the old tree | `..` clamps at the new namespace root |
| `unshare(CLONE_NEWUSER)` returned `EPERM` | the process still lived in the recovery root's mount namespace | user namespaces can be created from the moved root |

## No PID namespace

The launcher deliberately does **not** create a PID namespace. Docker's
`userns-remap` needs to create user namespaces, and runc's `nsexec` is refused
when the daemon runs inside a nested PID namespace. Containers still get their
own PID namespace from runc.

## `userns-remap` is not usable on this kernel

The 5.4 kernel cannot mount or bind the cgroup2 filesystem inside a user
namespace. Enabling `userns-remap` therefore breaks container creation rather
than adding isolation. Isolation comes from the root entry, not from UID
mapping. The daemon configuration is left without `userns-remap`.

## Container boundary

A container's `..` cannot escape its own root, and `docker export` contains only
the container's files (the exported image is about 8.9 MB with no host paths).
Docker data bind ownership must match the image runtime user; Hermes uses
`10000:10000` and must stay that way.

## GPU

`mali_kbase` is loaded and `/dev/mali0` opens, but there is no DRM render node,
no `libEGL`, and no userspace Mali driver. Containers have no GPU access. This
is documented here so it is not mistaken for a regression.
