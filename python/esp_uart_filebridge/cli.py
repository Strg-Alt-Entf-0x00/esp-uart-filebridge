#!/usr/bin/env python3
"""
esp-file-bridge CLI - Command-line tool for esp-uart-filebridge.

Usage:
    esp-file-bridge ls /sd/ --port COM4
    esp-file-bridge upload local.frvd /sd/models/local.frvd --port COM4
    esp-file-bridge upload_dir ./models /sd/models/ --port COM4
    esp-file-bridge download /sd/log.txt ./log.txt --port COM4
    esp-file-bridge delete /sd/old_file.bin --port COM4
    esp-file-bridge mkdir /sd/new_dir --port COM4
    esp-file-bridge format --port COM4
    esp-file-bridge info --port COM4
    esp-file-bridge speed --port COM4
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from .protocol import ESP32Protocol, ESP32ProtocolError
from .file_manager import ESP32FileManager

log = logging.getLogger("esp_file_bridge.cli")

def main():
    parser = argparse.ArgumentParser(
        prog="esp-file-bridge",
        description="esp-uart-filebridge host tool"
    )
    parser.add_argument("--port", "-p", required=True, help="Serial port (e.g. COM4 or /dev/ttyUSB0)")
    parser.add_argument("--baud", "-b", type=int, default=3000000, help="Baud rate (default: 3000000)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="Show device information")

    ls_p = sub.add_parser("ls", help="List directory contents")
    ls_p.add_argument("path", nargs="?", default="/sd/", help="Remote path (default: /sd/)")

    ul_p = sub.add_parser("upload", help="Upload local file to ESP32")
    ul_p.add_argument("local",  help="Local file path")
    ul_p.add_argument("remote", help="Remote file path on ESP32 (e.g. /sd/models/file.frvd)")
    ul_p.add_argument("--verify", action="store_true", help="Verify CRC32 after upload")

    uld_p = sub.add_parser("upload_dir", help="Upload entire local directory to ESP32")
    uld_p.add_argument("local_dir", help="Local directory path")
    uld_p.add_argument("remote_dir", help="Remote base directory on ESP32")

    dl_p = sub.add_parser("download", help="Download file from ESP32")
    dl_p.add_argument("remote", help="Remote file path")
    dl_p.add_argument("local",  help="Local destination path")

    rm_p = sub.add_parser("delete", help="Delete file or directory on ESP32")
    rm_p.add_argument("path", help="Remote path to delete")

    mk_p = sub.add_parser("mkdir", help="Create directory on ESP32")
    mk_p.add_argument("path", help="Remote directory path to create")

    fmt_p = sub.add_parser("format", help="Format the SD card (WARNING: Destroys all data)")
    fmt_p.add_argument("--force", action="store_true", help="Do not prompt for confirmation")

    sub.add_parser("speed", help="Run upload speed benchmark (/dev/null)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s"
    )

    proto = None
    try:
        proto = ESP32Protocol(args.port, args.baud)
        proto.connect()

        if args.command == "info":
            info = proto.get_device_info()
            print(f"Device     : {info.get('device_name', 'unknown')}")
            print(f"FW Version : {info.get('fw_major', 0)}.{info.get('fw_minor', 0)}.{info.get('fw_patch', 0)}")
            print(f"SD Present : {'yes' if info.get('sd_present') else 'no'}")
            if info.get('sd_present'):
                sd_mb = info.get('sd_size', 0) / (1024 * 1024)
                free_mb = info.get('sd_free', 0) / (1024 * 1024)
                print(f"SD Size    : {sd_mb:.0f} MB (free: {free_mb:.0f} MB)")
            print(f"Chunk Size : {info.get('optimal_chunk_size', 0)} bytes")

        elif args.command == "ls":
            entries = proto.list_directory(args.path)
            for e in sorted(entries, key=lambda x: (not x.get("is_dir"), x.get("name", ""))):
                name = e.get("name", "?")
                size = e.get("size", 0)
                suffix = "/" if e.get("is_dir") else f"  ({size:,} bytes)"
                print(f"  {name}{suffix}")

        elif args.command == "upload":
            file_size = os.path.getsize(args.local)
            print(f"Uploading {args.local} -> {args.remote} ({file_size:,} bytes)")
            proto.upload_file(args.local, args.remote,
                              progress_callback=lambda sent, total:
                              print(f"\r  {sent*100//total:3d}% {sent:,}/{total:,} bytes", end="", flush=True))
            print(f"\n[OK] Upload complete")
            if args.verify:
                print("Verifying CRC32...")
                import binascii
                with open(args.local, 'rb') as f:
                    local_crc = binascii.crc32(f.read())
                remote_crc = proto.get_file_hash(args.remote)
                if local_crc == remote_crc:
                    print(f"[OK] CRC32 Match: {local_crc:08X}")
                else:
                    print(f"[ERROR] CRC32 Mismatch! Local: {local_crc:08X}, Remote: {remote_crc:08X}")
                    sys.exit(1)

        elif args.command == "upload_dir":
            local_dir = Path(args.local_dir)
            if not local_dir.is_dir():
                print(f"[ERROR] {args.local_dir} is not a directory.")
                sys.exit(1)
            
            print(f"Uploading directory {args.local_dir} -> {args.remote_dir}")
            for path in local_dir.rglob('*'):
                if path.is_file():
                    if '.git' in path.parts or path.suffix == '.json':
                        continue
                    rel_path = path.relative_to(local_dir)
                    remote_path = f"{args.remote_dir}/{rel_path.as_posix()}"
                    remote_parent = "/".join(remote_path.split('/')[:-1])
                    
                    try:
                        proto.mkdir(remote_parent)
                    except ESP32ProtocolError:
                        pass # probably exists
                        
                    file_size = os.path.getsize(path)
                    print(f"  -> {remote_path} ({file_size:,} bytes)")
                    proto.upload_file(str(path), remote_path)
            print("[OK] Directory upload complete")

        elif args.command == "download":
            print(f"Downloading {args.remote} -> {args.local}")
            proto.download_file(args.remote, args.local,
                                progress_callback=lambda sent, total:
                                print(f"\r  {sent*100//total:3d}% {sent:,}/{total:,} bytes", end="", flush=True))
            print(f"\n[OK] Download complete")

        elif args.command == "delete":
            proto.delete_file(args.path)
            print(f"[OK] Deleted: {args.path}")

        elif args.command == "mkdir":
            proto.create_directory(args.path)
            print(f"[OK] Created: {args.path}")

        elif args.command == "format":
            if not args.force:
                confirm = input("WARNING: This will destroy all data on the ESP32 SD card. Continue? (y/N): ")
                if confirm.lower() != 'y':
                    print("Aborted.")
                    sys.exit(0)
            print("Formatting SD card...")
            proto.format_fs()
            print("[OK] Format complete")

        elif args.command == "speed":
            import time, tempfile
            size_mb = 2
            print(f"Speed test: uploading {size_mb} MB to /dev/null ...")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
                f.write(b'\xAA' * (size_mb * 1024 * 1024))
                tmp = f.name
            try:
                t0 = time.time()
                proto.upload_file(tmp, "/dev/null")
                elapsed = time.time() - t0
                rate_kbs = (size_mb * 1024) / elapsed
                print(f"[OK] {size_mb} MB in {elapsed:.2f}s = {rate_kbs:.0f} KB/s")
            finally:
                os.unlink(tmp)

    except ESP32ProtocolError as e:
        log.error(f"Protocol error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)
    finally:
        if proto:
            proto.close()

if __name__ == "__main__":
    main()
