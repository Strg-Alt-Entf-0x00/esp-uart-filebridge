"""
ESP32 WebDAV Provider - Maps WebDAV operations to ESP32 protocol commands.

This module implements the WsgiDAV DAVProvider interface to expose the ESP32
filesystem as a WebDAV-compatible resource tree.

Architecture:
    WebDAV Client (Windows Explorer, etc.)
        ↓
    WsgiDAV Framework
        ↓
    ESP32WebDAVProvider (this module)
        ↓
    ESP32Protocol (UART communication)
        ↓
    ESP32 Firmware
"""

import time
import logging
import threading
from io import BytesIO
from typing import Optional

from wsgidav.dav_provider import DAVProvider, DAVCollection, DAVNonCollection
from wsgidav.dav_error import DAVError, HTTP_FORBIDDEN, HTTP_NOT_FOUND, HTTP_INTERNAL_ERROR
from wsgidav import util

from ..protocol import ESP32Protocol
from ..file_manager import ESP32FileManager

logger = logging.getLogger(__name__)


class DirectoryCache:
    """
    Thread-safe cache for directory listings to avoid hammering ESP32 with requests.
    
    Windows WebDAV client makes hundreds of redundant requests for the same
    directory when accessing it. This cache dramatically reduces ESP32 load.
    """
    
    def __init__(self, ttl_seconds=2.0):
        """
        Initialize cache.
        
        Args:
            ttl_seconds: Time-to-live for cached entries (default: 2 seconds)
        """
        self.cache = {}
        self.ttl = ttl_seconds
        self._lock = threading.RLock()  # Thread-safe locking
    
    def get(self, path: str):
        """Get cached directory listing if still valid."""
        with self._lock:
            if path in self.cache:
                entries, timestamp = self.cache[path]
                age = time.time() - timestamp
                if age < self.ttl:
                    logger.debug(f"Cache HIT for {path} (age: {age:.2f}s)")
                    return entries
                else:
                    logger.debug(f"Cache EXPIRED for {path} (age: {age:.2f}s)")
                    del self.cache[path]
            return None
    
    def put(self, path: str, entries: list):
        """Store directory listing in cache."""
        with self._lock:
            self.cache[path] = (entries, time.time())
            logger.debug(f"Cache STORE {path} ({len(entries)} entries)")
    
    def invalidate(self, path: str):
        """Invalidate cache for a path and its parent."""
        with self._lock:
            # Remove exact path
            if path in self.cache:
                del self.cache[path]
                logger.debug(f"Cache INVALIDATE {path}")
            
            # Also invalidate parent (its listing changed)
            parent = "/".join(path.rstrip("/").split("/")[:-1]) or "/"
            if parent in self.cache:
                del self.cache[parent]
                logger.debug(f"Cache INVALIDATE parent {parent}")
    
    def clear(self):
        """Clear entire cache."""
        with self._lock:
            self.cache.clear()
            logger.debug("Cache CLEARED")


class ESP32File(DAVNonCollection):
    """
    Represents a file on the ESP32 filesystem.
    
    Implements WebDAV file operations: read, write, delete, metadata.
    """
    
    def __init__(self, path: str, environ: dict, file_info: dict, manager: ESP32FileManager):
        super().__init__(path, environ)
        self.file_info = file_info
        self.manager = manager
        
    def get_content_length(self) -> int:
        """Return file size in bytes."""
        if hasattr(self.file_info, 'size'):
            return self.file_info.size
        return self.file_info.get('size', 0)
    
    def get_content_type(self) -> str:
        """Return MIME type based on file extension."""
        return util.guess_mime_type(self.path)
    
    def get_creation_date(self) -> float:
        """Return creation timestamp (Unix epoch)."""
        if hasattr(self.file_info, 'timestamp'):
            return self.file_info.timestamp
        return self.file_info.get('timestamp', time.time())
    
    def get_last_modified(self) -> float:
        """Return last modification timestamp (Unix epoch)."""
        if hasattr(self.file_info, 'timestamp'):
            return self.file_info.timestamp
        return self.file_info.get('timestamp', time.time())
    
    def get_content(self) -> BytesIO:
        """
        Download file content from ESP32.
        
        Returns:
            BytesIO stream containing file data
            
        Raises:
            DAVError: On protocol errors or file not found
        """
        try:
            logger.debug(f"WebDAV: Reading file {self.path}")
            data = self.manager.download_file_to_bytes(self.path, quiet=True)
            return BytesIO(data)
        except Exception as e:
            logger.error(f"Failed to read file {self.path}: {e}")
            raise DAVError(HTTP_INTERNAL_ERROR, f"Failed to read file: {e}")
    
    def begin_write(self, content_type: Optional[str] = None) -> 'ESP32FileWriter':
        """
        Begin streaming upload to ESP32.
        
        Args:
            content_type: MIME type (unused, provided for compatibility)
            
        Returns:
            ESP32FileWriter instance for streaming data
        """
        content_length = 0
        cl = self.environ.get("CONTENT_LENGTH")
        if cl:
            try:
                content_length = int(cl)
            except ValueError:
                logger.warning(f"Invalid Content-Length header: {cl}")
                content_length = 0
        
        return ESP32FileWriter(self.path, self.manager, content_length)
    
    def delete(self):
        """
        Delete file from ESP32.
        
        Raises:
            DAVError: On protocol errors or file not found
        """
        try:
            logger.info(f"WebDAV: Deleting file {self.path}")
            self.manager.delete_file(self.path)
            
            # Invalidate parent directory cache
            parent = "/".join(self.path.rstrip("/").split("/")[:-1]) or "/"
            ESP32Folder._dir_cache.invalidate(parent)
        except Exception as e:
            # Check if this is a "file not found" error (NACK: 25)
            error_msg = str(e).lower()
            if "not found" in error_msg or "nack" in error_msg or "25" in str(e):
                # File doesn't exist - this is OK if it was just moved
                # (WsgiDAV sometimes calls delete after a successful move)
                logger.debug(f"File {self.path} not found (may have been moved)")
                # Don't raise an error - operation succeeded
                return
            
            logger.error(f"Failed to delete {self.path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, f"Failed to delete: {e}")
    
    def support_etag(self) -> bool:
        """ETag not supported (would require CRC32 on every request)."""
        return False
    
    def get_etag(self) -> None:
        """ETag not supported."""
        return None
    
    def support_ranges(self) -> bool:
        """HTTP Range requests not supported (full file only)."""
        return False
    
    def support_recursive_move(self, dest_path: str) -> bool:
        """
        Files don't support recursive move (they're not collections).
        
        This method is called by WsgiDAV to check if a resource can be moved
        recursively. Files return False (they're moved as single entities).
        """
        return False
    
    def move_recursive(self, dest_path: str):
        """
        Move file to new location (efficient server-side rename).
        
        Uses ESP32 RENAME command for instant server-side move,
        avoiding download+upload cycle.
        
        Args:
            dest_path: Destination path
            
        Raises:
            DAVError: On move failure
        """
        try:
            logger.info(f"WebDAV: Moving file {self.path} -> {dest_path}")
            self.manager.rename_file(self.path, dest_path)
            
            # Invalidate caches for both source and dest parents
            src_parent = "/".join(self.path.rstrip("/").split("/")[:-1]) or "/"
            dst_parent = "/".join(dest_path.rstrip("/").split("/")[:-1]) or "/"
            ESP32Folder._dir_cache.invalidate(src_parent)
            ESP32Folder._dir_cache.invalidate(dst_parent)
            
        except Exception as e:
            logger.error(f"Failed to move {self.path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, f"Move failed: {e}")
    
    def copy_move_single(self, dest_path: str, is_move: bool):
        """
        Copy or move this file (WsgiDAV standard method).
        
        This is the method WsgiDAV actually calls for MOVE/COPY operations.
        
        Args:
            dest_path: Destination path
            is_move: True for move, False for copy
            
        Raises:
            DAVError: On operation failure
        """
        try:
            if is_move:
                logger.info(f"WebDAV: Moving file {self.path} -> {dest_path}")
                self.manager.rename_file(self.path, dest_path)
            else:
                logger.info(f"WebDAV: Copying file {self.path} -> {dest_path}")
                self.manager.copy_file(self.path, dest_path)
            
            # Invalidate caches
            src_parent = "/".join(self.path.rstrip("/").split("/")[:-1]) or "/"
            dst_parent = "/".join(dest_path.rstrip("/").split("/")[:-1]) or "/"
            ESP32Folder._dir_cache.invalidate(src_parent)
            ESP32Folder._dir_cache.invalidate(dst_parent)
            
        except Exception as e:
            operation = "move" if is_move else "copy"
            logger.error(f"Failed to {operation} {self.path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, f"{operation.capitalize()} failed: {e}")
    
    def copy_recursive(self, dest_path: str, depth_infinity: bool):
        """
        Copy file to new location (efficient server-side copy).
        
        Uses ESP32 COPY command for server-side copy,
        avoiding download+upload cycle.
        
        Args:
            dest_path: Destination path
            depth_infinity: Ignored for files (not collections)
            
        Raises:
            DAVError: On copy failure
        """
        try:
            logger.info(f"WebDAV: Copying file {self.path} -> {dest_path}")
            self.manager.copy_file(self.path, dest_path)
            
            # Invalidate destination parent cache
            dst_parent = "/".join(dest_path.rstrip("/").split("/")[:-1]) or "/"
            ESP32Folder._dir_cache.invalidate(dst_parent)
            
        except Exception as e:
            logger.error(f"Failed to copy {self.path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, f"Copy failed: {e}")


class ESP32FileWriter:
    """
    Handles streaming file uploads to ESP32.
    
    Streams data directly to ESP32 without buffering in RAM.
    Uses the new streaming upload protocol (no per-chunk ACK).
    """
    
    def __init__(self, path: str, manager: ESP32FileManager, content_length: int = 0):
        self.path = path
        self.manager = manager
        self.content_length = content_length
        self.bytes_written = 0
        self.stream_started = False
        
        logger.info(f"WebDAV: Beginning upload to {path} ({content_length:,} bytes)")
    
    def write(self, data: bytes):
        """
        Stream data chunk directly to ESP32 (no RAM buffering).
        
        Args:
            data: Chunk of file data from WebDAV client
        """
        # Start stream on first write
        if not self.stream_started:
            self.manager.proto.begin_write_stream(self.path, self.content_length)
            self.stream_started = True
        
        # Stream chunk directly to ESP32
        self.manager.proto.write_stream_data(data)
        self.bytes_written += len(data)
    
    def close(self):
        """
        Finalize upload - close stream on ESP32.
        
        Raises:
            DAVError: On upload failure
        """
        try:
            if self.stream_started:
                self.manager.proto.end_write_stream()
                logger.info(f"WebDAV: Upload complete to {self.path} ({self.bytes_written:,} bytes)")
            
            # Invalidate parent directory cache AND the file itself
            parent = "/".join(self.path.rstrip("/").split("/")[:-1]) or "/"
            ESP32Folder._dir_cache.invalidate(parent)
            ESP32Folder._dir_cache.invalidate(self.path)
            
        except Exception as e:
            logger.error(f"Failed to upload file {self.path}: {e}")
            
            # Send abort command to ESP32 on error
            if self.stream_started:
                try:
                    # Abort incomplete upload
                    from ..protocol import CMD_PUT_FILE_ABORT
                    self.manager.proto._send_frame(CMD_PUT_FILE_ABORT, b'')
                except:
                    pass  # Best effort
            
            raise DAVError(HTTP_INTERNAL_ERROR, f"Upload failed: {e}")


class ESP32Folder(DAVCollection):
    """
    Represents a directory on the ESP32 filesystem.
    
    Implements WebDAV directory operations: list, create files/folders, delete.
    """
    
    # Class-level cache shared by all folder instances
    _dir_cache = DirectoryCache(ttl_seconds=2.0)
    
    def __init__(self, path: str, environ: dict, file_info: Optional[dict], manager: ESP32FileManager):
        super().__init__(path, environ)
        self.file_info = file_info
        self.manager = manager
    
    def get_creation_date(self) -> float:
        """Return creation timestamp (Unix epoch)."""
        if self.file_info:
            if hasattr(self.file_info, 'timestamp'):
                return self.file_info.timestamp
            if 'timestamp' in self.file_info:
                return self.file_info['timestamp']
        return time.time()
    
    def get_last_modified(self) -> float:
        """Return last modification timestamp (Unix epoch)."""
        if self.file_info:
            if hasattr(self.file_info, 'timestamp'):
                return self.file_info.timestamp
            if 'timestamp' in self.file_info:
                return self.file_info['timestamp']
        return time.time()
    
    def get_member_names(self) -> list:
        """
        List directory contents.
        
        Returns:
            List of entry names (files and subdirectories)
        """
        try:
            # Special handling for root "/" - return virtual mount point
            if self.path == "/":
                # Root shows only the virtual "sd" folder
                # Don't query ESP32 for root (it doesn't support "/")
                info = self.manager.get_device_info()
                if info and info.sd_present:
                    return ['sd']
                return []
            
            # Check cache first
            cached = self._dir_cache.get(self.path)
            if cached is not None:
                # Return names from cached entries
                result = []
                for e in cached:
                    name = e.name if hasattr(e, 'name') else e.get('name')
                    if name and name not in ('.', '..'):
                        result.append(name)
                return result
            
            # Cache miss - query ESP32
            entries = self.manager.list_directory(self.path, quiet=True)
            
            # Store in cache
            self._dir_cache.put(self.path, entries)
            
            # Filter out "." and ".." entries and extract names
            result = []
            for e in entries:
                name = e.name if hasattr(e, 'name') else e.get('name')
                if name and name not in ('.', '..'):
                    result.append(name)
            
            return result
        
        except Exception as e:
            logger.error(f"Failed to list directory {self.path}: {e}")
            return []
    
    def get_member(self, name: str) -> Optional[DAVCollection | DAVNonCollection]:
        """
        Get a specific member (file or subdirectory).
        
        Args:
            name: Entry name to retrieve
            
        Returns:
            ESP32File or ESP32Folder instance, or None if not found
        """
        child_path = util.join_uri(self.path, name)
        
        # Special case: root "/" accessing "sd" - create virtual folder that maps to ESP32 /sd
        if self.path == "/" and name == "sd":
            # This virtual folder will transparently access ESP32's /sd
            # No fake info - it will query ESP32 for real content
            return ESP32Folder("/sd", self.environ, None, self.manager)
        
        try:
            # Check cache first
            cached = self._dir_cache.get(self.path)
            if cached is None:
                # Cache miss - query ESP32 and store
                cached = self.manager.list_directory(self.path, quiet=True)
                self._dir_cache.put(self.path, cached)
            
            # Find entry in cached listing
            for entry in cached:
                entry_name = entry.name if hasattr(entry, 'name') else entry.get('name')
                
                if entry_name == name:
                    # Found the entry - determine if it's a file or directory
                    is_dir = entry.is_directory if hasattr(entry, 'is_directory') else entry.get('is_dir', False)
                    size = entry.size if hasattr(entry, 'size') else entry.get('size', 0)
                    timestamp = entry.timestamp if hasattr(entry, 'timestamp') else entry.get('timestamp', int(time.time()))
                    
                    # Build entry info dict for compatibility
                    entry_dict = {
                        'name': entry_name,
                        'size': size,
                        'is_dir': is_dir,
                        'timestamp': timestamp
                    }
                    
                    if is_dir:
                        return ESP32Folder(child_path, self.environ, entry_dict, self.manager)
                    else:
                        return ESP32File(child_path, self.environ, entry_dict, self.manager)
            
            # Entry not found in listing
            return None
        
        except Exception as e:
            logger.error(f"Error getting member {child_path}: {e}")
            return None
    
    def create_empty_resource(self, name: str) -> ESP32File:
        """
        Create an empty file in this directory.
        
        Args:
            name: File name to create
            
        Returns:
            ESP32File instance for the new file
            
        Raises:
            DAVError: On creation failure
        """
        child_path = util.join_uri(self.path, name)
        
        try:
            logger.info(f"WebDAV: Creating empty file {child_path}")
            # Upload empty file
            self.manager.upload_file_from_bytes(b'', child_path, quiet=True)
            
            # Invalidate cache for this directory
            self._dir_cache.invalidate(self.path)
            
            # Return file resource
            file_info = {'name': name, 'size': 0, 'is_dir': False, 'timestamp': int(time.time())}
            return ESP32File(child_path, self.environ, file_info, self.manager)
        
        except Exception as e:
            logger.error(f"Failed to create empty file {child_path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, f"Failed to create file: {e}")
    
    def create_collection(self, name: str):
        """
        Create a subdirectory in this directory.
        
        Args:
            name: Directory name to create
            
        Raises:
            DAVError: On creation failure (unless directory already exists)
        """
        child_path = util.join_uri(self.path, name)
        
        logger.info(f"WebDAV: Creating directory {child_path}")
        # Use quiet=True to suppress the [FAIL] log for "already exists"
        success = self.manager.create_directory(child_path, quiet=False)
        
        # Invalidate cache for this directory regardless of success
        # (directory might exist from previous operation)
        self._dir_cache.invalidate(self.path)
        
        if not success:
            # If create_directory returned False, it's a real error (not "already exists")
            raise DAVError(HTTP_FORBIDDEN, f"Failed to create directory: {child_path}")
    
    def delete(self):
        """
        Delete this directory (must be empty for most filesystems).
        
        Raises:
            DAVError: On deletion failure
        """
        try:
            logger.info(f"WebDAV: Deleting directory {self.path}")
            self.manager.delete_file(self.path)
            
            # Invalidate cache for this path and parent
            self._dir_cache.invalidate(self.path)
        
        except Exception as e:
            logger.error(f"Failed to delete directory {self.path}: {e}")
            if "not found" in str(e).lower():
                raise DAVError(HTTP_NOT_FOUND, f"Directory not found: {self.path}")
            raise DAVError(HTTP_FORBIDDEN, f"Failed to delete directory: {e}")
    
    def support_recursive_move(self, dest_path: str) -> bool:
        """
        Directories support recursive move.
        
        This method is called by WsgiDAV to check if a directory can be moved
        recursively (with all its contents). We return True for directories.
        """
        return True
    
    def move_recursive(self, dest_path: str):
        """
        Move directory to new location (efficient server-side rename).
        
        Uses ESP32 RENAME command to instantly rename directory
        and all its contents, avoiding recursive download+upload.
        
        Args:
            dest_path: Destination path
            
        Raises:
            DAVError: On move failure
        """
        try:
            logger.info(f"WebDAV: Moving directory {self.path} -> {dest_path}")
            self.manager.rename_file(self.path, dest_path)
            
            # Invalidate caches extensively
            src_parent = "/".join(self.path.rstrip("/").split("/")[:-1]) or "/"
            dst_parent = "/".join(dest_path.rstrip("/").split("/")[:-1]) or "/"
            ESP32Folder._dir_cache.invalidate(src_parent)
            ESP32Folder._dir_cache.invalidate(dst_parent)
            ESP32Folder._dir_cache.invalidate(self.path)  # Old path
            ESP32Folder._dir_cache.invalidate(dest_path)  # New path
            
        except Exception as e:
            logger.error(f"Failed to move directory {self.path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, f"Move failed: {e}")
    
    def copy_move_single(self, dest_path: str, is_move: bool):
        """
        Copy or move this directory (WsgiDAV standard method).
        
        This is the method WsgiDAV actually calls for MOVE operations on directories.
        Note: Directories cannot be copied with this method (use copy_recursive).
        
        Args:
            dest_path: Destination path
            is_move: True for move, False for copy
            
        Raises:
            DAVError: On operation failure
        """
        if not is_move:
            # Directories can't be "single copied" - this would need copy_recursive
            raise DAVError(HTTP_FORBIDDEN, "Directory copy requires recursive operation")
        
        try:
            logger.info(f"WebDAV: Moving directory {self.path} -> {dest_path}")
            self.manager.rename_file(self.path, dest_path)
            
            # Invalidate caches extensively
            src_parent = "/".join(self.path.rstrip("/").split("/")[:-1]) or "/"
            dst_parent = "/".join(dest_path.rstrip("/").split("/")[:-1]) or "/"
            ESP32Folder._dir_cache.invalidate(src_parent)
            ESP32Folder._dir_cache.invalidate(dst_parent)
            ESP32Folder._dir_cache.invalidate(self.path)
            ESP32Folder._dir_cache.invalidate(dest_path)
            
        except Exception as e:
            logger.error(f"Failed to move directory {self.path}: {e}")
            raise DAVError(HTTP_FORBIDDEN, f"Move failed: {e}")


class ESP32WebDAVProvider(DAVProvider):
    """
    Main WebDAV provider for ESP32 filesystem.
    
    Entry point for WsgiDAV framework. Maps WebDAV paths to ESP32 resources.
    """
    
    def __init__(self, manager: ESP32FileManager):
        """
        Initialize provider.
        
        Args:
            manager: ESP32FileManager instance (wraps protocol + file operations)
        """
        super().__init__()
        self.manager = manager
        logger.info("ESP32 WebDAV Provider initialized")
    
    def get_resource_inst(self, path: str, environ: dict) -> Optional[DAVCollection | DAVNonCollection]:
        """
        Get resource instance for a given path.
        
        This is the main entry point called by WsgiDAV for all operations.
        
        Args:
            path: WebDAV path (e.g. "/sd/models/file.bin")
            environ: WSGI environment dict
            
        Returns:
            ESP32File, ESP32Folder, or None if path doesn't exist
        """
        # Root "/" is always a virtual directory
        if path == "/":
            return ESP32Folder(path, environ, None, self.manager)
        
        # Special case: "/sd" is the virtual mount point to ESP32's /sd
        if path == "/sd" or path == "/sd/":
            return ESP32Folder("/sd", environ, None, self.manager)
        
        try:
            # For all other paths, determine if file or directory
            # by listing parent and checking entry type
            parent_path = "/".join(path.rstrip("/").split("/")[:-1]) or "/"
            entry_name = path.rstrip("/").split("/")[-1]
            
            # Check cache first
            cached = ESP32Folder._dir_cache.get(parent_path)
            if cached is None:
                # Cache miss - query ESP32 and store
                cached = self.manager.list_directory(parent_path, quiet=True)
                ESP32Folder._dir_cache.put(parent_path, cached)
            
            # Find entry in cached listing
            for entry in cached:
                entry_name_actual = entry.name if hasattr(entry, 'name') else entry.get('name')
                if entry_name_actual == entry_name:
                    is_dir = entry.is_directory if hasattr(entry, 'is_directory') else entry.get('is_dir', False)
                    if is_dir:
                        return ESP32Folder(path, environ, entry, self.manager)
                    else:
                        return ESP32File(path, environ, entry, self.manager)
            
            # Path doesn't exist
            return None
        
        except Exception as e:
            logger.debug(f"Error getting resource instance for {path}: {e}")
            return None
