/*
 * esp-uart-filebridge - Top-Level Public API
 *
 * Single-call initialization for UART file bridge on ESP32.
 * Manages UART driver, FilesystemManager, FileProtocol, and RX task internally.
 *
 * Supported targets: ESP32, ESP32-S3, ESP32-C6, ESP32-P4
 * Primary tested hardware: FT232R USB-UART @ 3 Mbit/s + RTS/CTS
 */

#pragma once

#include <stdbool.h>
#include "sdkconfig.h"

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>
#include "esp_err.h"
#include "driver/uart.h"

/* ============================================================================
 * Configuration
 * ========================================================================== */

/**
 * Configuration for esp_uart_filebridge_init().
 * All fields have Kconfig-based defaults accessible via
 * ESP_UART_FILEBRIDGE_CONFIG_DEFAULT().
 */
typedef struct {
    uart_port_t uart_num;       /**< UART peripheral (UART_NUM_0/1/2) */
    int         tx_pin;         /**< TX GPIO, -1 = use Kconfig default */
    int         rx_pin;         /**< RX GPIO, -1 = use Kconfig default */
    int         rts_pin;        /**< RTS GPIO for HW flow ctrl, -1 = disabled */
    int         cts_pin;        /**< CTS GPIO for HW flow ctrl, -1 = disabled */
    int         baud_rate;      /**< Baud rate. FT232R max = 3000000 */
    int         rx_buf_size;    /**< UART HW RX ring buffer size (bytes) */
    int         tx_buf_size;    /**< UART HW TX ring buffer size (bytes) */
    int         task_stack;     /**< RX processing task stack size (bytes) */
    int         task_priority;  /**< RX task FreeRTOS priority */
    const char* sd_mount_point; /**< VFS mount point, e.g. "/sd" */
    bool        mount_sd_own;   /**< true = component mounts SD internally */
} esp_uart_filebridge_config_t;

/**
 * Default configuration populated from Kconfig values.
 * Override individual fields as needed.
 *
 * Example:
 *   esp_uart_filebridge_config_t cfg = ESP_UART_FILEBRIDGE_CONFIG_DEFAULT();
 *   cfg.tx_pin = 17;  // override TX pin for your board
 *   ESP_ERROR_CHECK(esp_uart_filebridge_init(&cfg));
 */
#define ESP_UART_FILEBRIDGE_CONFIG_DEFAULT() {                              \
    .uart_num      = (uart_port_t)CONFIG_UART_FILEBRIDGE_NUM,              \
    .tx_pin        = CONFIG_UART_FILEBRIDGE_TX_PIN,                        \
    .rx_pin        = CONFIG_UART_FILEBRIDGE_RX_PIN,                        \
    .rts_pin       = CONFIG_UART_FILEBRIDGE_RTS_PIN,                       \
    .cts_pin       = CONFIG_UART_FILEBRIDGE_CTS_PIN,                       \
    .baud_rate     = CONFIG_UART_FILEBRIDGE_BAUD,                          \
    .rx_buf_size   = CONFIG_UART_FILEBRIDGE_RX_BUF_SIZE,                   \
    .tx_buf_size   = CONFIG_UART_FILEBRIDGE_TX_BUF_SIZE,                   \
    .task_stack    = CONFIG_UART_FILEBRIDGE_TASK_STACK,                    \
    .task_priority = CONFIG_UART_FILEBRIDGE_TASK_PRIO,                     \
    .sd_mount_point = CONFIG_UART_FILEBRIDGE_SD_MOUNT_POINT,               \
    .mount_sd_own  = CONFIG_UART_FILEBRIDGE_SD_MOUNT_OWN,                  \
}

/* ============================================================================
 * Lifecycle
 * ========================================================================== */

/**
 * Initialize the UART file bridge.
 *
 * Performs in order:
 *   1. Install UART driver with HW flow control (if pins != -1)
 *   2. Optionally mount SD card (if cfg->mount_sd_own == true)
 *   3. Initialize FileProtocol handler
 *   4. Start background UART RX task
 *
 * @param cfg  Configuration. Must not be NULL. Use
 *             ESP_UART_FILEBRIDGE_CONFIG_DEFAULT() for sane defaults.
 * @return ESP_OK when the bridge starts. SD mount failure is non-fatal and
 *         makes file operations unavailable until storage is mounted.
 *         ESP_ERR_INVALID_ARG  if cfg is NULL
 *         ESP_ERR_INVALID_STATE if already initialized
 */
esp_err_t esp_uart_filebridge_init(const esp_uart_filebridge_config_t *cfg);

/**
 * Deinitialize the UART file bridge.
 *
 * Stops RX task, uninstalls UART driver, aborts any active transfer,
 * optionally unmounts SD card (if this component mounted it).
 *
 * @return ESP_OK always
 */
esp_err_t esp_uart_filebridge_deinit(void);

/**
 * Check if the bridge is initialized.
 * @return true if esp_uart_filebridge_init() succeeded
 */
bool esp_uart_filebridge_is_running(void);

#ifdef __cplusplus
}
#endif
