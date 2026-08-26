"""Universal high-level file operations for the ESP UART file bridge."""

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from .protocol import (
    ESP32Protocol,
    ESP32ProtocolError,
    ERR_FILE_EXISTS,
    ERR_FILE_NOT_FOUND,
)

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int], None]


class ESP32FileManager:
    """High-level, filesystem-agnostic operations for a connected ESP32."""

    def __init__(self, proto: ESP32Protocol | str, baud: Optional[int] = None):
        if isinstance(proto, str):
            self.port = proto
            self.baud = baud or 3000000
            self.proto = ESP32Protocol()
        else:
            self.port = None
            self.baud = baud or 3000000
            self.proto = proto

    def connect(self) -> bool:
        """Connect when the manager was constructed with a serial port."""
        if not self.port:
            raise RuntimeError("A port is required when using connect()")

        for attempt in range(3):
            if self.proto.connect(self.port, self.baud):
                return True
            if attempt < 2:
                import time
                time.sleep(2)
        return False

    def disconnect(self) -> None:
        self.proto.disconnect()

    def get_device_info(self):
        return self.proto.get_device_info()

    def get_file_stat(self, remote_path: str):
        return self.proto.get_stat(remote_path)

    def list_directory(self, path: str = "/sd", quiet: bool = False):
        if path in ("", "/"):
            raise ESP32ProtocolError("Root directory listing is not supported")

        entries = self.proto.list_directory(path)
        if not quiet:
            directories = sorted((entry for entry in entries if entry.is_directory), key=lambda e: e.name)
            files = sorted((entry for entry in entries if not entry.is_directory), key=lambda e: e.name)
            for entry in directories:
                logger.info("  [DIR]  %s", entry.name)
            for entry in files:
                logger.info("  %s bytes  %s", f"{entry.size:,}", entry.name)
            logger.info("Total: %d directories, %d files", len(directories), len(files))
        return entries

    def upload_file(
        self,
        local_path: str | os.PathLike[str],
        remote_path: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        size = os.path.getsize(local_path)
        try:
            self.proto.begin_write_stream(remote_path, size)
            sent = 0
            with open(local_path, "rb") as source:
                while chunk := source.read(self.proto.chunk_size):
                    self.proto.write_stream_data(chunk)
                    sent += len(chunk)
                    if progress_callback:
                        progress_callback(sent, size)
            self.proto.end_write_stream()
        except Exception:
            self._abort_transfer()
            raise

    def upload_directory(
        self,
        local_dir: str | os.PathLike[str],
        remote_dir: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> int:
        """Upload every file recursively, preserving the local directory tree."""
        root = Path(local_dir)
        if not root.is_dir():
            raise NotADirectoryError(root)

        uploaded = 0
        created_directories = set()
        for local_path in sorted(path for path in root.rglob("*") if path.is_file()):
            relative_path = local_path.relative_to(root).as_posix()
            remote_path = f"{remote_dir.rstrip('/')}/{relative_path}"
            remote_parent = remote_path.rsplit("/", 1)[0]
            if remote_parent not in created_directories:
                self.create_directory(remote_parent, quiet=True)
                created_directories.add(remote_parent)
            self.upload_file(local_path, remote_path, progress_callback)
            uploaded += 1
        return uploaded

    def download_file(
        self,
        remote_path: str,
        local_path: str | os.PathLike[str],
        progress_callback: Optional[ProgressCallback] = None,
    ) -> None:
        data = self.proto.read_file(remote_path)
        destination = Path(local_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        if progress_callback:
            progress_callback(len(data), len(data))

    def download_file_to_bytes(self, remote_path: str, quiet: bool = False) -> bytes:
        data = self.proto.read_file(remote_path)
        if not quiet:
            logger.info("Downloaded %d bytes from %s", len(data), remote_path)
        return data

    def upload_file_from_bytes(self, data: bytes, remote_path: str, quiet: bool = False) -> None:
        try:
            self.proto.begin_write_stream(remote_path, len(data))
            for offset in range(0, len(data), self.proto.chunk_size):
                self.proto.write_stream_data(data[offset:offset + self.proto.chunk_size])
            self.proto.end_write_stream()
        except Exception:
            self._abort_transfer()
            raise

    def delete_file(self, remote_path: str) -> bool:
        try:
            self.proto.delete_file(remote_path)
            return True
        except ESP32ProtocolError as error:
            if error.error_code == ERR_FILE_NOT_FOUND:
                return True
            raise

    def create_directory(self, remote_path: str, quiet: bool = False) -> bool:
        try:
            self.proto.mkdir(remote_path)
            return True
        except ESP32ProtocolError as error:
            if error.error_code == ERR_FILE_EXISTS:
                return True
            raise

    def get_file_hash(self, remote_path: str) -> int:
        return self.proto.get_file_hash(remote_path)

    def rename_file(self, old_path: str, new_path: str) -> None:
        self.proto.rename(old_path, new_path)

    def copy_file(self, source_path: str, destination_path: str) -> None:
        self.proto.copy_file(source_path, destination_path)

    def format_fs(self, fs_type: int = 2) -> None:
        self.proto.format_fs(fs_type)

    def _abort_transfer(self) -> None:
        try:
            self.proto.abort_write_stream()
        except Exception:
            logger.debug("Could not abort the failed remote transfer", exc_info=True)
