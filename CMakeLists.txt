cmake_minimum_required(VERSION 3.16)

idf_component_register(
    SRCS
        "src/esp_uart_filebridge.c"
        "src/file_protocol.cpp"
        "src/filesystem_manager.cpp"
    INCLUDE_DIRS
        "include"
    REQUIRES
        driver
        esp_driver_uart
        esp_psram
        fatfs
        sdmmc
        vfs
        freertos
        log
        newlib
)
