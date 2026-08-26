# esp-uart-filebridge

Universal ESP32 UART File Bridge - A highly optimized IDF Component for reliable file transfer between an ESP32 and a host PC over UART.

## Why does this exist? (The Honest Truth)

In the ESP32 ecosystem, transferring large files and directory trees to an SD card usually involves WiFi (which can be slow or unreliable) or WebUSB/Native USB (which adds hardware and driver complexity).

We built **esp-uart-filebridge** to provide a deterministic way to transfer arbitrary files and directory trees to an ESP32 filesystem without relying on a network stack.

UART is an ancient protocol, but when implemented correctly, it is **rock solid**. By using a high-quality USB-UART adapter (like the FT232R) with Hardware Flow Control (RTS/CTS) pushed to **3,000,000 Baud**, we achieved stable speeds that rival basic WiFi setups—without any of the software overhead.

### Pros:
- **Reliable transfers:** CRC32, strict upload-size validation and hardware flow control (RTS/CTS) detect transfer errors.
- **Zero Network Overhead:** No WiFi, no IP stacks, no router needed. Pure serial communication.
- **Highly Performant for UART:** We push standard UART to its absolute limits, achieving near-theoretical maximum throughput.
- **Configurable:** Supports the ESP32 targets and storage arrangements supported by the selected ESP-IDF configuration.

### Cons:
- **Hardware Requirement:** You must wire up an external USB-UART adapter with 4 pins (TX, RX, RTS, CTS). A simple 2-pin TX/RX connection will drop packets at these speeds.
- **Absolute Speed Limit:** You will never exceed ~330 KB/s due to UART protocol overhead (start/stop bits). If you need Megabytes-per-second, this is the wrong tool; you must use native SDIO or USB MSC (Mass Storage Class), which are significantly more complex to implement.

---

## ⚡ Real-World Performance

Measured on one ESP32-P4 setup (360 MHz) using an FT232R adapter at **3,000,000 baud** with Hardware Flow Control enabled.

| Scenario | File Size | Upload (PC -> SD) | Download (SD -> PC) |
|---|---|---|---|
| **Small File** (Overhead Test) | 1 KB | ~0.22s | ~0.22s |
| **Large File** (Throughput Test) | 1 MiB | ~4.5s (**~227 KiB/s**) | ~3.7s (**~278 KiB/s**) |
| **Raw UART Limit** (No SD write) | 2 MB | ~8.7s (**~236 KiB/s**) | N/A |

*Note: These are setup-specific measurements, not universal guarantees. They should be re-measured after protocol, buffer, UART, or hardware changes. Performance depends on the adapter, wiring, UART configuration and SD card.*

## Verification status

The current live regression on the validated setup passed **10/10 tests**:

- setup and connection
- device info query
- directory creation and listing
- upload of multiple file sizes
- download and verification of multiple file sizes
- CRC32 validation
- delete operations
- streaming upload
- UART throughput benchmark

This is a strong functional verification for the current firmware and host implementation, but it is not the same as a final public release gate. Any protocol, serial, or performance-affecting change should be followed by a fresh measurement and live regression run.

---

## Repository Structure

```
esp-uart-filebridge/
├── components/
│   └── esp_uart_filebridge/      # The ESP-IDF component
│       ├── include/               # Public API headers
│       ├── src/                   # Implementation
│       ├── CMakeLists.txt
│       ├── idf_component.yml
│       ├── Kconfig
│       └── README.md
├── examples/
│   └── basic_transfer/            # Complete working example
│       ├── main/
│       ├── CMakeLists.txt
│       └── sdkconfig.defaults
├── python/                        # Python CLI and WebDAV tools
│   ├── esp_uart_filebridge/
│   ├── pyproject.toml
│   └── test_all.py
└── README.md                      # This file
```

---

## Features

- **Binary protocol** with CRC32 integrity verification and sequence numbering.
- **Full filesystem operations:** upload, download, list, delete, rename, mkdir, copy, hash.
- **Streaming upload** (no per-chunk ACK) with Hardware Flow Control (RTS/CTS) for maximum throughput.
- **Log suppression** during transfers for optimal SD card write performance.
- **Optional WebDAV server** for convenient local file management.
- **Multi-target:** ESP32, ESP32-S3, ESP32-C6, ESP32-P4 (P4 LDO power control via Kconfig).
- **Python CLI Tool** included out of the box.
- **WebDAV Server** (optional) - Mount ESP32 as a local network drive for drag-and-drop file management.

---

## Hardware Requirements

- ESP32 with UART peripheral (any variant).
- USB-UART adapter (recommended: FT232R, tested @ 3 Mbit/s + HW Flow Control).
  - *Compatible with: FT232R, CH343P, CP2102N, or any USB-UART chip supporting >= 3 Mbit/s + RTS/CTS.*
- SD card formatted as FAT32 or exFAT.

---

## Quick Start

### 1. Add Component to Your Project

Add the component to your project's `main/idf_component.yml`:

```yaml
dependencies:
  Strg-Alt-Entf-0x00/esp-uart-filebridge:
    git: https://github.com/Strg-Alt-Entf-0x00/esp-uart-filebridge.git
```

Then run: `idf.py update-dependencies`

*(For local development, you can use `path: "../esp-uart-filebridge/components/esp_uart_filebridge"` instead of `git`)*

### 2. Initialize in Your Firmware

```c
#include "esp_uart_filebridge.h"

// Initialize configuration with defaults
esp_uart_filebridge_config_t cfg = ESP_UART_FILEBRIDGE_CONFIG_DEFAULT();

// Set your specific pins
cfg.uart_num  = UART_NUM_1;
cfg.tx_pin    = 30;
cfg.rx_pin    = 31;
cfg.rts_pin   = 50;  // Required for high-speed reliability
cfg.cts_pin   = 29;  // Required for high-speed reliability
cfg.baud_rate = 3000000;

// Start the background task
ESP_ERROR_CHECK(esp_uart_filebridge_init(&cfg));
```

### 3. Try the Example

```bash
cd examples/basic_transfer
idf.py build flash monitor
```

### 4. Install Python Tools

Install the companion Python package:
```bash
# Basic installation (CLI only)
pip install -e ./python

# With WebDAV server support (optional)
pip install -e "./python[webdav]"
```

### 5. Choose Your Interface

**Option A: Command-Line Interface (Fast & Scriptable)**
```bash
# Upload a file
esp-file-bridge --port COM13 upload ./local_file.bin /sd/data/local_file.bin

# List SD card contents
esp-file-bridge --port COM13 ls /sd/

# Download a file
esp-file-bridge --port COM13 download /sd/log.txt ./log.txt

# Upload entire directory, preserving its tree
esp-file-bridge --port COM13 upload_dir ./local_directory /sd/data/
```

**Option B: WebDAV Server (Drag & Drop in Explorer)** *(requires `[webdav]` extras)*
```bash
# Start WebDAV server
esp-file-bridge --port COM13 webdav

# Windows: Opens as Z: drive automatically
# Linux/Mac: Follow on-screen mount instructions
# All: Access via web browser at http://localhost:8080
```

The ESP32 SD card will appear as a network drive - drag and drop files like a USB stick!

---

## Kconfig Configuration

All pins and transfer parameters are configurable via `idf.py menuconfig` under
`Component config -> ESP UART File Bridge`:

| Option | Default | Description |
|---|---|---|
| `UART_FILEBRIDGE_NUM` | 1 | UART port number |
| `UART_FILEBRIDGE_TX_PIN` | 30 | TX GPIO |
| `UART_FILEBRIDGE_RX_PIN` | 31 | RX GPIO |
| `UART_FILEBRIDGE_RTS_PIN` | 50 | RTS GPIO (HW flow ctrl) |
| `UART_FILEBRIDGE_CTS_PIN` | 29 | CTS GPIO (HW flow ctrl) |
| `UART_FILEBRIDGE_BAUD` | 3000000 | Baud rate |
| `UART_FILEBRIDGE_RX_BUF_SIZE` | 8192 | RX buffer size |
| `UART_FILEBRIDGE_TASK_STACK` | 16384 | RX task stack size |
| `UART_FILEBRIDGE_TASK_PRIO` | 5 | RX task priority |
| `UART_FILEBRIDGE_P4_LDO_ENABLE` | y (P4 only) | Enable ESP32-P4 SD LDO power ctrl |
| `UART_FILEBRIDGE_P4_LDO_CHAN` | 4 | LDO channel for P4 SD power |

## Protocol Architecture

The underlying binary protocol is designed for minimal overhead while guaranteeing data integrity.

**Binary frame format:**
```
[MAGIC_0=0xF1] [MAGIC_1=0x1E] [VERSION] [CMD] [FLAGS] [SEQ_LSB] [SEQ_MSB] [LEN_LSB] [LEN_MSB] [PAYLOAD...] [CRC32]
```

- **Frame size:** 9 byte header + payload (max 32 KB) + 4 byte CRC32.
- **Chunk size:** Defaults to 8 KB to perfectly align with optimal SD card sector writes.

---

## WebDAV Server (Optional Feature)

The WebDAV server provides a user-friendly way to access the ESP32 filesystem through native OS file explorers.

### Installation

```bash
pip install -e "./python[webdav]"
```

This installs additional dependencies: `wsgidav`, `cheroot`, `pystray` (Windows), `pillow`

### Usage

```bash
esp-file-bridge --port COM13 webdav
```

**What happens:**
- Starts HTTP WebDAV server on `http://localhost:8080`
- **Windows:** Auto-mounts as network drive (Z:) + system tray icon
- **Linux:** Instructions for `davfs2` or file manager mounting
- **macOS:** Instructions for Finder mounting
- **All platforms:** Web browser interface at `http://localhost:8080`

### Platform-Specific Mounting

**Windows:**
```cmd
# Automatic (default)
esp-file-bridge --port COM13 webdav

# Manual mount
net use Z: http://localhost:8080
# Or in Explorer: \\localhost@8080\DavWWWRoot
```

**Linux:**
```bash
# Using davfs2
sudo mount -t davfs http://localhost:8080 /mnt/esp32

# Using file manager (Nautilus/Dolphin)
# Connect to Server → dav://localhost:8080
```

**macOS:**
```bash
# Finder → Go → Connect to Server (Cmd+K)
# Enter: http://localhost:8080
```

### WebDAV Options

```bash
esp-file-bridge --port COM13 webdav \
  --host 127.0.0.1 \           # Server bind address
  --webdav-port 8080 \         # HTTP port
  --no-systray \               # Disable system tray (Windows)
  --no-mount \                 # Disable auto-mount (Windows)
  --drive Y:                   # Custom drive letter (Windows)
```

### When to Use WebDAV vs CLI

| Use Case | Recommended Tool |
|----------|------------------|
| Automation, CI/CD, scripts | **CLI** (faster, scriptable) |
| Manual file management | **WebDAV** (drag & drop) |
| Large batch uploads | **CLI** (progress tracking) |
| Quick edits, browsing | **WebDAV** (visual) |
| Embedded in applications | **CLI** (Python API) |
| End-user deployment | **WebDAV** (user-friendly) |

---

## License

MIT - see LICENSE file.
