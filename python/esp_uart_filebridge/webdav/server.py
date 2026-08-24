"""
ESP32 WebDAV Server - Network drive interface for ESP32 filesystem.

Provides a WebDAV server that exposes the ESP32 SD card as a network-mounted
drive, enabling drag-and-drop file management through native OS file explorers.

Platform Support:
    - Windows: Mounts as network drive (net use Z: \\\\localhost\\DavWWWRoot@8080\\)
    - Linux: Mount via davfs2 or file manager (Nautilus, Dolphin)
    - macOS: Finder → Go → Connect to Server → http://localhost:8080

Architecture:
    ESP32 (UART) ← ESP32Protocol ← ESP32FileManager ← ESP32WebDAVProvider ← WsgiDAV ← Cheroot HTTP Server
"""

import sys
import os
import time
import logging
import threading
import platform
from typing import Optional

try:
    from cheroot import wsgi
    from wsgidav.wsgidav_app import WsgiDAVApp
    _CHEROOT_AVAILABLE = True
except ImportError:
    _CHEROOT_AVAILABLE = False
    wsgi = None
    WsgiDAVApp = None

try:
    import pystray
    from PIL import Image, ImageDraw
    _SYSTRAY_AVAILABLE = True
except ImportError:
    _SYSTRAY_AVAILABLE = False
    pystray = None
    Image = None
    ImageDraw = None

from ..protocol import ESP32Protocol
from ..file_manager import ESP32FileManager
from .provider import ESP32WebDAVProvider

logger = logging.getLogger(__name__)


class ESP32WebDAVServer:
    """
    WebDAV server for ESP32 filesystem access.
    
    Manages the HTTP server lifecycle, system tray integration, and
    optional auto-mounting of network drive.
    """
    
    def __init__(self, port_name: str, baud_rate: int = 3000000,
                 host: str = "127.0.0.1", webdav_port: int = 8080,
                 enable_systray: bool = True, auto_mount: bool = True,
                 mount_drive: Optional[str] = None):
        """
        Initialize WebDAV server.
        
        Args:
            port_name: Serial port (e.g., "COM4", "/dev/ttyUSB0")
            baud_rate: UART baud rate (default: 3000000 = 3 Mbps)
            host: HTTP server bind address (default: 127.0.0.1 for localhost only)
            webdav_port: HTTP server port (default: 8080)
            enable_systray: Enable system tray icon (Windows only, requires pystray)
            auto_mount: Automatically mount as network drive (Windows only)
            mount_drive: Drive letter for Windows (e.g., "Z:"), auto-selects if None
        """
        if not _CHEROOT_AVAILABLE:
            raise RuntimeError(
                "WebDAV dependencies not installed. Install with:\n"
                "  pip install esp-uart-filebridge[webdav]"
            )
        
        self.port_name = port_name
        self.baud_rate = baud_rate
        self.host = host
        self.webdav_port = webdav_port
        self.enable_systray = enable_systray and _SYSTRAY_AVAILABLE
        self.auto_mount = auto_mount
        self.mount_drive = mount_drive or self._find_available_drive()
        
        self.proto = None
        self.manager = None
        self.server = None
        self.server_thread = None
        self.systray_icon = None
        self.running = False
        
        # Detect platform
        self.platform = platform.system()
        logger.info(f"Platform detected: {self.platform}")
        
        # Disable systray on non-Windows if not explicitly enabled
        if self.platform != "Windows" and self.enable_systray:
            logger.warning("System tray icon only supported on Windows, disabling.")
            self.enable_systray = False
        
        # Disable auto-mount on non-Windows
        if self.platform != "Windows" and self.auto_mount:
            logger.info("Auto-mount only supported on Windows, manual mount required.")
            self.auto_mount = False
    
    def _find_available_drive(self) -> str:
        """Find available drive letter on Windows."""
        if platform.system() != "Windows":
            return None
        
        # Prefer Z:, then Y:, X:, etc.
        for letter in "ZYXWVUTSRQPONMLKJIHGFED":
            drive = f"{letter}:"
            if not os.path.exists(drive):
                return drive
        
        return "Z:"  # Fallback
    
    def connect_esp32(self) -> bool:
        """
        Connect to ESP32 via UART.
        
        Returns:
            True if connection successful
        """
        try:
            logger.info(f"Connecting to ESP32 on {self.port_name} @ {self.baud_rate:,} baud...")
            
            self.proto = ESP32Protocol()
            self.proto.connect(self.port_name, self.baud_rate)
            
            # Test connection by getting device info
            self.manager = ESP32FileManager(self.proto)
            info = self.manager.get_device_info()
            
            logger.info("[OK] Connected to ESP32")
            logger.info(f"    Device: {info.device_name}")
            logger.info(f"    Firmware: {info.fw_version}")
            logger.info(f"    SD Card: {'Present' if info.sd_present else 'Not detected'}")
            
            if not info.sd_present:
                logger.warning("WARNING: No SD card detected on ESP32!")
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to connect to ESP32: {e}")
            return False
    
    def start_webdav_server(self):
        """Start the WebDAV HTTP server."""
        try:
            # Create WebDAV provider
            provider = ESP32WebDAVProvider(self.manager)
            
            # Configure WsgiDAV
            config = {
                "host": self.host,
                "port": self.webdav_port,
                "provider_mapping": {"/": provider},
                "simple_dc": {"user_mapping": {"*": True}},  # Anonymous access
                "verbose": 1,
                "logging": {
                    "enable": True,
                    "enable_loggers": []
                },
                "dir_browser": {
                    "enable": True  # Enable web browser interface
                }
            }
            
            app = WsgiDAVApp(config)
            self.server = wsgi.Server((self.host, self.webdav_port), app)
            
            logger.info(f"[OK] WebDAV server started on http://{self.host}:{self.webdav_port}")
            logger.info(f"    Mount URL: http://{self.host}:{self.webdav_port}/")
            
            # Auto-mount on Windows
            if self.auto_mount and self.platform == "Windows":
                threading.Thread(target=self._auto_mount_windows, daemon=True).start()
            else:
                self._print_manual_mount_instructions()
            
            # Start server (blocking)
            self.running = True
            self.server.start()
        
        except Exception as e:
            logger.error(f"Failed to start WebDAV server: {e}")
            self.running = False
    
    def _auto_mount_windows(self):
        """Auto-mount WebDAV share on Windows."""
        time.sleep(2)  # Wait for server to fully start
        
        logger.info("Starting WebClient service...")
        os.system("sc config webclient start=auto >nul 2>&1")
        os.system("sc start webclient >nul 2>&1")
        time.sleep(1)
        
        logger.info(f"Mounting network drive {self.mount_drive}...")
        
        # Unmount if already exists
        os.system(f"net use {self.mount_drive} /delete /y >nul 2>&1")
        
        # Mount WebDAV share
        # Windows requires DavWWWRoot in the path for WebDAV
        webdav_url = f"http://{self.host}:{self.webdav_port}"
        mount_cmd = f'net use {self.mount_drive} "{webdav_url}" /persistent:no'
        
        result = os.system(mount_cmd)
        
        if result == 0:
            logger.info(f"[OK] ESP32 filesystem mounted as {self.mount_drive}")
            logger.info(f"    You can now access it in Windows Explorer!")
        else:
            logger.error(f"[FAIL] Failed to mount drive {self.mount_drive}")
            logger.error("      Try mounting manually:")
            logger.error(f"      1. Open Windows Explorer")
            logger.error(f"      2. Type in address bar: \\\\{self.host}@{self.webdav_port}\\DavWWWRoot")
            logger.error(f"      3. Or use: net use {self.mount_drive} {webdav_url}")
    
    def _print_manual_mount_instructions(self):
        """Print manual mounting instructions for current platform."""
        logger.info("\n" + "="*70)
        logger.info("WEBDAV MOUNT INSTRUCTIONS")
        logger.info("="*70)
        
        if self.platform == "Windows":
            logger.info("Windows Explorer:")
            logger.info(f"  1. Open Explorer and type: \\\\{self.host}@{self.webdav_port}\\DavWWWRoot")
            logger.info(f"  2. Or run: net use {self.mount_drive} http://{self.host}:{self.webdav_port}")
        
        elif self.platform == "Linux":
            logger.info("Linux (davfs2):")
            logger.info(f"  sudo mount -t davfs http://{self.host}:{self.webdav_port} /mnt/esp32")
            logger.info("")
            logger.info("Linux (File Manager):")
            logger.info(f"  Nautilus/Dolphin: Connect to Server → dav://{self.host}:{self.webdav_port}")
        
        elif self.platform == "Darwin":  # macOS
            logger.info("macOS Finder:")
            logger.info(f"  1. Go → Connect to Server (Cmd+K)")
            logger.info(f"  2. Enter: http://{self.host}:{self.webdav_port}")
            logger.info(f"  3. Click Connect")
        
        logger.info("")
        logger.info("Web Browser (all platforms):")
        logger.info(f"  http://{self.host}:{self.webdav_port}")
        logger.info("="*70 + "\n")
    
    def stop(self):
        """Stop the WebDAV server and disconnect from ESP32."""
        logger.info("Shutting down WebDAV server...")
        
        self.running = False
        
        # Unmount Windows drive
        if self.auto_mount and self.platform == "Windows" and self.mount_drive:
            logger.info(f"Unmounting {self.mount_drive}...")
            os.system(f"net use {self.mount_drive} /delete /y >nul 2>&1")
        
        # Stop HTTP server
        if self.server:
            self.server.stop()
        
        # Disconnect from ESP32
        if self.proto:
            self.proto.disconnect()
        
        logger.info("[OK] Shutdown complete")
    
    def _create_systray_icon(self) -> Optional[Image.Image]:
        """Create system tray icon image."""
        if not _SYSTRAY_AVAILABLE:
            return None
        
        # Generate a simple icon: blue square with "ESP" text
        image = Image.new('RGB', (64, 64), color=(0, 0, 0))
        dc = ImageDraw.Draw(image)
        dc.rectangle((12, 12, 52, 52), fill=(0, 128, 255))
        dc.text((18, 24), "ESP", fill=(255, 255, 255))
        return image
    
    def run_with_systray(self):
        """Run server with system tray icon (Windows only)."""
        if not self.enable_systray or not _SYSTRAY_AVAILABLE:
            raise RuntimeError("System tray not available. Install with: pip install esp-uart-filebridge[webdav]")
        
        # Start server in background thread
        self.server_thread = threading.Thread(target=self.start_webdav_server, daemon=True)
        self.server_thread.start()
        
        # Setup system tray icon (must run in main thread)
        image = self._create_systray_icon()
        menu = pystray.Menu(
            pystray.MenuItem('ESP32 WebDAV Server', None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f'Drive: {self.mount_drive}', None, enabled=False),
            pystray.MenuItem(f'Port: {self.port_name}', None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit', self._on_systray_quit)
        )
        
        self.systray_icon = pystray.Icon(
            "ESP32-WebDAV",
            image,
            f"ESP32 WebDAV ({self.mount_drive})",
            menu
        )
        
        logger.info("[OK] System tray icon running")
        logger.info("     Right-click the tray icon to quit")
        
        # Run system tray (blocking)
        self.systray_icon.run()
    
    def _on_systray_quit(self, icon, item):
        """System tray quit callback."""
        logger.info("Quit requested from system tray")
        icon.stop()
        self.stop()
        # Force exit to ensure all threads terminate
        os._exit(0)
    
    def run(self):
        """
        Run the WebDAV server.
        
        Uses system tray on Windows if enabled, otherwise runs in console.
        """
        # Connect to ESP32
        if not self.connect_esp32():
            logger.error("Cannot start server without ESP32 connection")
            return False
        
        try:
            # Run with systray on Windows if enabled
            if self.enable_systray and self.platform == "Windows":
                self.run_with_systray()
            else:
                # Run in console (blocking)
                self.start_webdav_server()
        
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user (Ctrl+C)")
        
        finally:
            self.stop()
        
        return True


def start_webdav_server(port: str, baud: int = 3000000, host: str = "127.0.0.1",
                       webdav_port: int = 8080, systray: bool = True,
                       auto_mount: bool = True, drive: Optional[str] = None) -> int:
    """
    Start ESP32 WebDAV server (main entry point).
    
    Args:
        port: Serial port name
        baud: Baud rate (default: 3 Mbps)
        host: HTTP server host (default: localhost)
        webdav_port: HTTP server port (default: 8080)
        systray: Enable system tray icon (Windows only)
        auto_mount: Auto-mount network drive (Windows only)
        drive: Drive letter (Windows only, auto-detect if None)
    
    Returns:
        Exit code (0 = success)
    """
    server = ESP32WebDAVServer(
        port_name=port,
        baud_rate=baud,
        host=host,
        webdav_port=webdav_port,
        enable_systray=systray,
        auto_mount=auto_mount,
        mount_drive=drive
    )
    
    success = server.run()
    return 0 if success else 1
