/*
 * esp-uart-filebridge - Filesystem Manager
 *
 * Internal implementation interface. This header is kept in the component
 * include tree because the implementation is split across translation units.
 */

#pragma once

#include <cstdint>
#include <cstdio>
#include <dirent.h>
#include "sdkconfig.h"
#include "esp_err.h"
#include "esp_vfs.h"
#include "esp_vfs_fat.h"
#include "sdmmc_cmd.h"

class FilesystemManager {
public:
    FilesystemManager();
    ~FilesystemManager();

    FilesystemManager(const FilesystemManager&) = delete;
    FilesystemManager& operator=(const FilesystemManager&) = delete;

    esp_err_t init(const char* mount_point = CONFIG_UART_FILEBRIDGE_SD_MOUNT_POINT,
                   bool do_mount = CONFIG_UART_FILEBRIDGE_SD_MOUNT_OWN);
    esp_err_t mount_sd();
    void unmount_sd();

    bool is_sd_mounted() const { return m_sd_mounted; }
    const char* get_mount_point() const { return m_mount_point; }
    sdmmc_card_t* get_sd_card_info() { return m_sd_card; }

    esp_err_t get_space_info(const char* path, uint64_t* total_bytes, uint64_t* free_bytes);
    esp_err_t list_directory(const char* path,
                             void (*callback)(const char* name, uint64_t size,
                                              bool is_dir, uint32_t timestamp, void* user_data),
                             void* user_data);
    esp_err_t stat_file(const char* path, uint64_t* size, uint32_t* timestamp, bool* is_dir);
    esp_err_t delete_file(const char* path);
    esp_err_t rename_file(const char* old_path, const char* new_path);
    esp_err_t create_directory(const char* path);
    esp_err_t copy_file(const char* src_path, const char* dst_path);
    esp_err_t hash_file(const char* path, uint32_t* hash);
    esp_err_t format_sd();
    esp_err_t validate_path(const char* path);

private:
    bool m_initialized = false;
    bool m_sd_mounted = false;
    bool m_owns_mount = false;
    char m_mount_point[64] = "/sd";

    sdmmc_card_t* m_sd_card = nullptr;
    void* m_sd_pwr_ctrl = nullptr;

    bool is_sd_path(const char* path);
    esp_err_t delete_directory_recursive(const char* path);
};