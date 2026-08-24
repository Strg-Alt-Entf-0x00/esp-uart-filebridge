"""
WebDAV server module for esp-uart-filebridge.

Provides a WebDAV interface to ESP32 filesystem, allowing users to mount
the ESP32 SD card as a network drive for drag-and-drop file management.

Optional module requiring: wsgidav, cheroot, pystray (system tray), pillow (icon)
"""

__all__ = ['ESP32WebDAVProvider', 'start_webdav_server']

try:
    from .provider import ESP32WebDAVProvider
    from .server import start_webdav_server
    _WEBDAV_AVAILABLE = True
except ImportError:
    _WEBDAV_AVAILABLE = False
    ESP32WebDAVProvider = None
    start_webdav_server = None

def is_available():
    """Check if WebDAV dependencies are installed."""
    return _WEBDAV_AVAILABLE
