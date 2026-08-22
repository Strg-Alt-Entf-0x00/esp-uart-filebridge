/*
 * esp-uart-filebridge - Top-Level Init/Deinit Implementation
 *
 * Wires together: UART driver, FilesystemManager, FileProtocol, RX task.
 * Written as C to be usable from both C and C++ application code.
 */

#include "esp_uart_filebridge.h"
#include "file_protocol.h"
#include "filesystem_manager.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"

static const char *TAG = "uart_filebridge";

/* --------------------------------------------------------------------------
 * Module-private state
 * -------------------------------------------------------------------------- */
static FileProtocol     *s_protocol   = nullptr;
static FilesystemManager *s_fs_manager = nullptr;
static TaskHandle_t       s_rx_task   = nullptr;
static uart_port_t        s_uart_num  = UART_NUM_1;
static bool               s_running   = false;

/* --------------------------------------------------------------------------
 * UART TX callback (C linkage, passed into FileProtocol)
 * -------------------------------------------------------------------------- */
static esp_err_t uart_tx_cb(const uint8_t *data, size_t len) {
    int written = uart_write_bytes(s_uart_num, data, len);
    if (written < 0 || (size_t)written != len) {
        ESP_LOGE(TAG, "UART write error: expected %d wrote %d", (int)len, written);
        return ESP_FAIL;
    }
    return ESP_OK;
}

/* --------------------------------------------------------------------------
 * UART RX Task
 * -------------------------------------------------------------------------- */
static void uart_rx_task(void *arg) {
    const int buf_size = CONFIG_UART_FILEBRIDGE_RX_BUF_SIZE;
    uint8_t  *rx_buf   = (uint8_t *)malloc(buf_size);

    if (!rx_buf) {
        ESP_LOGE(TAG, "Failed to allocate RX buffer (%d bytes)", buf_size);
        vTaskDelete(NULL);
        return;
    }

    ESP_LOGI(TAG, "RX task started on UART%d", (int)s_uart_num);

    while (1) {
        int len = uart_read_bytes(s_uart_num, rx_buf, buf_size, pdMS_TO_TICKS(100));
        if (len > 0 && s_protocol) {
            s_protocol->process_rx_data(rx_buf, (size_t)len);
        }
    }

    /* Unreachable - task is deleted via esp_uart_filebridge_deinit() */
    free(rx_buf);
    vTaskDelete(NULL);
}

/* --------------------------------------------------------------------------
 * Public API
 * -------------------------------------------------------------------------- */
esp_err_t esp_uart_filebridge_init(const esp_uart_filebridge_config_t *cfg) {
    if (!cfg) {
        ESP_LOGE(TAG, "cfg must not be NULL");
        return ESP_ERR_INVALID_ARG;
    }
    if (s_running) {
        ESP_LOGW(TAG, "Already initialized");
        return ESP_ERR_INVALID_STATE;
    }

    s_uart_num = cfg->uart_num;

    /* ------------------------------------------------------------------ */
    /* 1. Install UART driver                                              */
    /* ------------------------------------------------------------------ */
    uart_config_t uart_cfg = {
        .baud_rate           = cfg->baud_rate,
        .data_bits           = UART_DATA_8_BITS,
        .parity              = UART_PARITY_DISABLE,
        .stop_bits           = UART_STOP_BITS_1,
        .flow_ctrl           = (cfg->rts_pin >= 0 && cfg->cts_pin >= 0)
                                ? UART_HW_FLOWCTRL_CTS_RTS
                                : UART_HW_FLOWCTRL_DISABLE,
        .rx_flow_ctrl_thresh = 96,
        .source_clk          = UART_SCLK_DEFAULT,
        .flags               = {},
    };

    esp_err_t ret = uart_param_config(cfg->uart_num, &uart_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uart_param_config failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = uart_set_pin(cfg->uart_num,
                       cfg->tx_pin, cfg->rx_pin,
                       (cfg->rts_pin >= 0) ? cfg->rts_pin : UART_PIN_NO_CHANGE,
                       (cfg->cts_pin >= 0) ? cfg->cts_pin : UART_PIN_NO_CHANGE);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uart_set_pin failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = uart_driver_install(cfg->uart_num,
                              cfg->rx_buf_size, cfg->tx_buf_size,
                              0, NULL, 0);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uart_driver_install failed: %s", esp_err_to_name(ret));
        return ret;
    }

    ESP_LOGI(TAG, "UART%d configured: %d baud, TX=%d RX=%d RTS=%d CTS=%d",
             (int)cfg->uart_num, cfg->baud_rate,
             cfg->tx_pin, cfg->rx_pin, cfg->rts_pin, cfg->cts_pin);

    /* ------------------------------------------------------------------ */
    /* 2. Filesystem Manager                                               */
    /* ------------------------------------------------------------------ */
    s_fs_manager = new FilesystemManager();
    if (!s_fs_manager) {
        ESP_LOGE(TAG, "FilesystemManager allocation failed");
        uart_driver_delete(cfg->uart_num);
        return ESP_ERR_NO_MEM;
    }

    ret = s_fs_manager->init(cfg->sd_mount_point, cfg->mount_sd_own);
    if (ret != ESP_OK) {
        /* Non-fatal warning already logged inside init() */
        ESP_LOGW(TAG, "Filesystem init returned: %s", esp_err_to_name(ret));
    }

    /* ------------------------------------------------------------------ */
    /* 3. File Protocol                                                    */
    /* ------------------------------------------------------------------ */
    s_protocol = new FileProtocol();
    if (!s_protocol) {
        ESP_LOGE(TAG, "FileProtocol allocation failed");
        delete s_fs_manager;
        s_fs_manager = nullptr;
        uart_driver_delete(cfg->uart_num);
        return ESP_ERR_NO_MEM;
    }

    ret = s_protocol->init(s_fs_manager);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "FileProtocol::init failed: %s", esp_err_to_name(ret));
        delete s_protocol;   s_protocol   = nullptr;
        delete s_fs_manager; s_fs_manager = nullptr;
        uart_driver_delete(cfg->uart_num);
        return ret;
    }

    s_protocol->set_tx_callback(uart_tx_cb);

    /* ------------------------------------------------------------------ */
    /* 4. Start RX Task                                                    */
    /* ------------------------------------------------------------------ */
    BaseType_t rc = xTaskCreate(uart_rx_task, "uart_fb_rx",
                                cfg->task_stack, NULL,
                                cfg->task_priority, &s_rx_task);
    if (rc != pdPASS) {
        ESP_LOGE(TAG, "RX task creation failed");
        delete s_protocol;   s_protocol   = nullptr;
        delete s_fs_manager; s_fs_manager = nullptr;
        uart_driver_delete(cfg->uart_num);
        return ESP_ERR_NO_MEM;
    }

    s_running = true;
    ESP_LOGI(TAG, "esp-uart-filebridge initialized (SD at %s)", cfg->sd_mount_point);
    return ESP_OK;
}

esp_err_t esp_uart_filebridge_deinit(void) {
    if (!s_running) return ESP_OK;

    if (s_rx_task) {
        vTaskDelete(s_rx_task);
        s_rx_task = nullptr;
    }

    if (s_protocol) {
        delete s_protocol;
        s_protocol = nullptr;
    }

    if (s_fs_manager) {
        delete s_fs_manager;
        s_fs_manager = nullptr;
    }

    uart_driver_delete(s_uart_num);
    s_running = false;
    ESP_LOGI(TAG, "esp-uart-filebridge deinitialized");
    return ESP_OK;
}

bool esp_uart_filebridge_is_running(void) {
    return s_running;
}
