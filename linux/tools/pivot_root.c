/* pivot_root NEWROOT NEWINIT [args...] — switch_root-style entry for the
 * recovery slot.
 *
 * The recovery's / is rootfs. The previous bind+chroot+pivot_root workaround
 * attached the new root at the bind's mountpoint (/.pivotbind), not at "/",
 * so the process stayed "chrooted" relative to the mount namespace root:
 * the kernel's create_user_ns() refuses that with EPERM (no user namespaces,
 * hence no userns-remap), and ".." can cross the mount stack into the host.
 *
 * Moving the new root onto "/" attaches it at the namespace root mountpoint,
 * which is the mount current_chrooted() follows down to. The process then has
 * a normal root: user namespaces work and ".." clamps at "/".
 *
 * Android marks the tree shared, so it is made private first. Run inside
 * `unshare --mount --fork`.
 */
#define _GNU_SOURCE
#include <sys/mount.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>
#include <errno.h>

/* The property that matters is whether ".." from a top-level directory still
 * lands on the root. If it escapes, a chroot-based container runtime can
 * leave the namespace. */
static void check_root_mount(void) {
    struct stat root, up;
    if (stat("/", &root) || stat("/etc/..", &up)) return;
    if (root.st_dev != up.st_dev || root.st_ino != up.st_ino)
        fprintf(stderr, "pivot_root: WARNING /etc/.. does not resolve to / "
                        "(stacked root; container isolation is unsafe)\n");
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s NEWROOT NEWINIT [args...]\n", argv[0]); return 2; }
    if (mount("none", "/", NULL, MS_REC | MS_PRIVATE, NULL)) { perror("make-rprivate"); return 1; }
    if (mount(argv[1], argv[1], NULL, MS_BIND | MS_REC, NULL)) { perror("bind newroot"); return 1; }
    if (chdir(argv[1])) { perror("chdir newroot"); return 1; }
    if (mount(".", "/", NULL, MS_MOVE, NULL)) { perror("move newroot"); return 1; }
    if (chroot(".")) { perror("chroot newroot"); return 1; }
    check_root_mount();
    execv(argv[2], &argv[2]);
    perror("execv");
    return 1;
}
