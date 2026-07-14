/*
 * Minimal CLI entry point for the QEMU aarch64 framework bundled by UTM.
 *
 * UTM's macOS package exposes qemu_init/main_loop/cleanup from a signed
 * framework rather than shipping qemu-system-aarch64 as an executable. The
 * framework build leaves the big QEMU lock unlocked after qemu_init, so this
 * entry point intentionally enters qemu_main_loop directly.
 */
void qemu_init(int argc, char **argv);
int qemu_main_loop(void);
void qemu_cleanup(int status);

int main(int argc, char **argv) {
    int status;
    qemu_init(argc, argv);
    status = qemu_main_loop();
    qemu_cleanup(status);
    return status;
}
