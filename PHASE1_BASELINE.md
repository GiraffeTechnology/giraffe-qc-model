# Phase 1 Jetson Xavier NX baseline

Captured before Phase 1 deployment changes at `2026-07-12T01:54:47+08:00`.

## Connectivity and identity

- Host: (redacted — device hostname; see internal deployment log)
- LAN: (redacted — internal LAN address; see internal deployment log)
- SSH: reachable as `giraffe`, key authentication verified
- Kernel/architecture: `Linux 4.9.253-tegra`, `aarch64`
- OS: Ubuntu 18.04.6 LTS
- L4T: R32.7.1 (`nvidia-l4t-core 32.7.1-20220219090344`)
- JetPack family: 4.6.1 (derived from L4T 32.7.1)

## Compute runtime

| Component | Measured version/state |
|---|---|
| CUDA runtime | 10.2.300 (`/usr/local/cuda/version.txt`); `nvcc` not on PATH |
| cuDNN | 8.2.1.32 |
| TensorRT | 8.2.1 |
| System Python | 3.6.9 |
| Existing project runtime | Python 3.11.15 at `.conda311` |
| Git | 2.17.1 |
| Docker | 20.10.7 |
| Power mode | `MODE_20W_6CORE`, mode id 8 |
| Fan mode | quiet |

`nvpmodel -q` identified the active mode but emitted permission errors for
several detailed sysfs parameters because passwordless sudo is unavailable.

## Capacity at capture time

- Root filesystem: 117 GB total, 17 GB used, 96 GB available (15% used)
- RAM: 7.6 GB total, 1.8 GB used, 5.6 GB available
- Swap: 3.8 GB total, 0 used
- Initial `tegrastats`: RAM 1908/7765 MB, GR3D 0%, CPU temperature 40.5 C,
  GPU 40 C, thermal 40.35 C

## Camera and display

- `/dev/video0`: `USB 2.0 Camera`, USB id `1c45:6200`
- User `giraffe` is in group `video`
- OpenCV V4L2 capture succeeded before deployment: 640x480 BGR frame
- System OpenCV: 4.1.1, GTK enabled
- A graphical `giraffe` session was already active on the attached display

## Services and configuration baseline

- SSH, NetworkManager, Docker, containerd, GDM, `nvargus-daemon`, journald,
  Bluetooth and the normal Jetson platform services were active.
- `systemctl --failed`: zero failed units.
- No qc-model/Jetson system unit was installed.
- A manually launched qc-model API process was present on port 8000:
  `.conda311/bin/uvicorn src.api.main:app --host 0.0.0.0 --port 8000`.
- SHA-256 values captured for `/etc/hosts`, `/etc/hostname`, `/etc/fstab`,
  `/etc/ssh/sshd_config`, and existing `/etc/systemd/system/*.service` units.
  No `/etc` file was changed by this phase before or during baseline capture.

## Repository baseline

- Path: `/home/giraffe/work/giraffe-qc-model`
- Remote: `git@github.com:GiraffeTechnology/giraffe-qc-model.git`
- Original branch: `agent/studio-language-i18n`
- Original HEAD: `e3b19524a7f18eb6f8aeff95e2b93591795e0775`
- Worktree: clean
- GitHub `origin/main`: `53db8279f065d3d3c6adfdf6982aa2276c859550`
- Relationship: original local HEAD was one commit ahead of `origin/main`, so
  the repository was not deleted or recloned.
- PR #51 was not merged. Its head was
  `0ba441bce5d6a4e44ef012e08ca73bbb51371a9c`, one commit ahead of main.
