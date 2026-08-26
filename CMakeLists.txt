cmake_minimum_required(VERSION 3.16)

# The repository root is the managed ESP-IDF component. Python tools and
# examples are kept alongside the component sources but are not registered.

idf_component_register(
    SRCS
        "components/esp_uart_filebridge/src/esp_uart_filebridge.cpp"
        "components/esp_uart_filebridge/src/file_protocol.cpp"
        "components/esp_uart_filebridge/src/filesystem_manager.cpp"
    INCLUDE_DIRS
        "components/esp_uart_filebridge/include"
    PRIV_INCLUDE_DIRS
        "components/esp_uart_filebridge/src/internal"
    REQUIRES
        esp_driver_uart
    PRIV_REQUIRES
        esp_psram
        fatfs
        sdmmc
        vfs
        freertos
        log
)
