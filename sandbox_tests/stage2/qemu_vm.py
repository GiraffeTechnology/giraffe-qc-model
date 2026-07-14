"""Prepare, run, and probe the external-drive-backed QEMU aarch64 guest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path


IMAGE_NAME = "ubuntu-24.04-minimal-cloudimg-arm64.img"
IMAGE_SHA256 = "d512e22bea475595ca368d5e539984ecfa5b54de9713addea4855587b159b931"
IMAGE_SOURCE = (
    "https://cloud-images.ubuntu.com/minimal/releases/noble/release/"
    "ubuntu-24.04-minimal-cloudimg-arm64.img"
)
SSH_PORT = 22222
SSH_USER = "giraffe"
SERIAL_RECOVERY_PORT = 22223
BOOT_VOLUME_NAME = "stage2-boot.raw"
UEFI_VOLUME_NAME = "stage2-uefi.raw"


def _external_root(value: str) -> Path:
    root = Path(value).resolve()
    root.relative_to(Path("/Volumes"))
    return root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def _find(executable: str, explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).resolve()
    else:
        resolved = shutil.which(executable)
        if not resolved:
            raise FileNotFoundError(f"required host tool not found: {executable}")
        candidate = Path(resolved).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _find_firmware(qemu: Path, explicit: str | None) -> Path:
    if explicit:
        firmware = Path(explicit).resolve()
        if firmware.is_file():
            return firmware
        raise FileNotFoundError(firmware)
    prefix = qemu.parent.parent
    candidates = [
        prefix / "share/qemu/edk2-aarch64-code.fd",
        prefix / "share/qemu/edk2-aarch64-code.fd.bz2",
        prefix / "share/qemu/QEMU_EFI.fd",
        Path("/opt/local/share/qemu/edk2-aarch64-code.fd"),
        Path("/usr/local/share/qemu/edk2-aarch64-code.fd"),
    ]
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix != ".bz2":
            return candidate
    raise FileNotFoundError("aarch64 UEFI firmware not found beside QEMU")


def _create_sparse_file(path: Path, size_mib: int) -> None:
    with path.open("wb") as output:
        output.truncate(size_mib * 1024 * 1024)


def _partition_support_volume(path: Path, size_mib: int, label: str, ext4: bool) -> None:
    """Create a GPT disk because udev does not label-link whole-disk filesystems."""
    _create_sparse_file(path, size_mib)
    attached = subprocess.check_output(
        [
            "hdiutil",
            "attach",
            "-nomount",
            "-imagekey",
            "diskimage-class=CRawDiskImage",
            str(path),
        ],
        text=True,
    )
    device = attached.split()[0]
    try:
        _run(
            ["diskutil", "partitionDisk", device, "GPT", "MS-DOS FAT32", label, "100%"],
            stdout=subprocess.DEVNULL,
        )
        if ext4:
            partition = f"{device}s1"
            _run(["diskutil", "unmount", partition], stdout=subprocess.DEVNULL)
            _run(
                [
                    str(_find("mke2fs", None)),
                    "-q",
                    "-t",
                    "ext4",
                    "-F",
                    "-L",
                    label,
                    partition,
                ]
            )
    finally:
        _run(["hdiutil", "detach", device], stdout=subprocess.DEVNULL)


def _create_support_volumes(workspace: Path) -> tuple[Path, Path]:
    """Create GPT volumes required by Ubuntu's minimal ARM64 cloud image."""
    boot = workspace / BOOT_VOLUME_NAME
    if not boot.exists():
        _partition_support_volume(boot, 256, "BOOT", ext4=True)
    uefi = workspace / UEFI_VOLUME_NAME
    if not uefi.exists():
        _partition_support_volume(uefi, 64, "UEFI", ext4=False)
    return boot, uefi


def prepare(
    root: Path,
    qemu_img: Path | None,
    guest_https_proxy: str | None = None,
) -> None:
    images = root / "images"
    workspace = root / "workspace"
    evidence = root / "evidence"
    cloud_init = workspace / "cloud-init"
    for directory in (images, workspace, evidence, cloud_init):
        directory.mkdir(parents=True, exist_ok=True)
    image = images / IMAGE_NAME
    if not image.is_file():
        raise FileNotFoundError(f"verified Ubuntu ARM64 image is missing: {image}")
    observed = _sha256(image)
    if observed != IMAGE_SHA256:
        raise ValueError(f"Ubuntu ARM64 image SHA-256 mismatch: {observed}")

    key = evidence / "stage2-vm-ed25519"
    if not key.is_file():
        _run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "giraffe-stage2-qemu", "-f", str(key)])
    os.chmod(key, 0o600)
    public_key = key.with_suffix(".pub").read_text(encoding="utf-8").strip()

    metadata = "instance-id: giraffe-stage2-arm64\nlocal-hostname: giraffe-stage2\n"
    apt_proxy = f"  proxy: {guest_https_proxy}\n" if guest_https_proxy else ""
    userdata = f"""#cloud-config
users:
  - name: {SSH_USER}
    groups: [adm, sudo]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - {public_key}
ssh_pwauth: false
disable_root: true
package_update: true
package_upgrade: false
apt:
  preserve_sources_list: false
{apt_proxy}  primary:
    - arches: [arm64]
      uri: https://mirrors.aliyun.com/ubuntu-ports/
packages:
  - python3
  - python3-numpy
  - python3-opencv
  - openssh-server
runcmd:
  - [sh, -c, 'uname -m > /var/tmp/stage2-machine && touch /var/tmp/stage2-ready']
final_message: 'GIRAFFE_STAGE2_ARM64_READY'
"""
    (cloud_init / "meta-data").write_text(metadata, encoding="utf-8")
    (cloud_init / "user-data").write_text(userdata, encoding="utf-8")
    seed = workspace / "seed.iso"
    if seed.exists():
        seed.unlink()
    _run(
        [
            "hdiutil",
            "makehybrid",
            "-iso",
            "-joliet",
            "-default-volume-name",
            "cidata",
            "-o",
            str(seed),
            str(cloud_init),
        ],
        stdout=subprocess.DEVNULL,
    )
    overlay = workspace / "ubuntu-noble-arm64-stage2.qcow2"
    if not overlay.exists():
        if qemu_img:
            _run(
                [
                    str(qemu_img),
                    "create",
                    "-f",
                    "qcow2",
                    "-F",
                    "qcow2",
                    "-b",
                    str(image),
                    str(overlay),
                    "24G",
                ]
            )
        else:
            shutil.copy2(image, overlay)
    boot_volume, uefi_volume = _create_support_volumes(workspace)
    manifest = {
        "schema_version": "stage2-qemu-vm-v1",
        "image": IMAGE_NAME,
        "image_source": IMAGE_SOURCE,
        "image_sha256": observed,
        "overlay": overlay.name,
        "overlay_mode": "qcow2_backing_overlay" if qemu_img else "verified_image_copy",
        "seed_iso": seed.name,
        "support_volumes": {
            "boot": {
                "file": boot_volume.name,
                "layout": "gpt",
                "filesystem": "ext4",
                "label": "BOOT",
            },
            "uefi": {
                "file": uefi_volume.name,
                "layout": "gpt",
                "filesystem": "fat32",
                "label": "UEFI",
            },
        },
        "architecture": "aarch64",
        "machine": "virt",
        "acceleration": "tcg",
        "vcpu_count": 2,
        "memory_mib": 4096,
        "ssh_host": "127.0.0.1",
        "ssh_port": SSH_PORT,
        "serial_recovery_host": "127.0.0.1",
        "serial_recovery_port": SERIAL_RECOVERY_PORT,
        "private_key_recorded": False,
        "external_volume": root.parts[2],
        "guest_package_proxy_configured": bool(guest_https_proxy),
    }
    (evidence / "qemu-vm-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("prepared verified Ubuntu aarch64 overlay and cloud-init seed on external volume")


def start(
    root: Path,
    qemu: Path,
    firmware: Path,
    resource_dir: Path | None = None,
) -> None:
    workspace = root / "workspace"
    evidence = root / "evidence"
    overlay = workspace / "ubuntu-noble-arm64-stage2.qcow2"
    seed = workspace / "seed.iso"
    boot = workspace / BOOT_VOLUME_NAME
    uefi = workspace / UEFI_VOLUME_NAME
    for required in (overlay, seed, boot, uefi, firmware):
        if not required.is_file():
            raise FileNotFoundError(required)
    manifest_path = evidence / "qemu-vm-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "qemu_executable": qemu.name,
            "qemu_version": subprocess.check_output(
                [str(qemu), "--version"], text=True
            ).splitlines()[0],
            "firmware_sha256": _sha256(firmware),
            "qemu_resource_dir_configured": bool(resource_dir),
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    command = [str(qemu)]
    if resource_dir:
        if not resource_dir.is_dir():
            raise FileNotFoundError(resource_dir)
        command.extend(["-L", str(resource_dir)])
    command.extend([
        "-name", "giraffe-stage2-arm64",
        "-machine", "virt",
        "-cpu", "max",
        "-accel", "tcg,thread=multi",
        "-smp", "2",
        "-m", "4096",
        "-bios", str(firmware),
        "-drive", f"if=none,file={overlay},format=qcow2,id=osdisk,discard=unmap",
        "-device", "virtio-blk-pci,drive=osdisk",
        "-drive", f"if=none,file={seed},format=raw,readonly=on,id=seed",
        "-device", "virtio-blk-pci,drive=seed",
        "-drive", f"if=none,file={boot},format=raw,id=bootdisk",
        "-device", "virtio-blk-pci,drive=bootdisk",
        "-drive", f"if=none,file={uefi},format=raw,id=uefidisk",
        "-device", "virtio-blk-pci,drive=uefidisk",
        "-netdev", f"user,id=net0,hostfwd=tcp:127.0.0.1:{SSH_PORT}-:22",
        "-device", "virtio-net-pci,netdev=net0",
        "-display", "none",
        "-chardev",
        (
            "socket,id=serial0,host=127.0.0.1,"
            f"port={SERIAL_RECOVERY_PORT},server=on,wait=off,"
            f"logfile={evidence / 'qemu-serial.log'},logappend=on"
        ),
        "-serial", "chardev:serial0",
        "-monitor", "none",
        "-pidfile", str(evidence / "qemu.pid"),
        "-daemonize",
    ])
    _run(command)
    print("started QEMU aarch64 guest; serial evidence is retained on external volume")


def _ssh_args(root: Path) -> list[str]:
    evidence = root / "evidence"
    return [
        "-i", str(evidence / "stage2-vm-ed25519"),
        "-p", str(SSH_PORT),
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={evidence / 'known_hosts'}",
        "-o", "ConnectTimeout=5",
        "-o", "LogLevel=ERROR",
    ]


def _scp_args(root: Path) -> list[str]:
    evidence = root / "evidence"
    return [
        "-i", str(evidence / "stage2-vm-ed25519"),
        "-P", str(SSH_PORT),
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={evidence / 'known_hosts'}",
        "-o", "ConnectTimeout=5",
        "-o", "LogLevel=ERROR",
    ]


def _continue_known_auxiliary_mount_failure(
    root: Path, serial_socket: socket.socket
) -> bool:
    """Continue only the observed minimal-image BOOT-label emergency path."""
    serial = root / "evidence/qemu-serial.log"
    if not serial.is_file():
        return False
    text = serial.read_text(encoding="utf-8", errors="replace")
    markers = (
        "Detected architecture arm64",
        "/dev/disk/by-label/BOOT",
        "Press Enter for maintenance",
        "or press Control-D to continue",
    )
    if not all(marker in text for marker in markers):
        return False
    serial_socket.sendall(b"\x04")
    manifest_path = root / "evidence/qemu-vm-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["known_auxiliary_mount_failure_acknowledged"] = True
    manifest["recovery_action"] = "control_d_continue_after_exact_BOOT_label_emergency"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return True


def run_probe(root: Path, repository: Path, output: Path, timeout_seconds: int) -> None:
    ssh_args = _ssh_args(root)
    scp_args = _scp_args(root)
    deadline = time.monotonic() + timeout_seconds
    mount_failure_acknowledged = False
    serial_socket = socket.create_connection(
        ("127.0.0.1", SERIAL_RECOVERY_PORT), timeout=5
    )
    try:
        while True:
            if not mount_failure_acknowledged:
                mount_failure_acknowledged = _continue_known_auxiliary_mount_failure(
                    root, serial_socket
                )
            check = subprocess.run(
                ["ssh", *ssh_args, f"{SSH_USER}@127.0.0.1", "test", "-f", "/var/tmp/stage2-ready"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if check.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("QEMU guest did not complete cloud-init before timeout")
            time.sleep(5)
    finally:
        serial_socket.close()
    machine = subprocess.check_output(
        ["ssh", *ssh_args, f"{SSH_USER}@127.0.0.1", "uname", "-m"], text=True
    ).strip()
    if machine not in {"aarch64", "arm64"}:
        raise ValueError(f"QEMU guest architecture refused: {machine}")
    remote_root = f"/home/{SSH_USER}/giraffe-qc-model"
    _run(["ssh", *ssh_args, f"{SSH_USER}@127.0.0.1", "mkdir", "-p", remote_root])
    sources = [repository / name for name in ("src", "sandbox_tests", "tests")]
    _run(["scp", *scp_args, "-r", *(str(source) for source in sources), f"{SSH_USER}@127.0.0.1:{remote_root}/"])
    _run(
        [
            "ssh", *ssh_args, f"{SSH_USER}@127.0.0.1",
            "cd", remote_root, "&&", "python3", "-m", "sandbox_tests.stage2.cv_probe",
            "--output", "/tmp/arm64-cv-probe.json",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(["scp", *scp_args, f"{SSH_USER}@127.0.0.1:/tmp/arm64-cv-probe.json", str(output)])
    print(f"verified guest machine={machine}; wrote {output}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "start", "run-probe"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--qemu")
    parser.add_argument("--qemu-img")
    parser.add_argument("--firmware")
    parser.add_argument("--resource-dir")
    parser.add_argument(
        "--guest-https-proxy",
        help="optional non-secret HTTPS proxy URL reachable from the QEMU guest",
    )
    parser.add_argument("--repository", default=".")
    parser.add_argument(
        "--output", default="sandbox_tests/reports/evidence/stage2/arm64-cv-probe.json"
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=5400,
        help="guest cloud-init wait; defaults to 90 minutes for software TCG",
    )
    args = parser.parse_args(argv)
    root = _external_root(args.root)
    if args.action == "prepare":
        prepare(
            root,
            _find("qemu-img", args.qemu_img) if args.qemu_img else None,
            guest_https_proxy=args.guest_https_proxy,
        )
    elif args.action == "start":
        qemu = _find("qemu-system-aarch64", args.qemu)
        start(
            root,
            qemu,
            _find_firmware(qemu, args.firmware),
            Path(args.resource_dir).resolve() if args.resource_dir else None,
        )
    else:
        run_probe(
            root,
            Path(args.repository).resolve(),
            Path(args.output),
            args.timeout_seconds,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
