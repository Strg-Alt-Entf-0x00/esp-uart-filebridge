# Changelog

All notable changes to esp-uart-filebridge are documented here.
Format: Keep a Changelog (https://keepachangelog.com/en/1.0.0/)
Versioning: Semantic Versioning (https://semver.org/)

## [Unreleased]

## [1.0.0] - 2026-08-23

### Added
- Initial release extracted from firered-vad-esp32-p4 project
- Binary protocol v1.0 with CRC32, sequence numbers, 8KB chunked transfer
- FileProtocol class: full command set (HELLO, DEVICE_INFO, LIST, STAT, GET, PUT, DELETE,
  RENAME, MKDIR, COPY, HASH_FILE, FORMAT_FS, SPACE_INFO)
- FilesystemManager class: SD card (FAT32/exFAT) with POSIX VFS interface
- Multi-target support: ESP32, S3, C6, P4 with Kconfig-controlled P4 LDO power
- esp_uart_filebridge_init() top-level API with config struct and sensible defaults
- Streaming upload without per-chunk ACK (Hardware Flow Control backpressure)
- Benchmark mode (/dev/null) for pure UART throughput measurement
- Log suppression during active transfers for optimal SD write performance
- Python package esp_uart_filebridge with protocol.py, file_manager.py, cli.py
- basic_transfer example application

### Changed
- Major README.md overhaul with real-world ESP32-P4 UART speed benchmarks (up to ~285 KB/s)

### Fixed
- Fixed method routing bugs in Python CLI (esp-file-bridge) for upload and download commands
- Cleaned up dangling legacy configuration dependencies (esp32_config.py) in Python tools