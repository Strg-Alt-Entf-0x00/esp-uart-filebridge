"""
esp_uart_filebridge - Host-side Python package for ESP32 UART file bridge.

Usage:
    from esp_uart_filebridge import FileManager

    fm = FileManager("COM4", baud=3000000)
    fm.connect()
    fm.upload_file("local_file.bin", "/sd/data/local_file.bin")
    fm.list_directory("/sd/")
    fm.download_file("/sd/data/local_file.bin", "local_copy.bin")
    fm.disconnect()
"""

from .file_manager import ESP32FileManager as FileManager
from .protocol import ESP32Protocol as Protocol

__version__ = "1.0.0"
__all__ = ["FileManager", "Protocol"]
