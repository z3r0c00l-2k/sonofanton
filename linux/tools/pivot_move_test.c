/* pivot_move NEWROOT NEWINIT [args...] — switch_root-style entry (test aid).
 *
 * The chroot+bind+pivot_root workaround attaches the new root at the bind's
 * mountpoint (/.pivotbind) instead of "/". The process then counts as
 * chrooted relative to the mount namespace root: create_user_ns() refuses
 * (EPERM) and ".." can cross the mount stack. Moving the new root onto "/"
 * attaches it at the namespace root mountpoint, which is the condition
 * current_chrooted() follows down to.
 *
 * This is a test binary; the launcher's helper is updated only after a
 * recovery-context test shows userns creation succeeding.
 */
#define _GNU_SOURCE
#include <sys/mount.h>
#include <sys/stat.h>
#include <unistd.h>
#include <stdio.h>

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: %s NEWROOT NEWINIT [args...]\n", argv[0]); return 2; }
    if (mount("none", "/", NULL, MS_REC | MS_PRIVATE, NULL)) { perror("make-rprivate"); return 1; }
    if (mount(argv[1], argv[1], NULL, MS_BIND | MS_REC, NULL)) { perror("bind newroot"); return 1; }
    if (chdir(argv[1])) { perror("chdir newroot"); return 1; }
    if (mount(".", "/", NULL, MS_MOVE, NULL)) { perror("move newroot"); return 1; }
    if (chroot(".")) { perror("chroot newroot"); return 1; }
    execv(argv[2], &argv[2]);
    perror("execv");
    return 1;
}
