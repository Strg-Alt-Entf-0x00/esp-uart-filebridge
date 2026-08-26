cmake_minimum_required(VERSION 3.16)

# The repository root is the managed ESP-IDF component. Python tools and
# examples are kept alongside the component sources but are not registered.

idf_component_register(
    SRCS
        "src/esp_uart_filebridge.cpp"
        "src/file_protocol.cpp"
        "src/filesystem_manager.cpp"
    INCLUDE_DIRS
        "include"
    PRIV_INCLUDE_DIRS
        "src/internal"
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
