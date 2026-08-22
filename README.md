# esp-uart-filebridge

Universal ESP32 UART File Bridge - IDF Component for reliable file transfer between an ESP32
and a host PC over UART, optimised for use with FT232R USB-UART adapters.

## Features

- Binary protocol with CRC32 integrity verification and sequence numbering
- Full filesystem operations: upload, download, list, delete, rename, mkdir, copy, hash
- Streaming upload (no per-chunk ACK) with Hardware Flow Control (RTS/CTS) for maximum throughput
- Log suppression during transfers for optimal SD card write performance
- Benchmark mode (/dev/null) for pure UART throughput measurement
- Multi-target: ESP32, ESP32-S3, ESP32-C6, ESP32-P4 (P4 LDO power control via Kconfig)
- Python package included: pip install -e ./python

## Hardware Requirements

- ESP32 with UART peripheral (any variant)
- FT232R USB-UART adapter (recommended, tested @ 3 Mbit/s + HW Flow Control)
  Compatible with: CH343P, CP2102N, or any USB-UART chip supporting >= 3 Mbit/s + RTS/CTS
- SD card (FAT32 or exFAT)

## Quick Start

### 1. Add to your project

Add to your project's `main/idf_component.yml`:

```yaml
dependencies:
  ghost/esp-uart-filebridge:
    git: https://github.com/Ghost/esp-uart-filebridge.git
    version: ">=1.0.0"
```

Then run: `idf.py update-dependencies`

For local development:
```yaml
dependencies:
  esp-uart-filebridge:
    path: "D:/github-repositorys/esp-uart-filebridge"
```

### 2. Initialize in your app

```c
#include "esp_uart_filebridge.h"

esp_uart_filebridge_config_t cfg = ESP_UART_FILEBRIDGE_CONFIG_DEFAULT();
cfg.uart_num  = UART_NUM_1;
cfg.tx_pin    = 30;
cfg.rx_pin    = 31;
cfg.rts_pin   = 50;
cfg.cts_pin   = 29;
cfg.baud_rate = 3000000;

ESP_ERROR_CHECK(esp_uart_filebridge_init(&cfg));
```

### 3. Use the Python tool

```bash
pip install -e ./python
python -m esp_uart_filebridge upload model.frvd /sd/models/ --port COM4
python -m esp_uart_filebridge ls /sd/ --port COM4
python -m esp_uart_filebridge download /sd/log.txt ./log.txt --port COM4
```

## Protocol

Binary frame format:

```
[MAGIC_0=0xF1] [MAGIC_1=0x1E] [VERSION] [CMD] [FLAGS] [SEQ_LSB] [SEQ_MSB] [LEN_LSB] [LEN_MSB] [PAYLOAD...] [CRC32]
```

Frame size: 9 byte header + payload (max 32 KB) + 4 byte CRC32.
Chunk size: 8 KB for optimal SD write alignment.

## Kconfig

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
| `UART_FILEBRIDGE_RX_BUF` | 8192 | RX buffer size |
| `UART_FILEBRIDGE_TASK_STACK` | 16384 | RX task stack size |
| `UART_FILEBRIDGE_TASK_PRIO` | 5 | RX task priority |
| `UART_FILEBRIDGE_P4_LDO` | y (P4 only) | Enable ESP32-P4 SD LDO power ctrl |
| `UART_FILEBRIDGE_P4_LDO_CHAN` | 4 | LDO channel for P4 SD power |

## Performance

Tested on ESP32-P4 @ 360 MHz with FT232R @ 3 Mbit/s + RTS/CTS:

| Operation | Throughput |
|---|---|
| Upload (PC -> SD) | ~285 KB/s |
| Download (SD -> PC) | ~285 KB/s |
| Pure UART (/dev/null benchmark) | ~330 KB/s |

## License

MIT - see LICENSE file.
