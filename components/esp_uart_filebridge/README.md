# ESP UART File Bridge Component

Universal ESP32 UART File Bridge - A highly optimized IDF Component for reliable file transfer between an ESP32 and a host PC over UART.

## Component Overview

This is the core ESP-IDF component that provides UART-based file transfer functionality. For complete documentation, usage examples, and Python tools, see the main repository README.

## Integration

Add to your project's `idf_component.yml`:

```yaml
dependencies:
  Strg-Alt-Entf-0x00/esp-uart-filebridge:
    git: https://github.com/Strg-Alt-Entf-0x00/esp-uart-filebridge.git
```

## Basic Usage

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

## API Reference

### Main Functions

- `esp_uart_filebridge_init(config)` - Initialize and start the file bridge
- `esp_uart_filebridge_deinit()` - Stop and cleanup

### Configuration

All parameters are configurable via `idf.py menuconfig` under:
**Component config → ESP UART File Bridge**

## Examples

See the `examples/` directory in the repository root for complete working examples.

## License

MIT - see LICENSE file in repository root.
