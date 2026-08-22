/**
 * @file main.c
 * @brief esp-uart-filebridge basic example
 *
 * Initializes the UART file bridge with default Kconfig settings.
 * After flashing, connect FT232R to GPIO30(TX)/31(RX)/50(RTS)/29(CTS)
 * and use the Python CLI to transfer files.
 *
 * Tested on: ESP32-P4 (Waveshare ESP32-P4-WIFI6) with FT232R @ 3 Mbit/s
 */

#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_uart_filebridge.h"

static const char *TAG = "example";

void app_main(void) {
    /* NVS required by some IDF subsystems */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    /* Initialize file bridge with Kconfig defaults.
     * Override individual fields for your board: */
    esp_uart_filebridge_config_t cfg = ESP_UART_FILEBRIDGE_CONFIG_DEFAULT();
    /* Example overrides:
     *   cfg.tx_pin    = 17;
     *   cfg.rx_pin    = 16;
     *   cfg.baud_rate = 921600;   // Slower if FT232R not rated for 3 Mbit/s
     */

    ESP_ERROR_CHECK(esp_uart_filebridge_init(&cfg));

    ESP_LOGI(TAG, "UART file bridge ready.");
    ESP_LOGI(TAG, "Connect FT232R and run: esp-file-bridge info --port COM4");

    /* Application loop - bridge runs in background RX task */
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(5000));
        if (esp_uart_filebridge_is_running()) {
            ESP_LOGI(TAG, "Bridge running. Heap free: %u bytes",
                     esp_get_free_heap_size());
        }
    }
}
