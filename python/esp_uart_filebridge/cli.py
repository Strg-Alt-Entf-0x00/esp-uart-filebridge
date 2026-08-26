#!/usr/bin/env python3
"""
esp-file-bridge CLI - Command-line tool for esp-uart-filebridge.

Usage:
    esp-file-bridge ls /sd/ --port COM4
    esp-file-bridge upload local_file.bin /sd/data/local_file.bin --port COM4
    esp-file-bridge upload_dir ./local_directory /sd/data/ --port COM4
    esp-file-bridge download /sd/log.txt ./log.txt --port COM4
    esp-file-bridge delete /sd/old_file.bin --port COM4
    esp-file-bridge mkdir /sd/new_dir --port COM4
    esp-file-bridge format --port COM4
    esp-file-bridge info --port COM4
"""

import sys
import os
import argparse
import logging
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

    stat_p = sub.add_parser("stat", help="Show file or directory metadata")
    stat_p.add_argument("path", help="Remote file or directory path")

    hash_p = sub.add_parser("hash", help="Show CRC32 hash of a remote file")
    hash_p.add_argument("path", help="Remote file path")

    ls_p = sub.add_parser("ls", help="List directory contents")
    ls_p.add_argument("path", nargs="?", default="/sd/", help="Remote path (default: /sd/)")

    ul_p = sub.add_parser("upload", help="Upload local file to ESP32")
    ul_p.add_argument("local",  help="Local file path")
    ul_p.add_argument("remote", help="Remote file path on ESP32 (e.g. /sd/data/file.bin)")
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
    
    mv_p = sub.add_parser("rename", help="Rename or move file/directory on ESP32")
    mv_p.add_argument("old_path", help="Current path")
    mv_p.add_argument("new_path", help="New path")
    
    cp_p = sub.add_parser("copy", help="Copy file on ESP32")
    cp_p.add_argument("src_path", help="Source file path")
    cp_p.add_argument("dst_path", help="Destination file path")

    fmt_p = sub.add_parser("format", help="Format the SD card (WARNING: Destroys all data)")
    fmt_p.add_argument("--force", action="store_true", help="Do not prompt for confirmation")

    webdav_p = sub.add_parser("webdav", help="Start WebDAV server (network drive)")
    webdav_p.add_argument("--host", default="127.0.0.1", help="HTTP server host (default: 127.0.0.1)")
    webdav_p.add_argument("--webdav-port", type=int, default=8080, help="HTTP server port (default: 8080)")
    webdav_p.add_argument("--no-systray", action="store_true", help="Disable system tray icon (Windows)")
    webdav_p.add_argument("--no-mount", action="store_true", help="Disable auto-mount (Windows)")
    webdav_p.add_argument("--drive", help="Drive letter for Windows (e.g. Z:)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s"
    )

    proto = None
    try:
        proto = ESP32Protocol()
        manager = ESP32FileManager(proto)
        if not proto.connect(args.port, args.baud):
            raise ESP32ProtocolError(f"Could not connect to {args.port}")

        if args.command == "info":
            info = manager.get_device_info()
            print(f"Device     : {info.device_name}")
            print(f"FW Version : {info.fw_version}")
            print(f"SD Present : {'yes' if info.sd_present else 'no'}")
            if info.sd_present:
                sd_mb = info.sd_size / (1024 * 1024)
                free_mb = info.sd_free / (1024 * 1024)
                print(f"SD Size    : {sd_mb:.0f} MB (free: {free_mb:.0f} MB)")
            print(f"Chunk Size : {info.optimal_chunk_size} bytes")

        elif args.command == "ls":
            entries = manager.list_directory(args.path)
            for entry in sorted(entries, key=lambda item: (not item.is_directory, item.name)):
                suffix = "/" if entry.is_directory else f"  ({entry.size:,} bytes)"
                print(f"  {entry.name}{suffix}")

        elif args.command == "stat":
            info = manager.get_file_stat(args.path)
            kind = "directory" if info.is_directory else "file"
            print(f"Path       : {args.path}")
            print(f"Type       : {kind}")
            print(f"Size       : {info.size} bytes")
            print(f"Timestamp  : {info.timestamp}")
            print(f"Attributes : 0x{info.attributes:02X}")

        elif args.command == "hash":
            value = manager.get_file_hash(args.path)
            print(f"CRC32      : {value:08X}")

        elif args.command == "upload":
            file_size = os.path.getsize(args.local)
            print(f"Uploading {args.local} -> {args.remote} ({file_size:,} bytes)")
            manager.upload_file(args.local, args.remote,
                              progress_callback=lambda sent, total:
                              print(f"\r  {sent*100//total:3d}% {sent:,}/{total:,} bytes", end="", flush=True))
            print(f"\n[OK] Upload complete")
            if args.verify:
                print("Verifying CRC32...")
                import binascii
                with open(args.local, 'rb') as f:
                    local_crc = binascii.crc32(f.read())
                remote_crc = manager.get_file_hash(args.remote)
                if local_crc == remote_crc:
                    print(f"[OK] CRC32 Match: {local_crc:08X}")
                else:
                    print(f"[ERROR] CRC32 Mismatch! Local: {local_crc:08X}, Remote: {remote_crc:08X}")
                    sys.exit(1)

        elif args.command == "upload_dir":
            print(f"Uploading directory {args.local_dir} -> {args.remote_dir}")
            count = manager.upload_directory(args.local_dir, args.remote_dir)
            print(f"[OK] Uploaded {count} files")

        elif args.command == "download":
            print(f"Downloading {args.remote} -> {args.local}")
            manager.download_file(args.remote, args.local,
                                progress_callback=lambda sent, total:
                                print(f"\r  {sent*100//total:3d}% {sent:,}/{total:,} bytes", end="", flush=True))
            print(f"\n[OK] Download complete")

        elif args.command == "delete":
            manager.delete_file(args.path)
            print(f"[OK] Deleted: {args.path}")

        elif args.command == "mkdir":
            manager.create_directory(args.path)
            print(f"[OK] Created: {args.path}")
        
        elif args.command == "rename":
            proto.rename(args.old_path, args.new_path)
            print(f"[OK] Renamed: {args.old_path} -> {args.new_path}")
        
        elif args.command == "copy":
            proto.copy_file(args.src_path, args.dst_path)
            print(f"[OK] Copied: {args.src_path} -> {args.dst_path}")

        elif args.command == "format":
            if not args.force:
                confirm = input("WARNING: This will destroy all data on the ESP32 SD card. Continue? (y/N): ")
                if confirm.lower() != 'y':
                    print("Aborted.")
                    sys.exit(0)
            print("Formatting SD card...")
            manager.format_fs()
            print("[OK] Format complete")

        elif args.command == "webdav":
            # WebDAV server requires additional dependencies
            try:
                from .webdav import is_available, start_webdav_server
                
                if not is_available():
                    log.error("WebDAV dependencies not installed!")
                    log.error("Install with: pip install esp-uart-filebridge[webdav]")
                    sys.exit(1)
                
                # Close the protocol connection (WebDAV server will create its own)
                proto.disconnect()
                
                # Start WebDAV server (blocking)
                exit_code = start_webdav_server(
                    port=args.port,
                    baud=args.baud,
                    host=args.host,
                    webdav_port=args.webdav_port,
                    systray=not args.no_systray,
                    auto_mount=not args.no_mount,
                    drive=args.drive
                )
                sys.exit(exit_code)
            
            except ImportError:
                log.error("WebDAV module not found!")
                log.error("Install with: pip install esp-uart-filebridge[webdav]")
                sys.exit(1)

    except ESP32ProtocolError as e:
        log.error(f"Protocol error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(0)
    finally:
        if proto:
            proto.disconnect()

if __name__ == "__main__":
    main()
