cmake_minimum_required(VERSION 3.16)

# This CMakeLists.txt serves as a wrapper for the actual component
# located in components/esp_uart_filebridge/
# It allows the entire repository (with python/ tools) to be used
# as a managed component while keeping the modular structure.

idf_component_register(
    SRCS
        "components/esp_uart_filebridge/src/esp_uart_filebridge.cpp"
        "components/esp_uart_filebridge/src/file_protocol.cpp"
        "components/esp_uart_filebridge/src/filesystem_manager.cpp"
    INCLUDE_DIRS
        "components/esp_uart_filebridge/include"
    REQUIRES
        driver
        esp_driver_uart
        esp_psram
        fatfs
        sdmmc
        vfs
        freertos
        log
)
