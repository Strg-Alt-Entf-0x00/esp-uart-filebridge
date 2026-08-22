"""
esp_uart_filebridge - Host-side Python package for ESP32 UART file bridge.

Usage:
    from esp_uart_filebridge import FileManager

    fm = FileManager("COM4", baud=3000000)
    fm.upload("model.frvd", "/sd/models/model.frvd")
    fm.list_dir("/sd/")
    fm.download("/sd/log.txt", "log.txt")
    fm.close()
"""

from .file_manager import ESP32FileManager as FileManager
from .protocol import ESP32Protocol as Protocol

__version__ = "1.0.0"
__all__ = ["FileManager", "Protocol"]
