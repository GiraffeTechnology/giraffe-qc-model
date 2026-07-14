# Stage 1 versus Stage 2 CV behavior differences

Status: **completed**

Populate one row per observed difference. If execution finds no differences, keep
the table and record an explicit `none observed` row with the compared evidence.

| Area | Stage 1 evidence | Stage 2 evidence | Difference | Stage 3 follow-up |
|---|---|---|---|---|
| Architecture/ISA | Native baseline: macOS/Darwin `x86_64` | Ubuntu 24.04 QEMU guest: Linux `aarch64`, QEMU `virt` with TCG | Expected platform and ISA change; ARM64 identity verified | Repeat on the physical Xavier NX and record JetPack/kernel/device-tree details |
| Dependency versions | Python 3.11.15, NumPy 2.2.6, OpenCV 4.10.0 | Python 3.12.3, NumPy 1.26.4, OpenCV 4.6.0 | Versions differ because the ARM64 guest uses Ubuntu Noble packages | Pin the Jetson runtime versions and re-run compatibility checks on hardware |
| Filesystem permissions | Repository-local native probe | External `N1_WORK/giraffe-stage2` write/fsync/read-back verified; guest support disks use GPT ext4/FAT32 | No read/write, fsync, checksum, or guest mount failure remained after the exact BOOT-label recovery | Validate production mount ownership, removable-drive behavior, and service-account permissions |
| Image normalization | Eight fixtures with recorded SHA-256, width, and height | The same eight fixture hashes and dimensions were observed | None observed | Repeat with real camera frames and Jetson image codecs |
| CV analyzer output | Eight native results | Eight ARM64 results | None observed: 8/8 semantic comparisons passed within declared numeric tolerances | Measure repeatability and performance on the Xavier NX; do not reuse TCG timing |
| UI-visible state | Not in Stage 1 scope | Six debug-only Android mock states validated, including fail-closed anomaly/unavailable and retry without duplication | New Stage 2 acceptance surface; all states visibly marked `NON-PRODUCTION MOCK` and recorded zero inference calls | Re-run against physical Pad/Jetson integration and production navigation |
