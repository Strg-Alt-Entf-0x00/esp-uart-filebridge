/*
 * esp-uart-filebridge - Filesystem Manager
 *
 * Unified POSIX/VFS interface for SD card (FAT32/exFAT).
 * Multi-target: ESP32, ESP32-S3, ESP32-C6, ESP32-P4.
 * Mount point and SD pins are configured via Kconfig or passed to init().
 */

#pragma once

#include <cstdint>
#include <cstdio>
#include <dirent.h>
#include "esp_err.h"
#include "esp_vfs.h"
#include "esp_vfs_fat.h"
#include "sdmmc_cmd.h"

class FilesystemManager {
public:
    FilesystemManager();
    ~FilesystemManager();

    // Non-copyable
    FilesystemManager(const FilesystemManager&) = delete;
    FilesystemManager& operator=(const FilesystemManager&) = delete;

    /**
     * Initialize filesystem manager and optionally mount SD card.
     *
     * @param mount_point  VFS path (e.g. "/sd"). Defaults to Kconfig value.
     * @param do_mount     true = mount SD card now. false = SD already mounted externally.
     * @return ESP_OK on success (SD mount failure is non-fatal, logged as warning)
     */
    esp_err_t init(const char* mount_point = CONFIG_UART_FILEBRIDGE_SD_MOUNT_POINT,
                   bool do_mount = CONFIG_UART_FILEBRIDGE_SD_MOUNT_OWN);

    /**
     * Mount SD card (FAT32/exFAT).
     * Called automatically by init() when do_mount == true.
     * @return ESP_OK on success
     */
    esp_err_t mount_sd();

    /**
     * Unmount SD card. Called automatically in destructor.
     */
    void unmount_sd();

    /** @return true if SD card is currently mounted */
    bool is_sd_mounted() const { return m_sd_mounted; }

    /** @return sdmmc_card_t handle for card info, or nullptr */
    sdmmc_card_t* get_sd_card_info() { return m_sd_card; }

    /**
     * Get filesystem space information.
     * @param path         Mount point path (e.g. "/sd")
     * @param total_bytes  Output: total capacity in bytes
     * @param free_bytes   Output: free space in bytes
     */
    esp_err_t get_space_info(const char* path, uint64_t* total_bytes, uint64_t* free_bytes);

    /**
     * List directory contents. Calls callback for each entry.
     * @param path      Directory path (e.g. "/sd/models")
     * @param callback  Called per entry: name, size, is_dir, mtime, user_data
     * @param user_data Passed through to callback
     */
    esp_err_t list_directory(const char* path,
                             void (*callback)(const char* name, uint64_t size,
                                             bool is_dir, uint32_t timestamp, void* user_data),
                             void* user_data);

    /** Get file statistics (size, mtime, is_dir). */
    esp_err_t stat_file(const char* path, uint64_t* size, uint32_t* timestamp, bool* is_dir);

    /** Delete file or directory (recursive for non-empty directories). */
    esp_err_t delete_file(const char* path);

    /** Rename/move file or directory. */
    esp_err_t rename_file(const char* old_path, const char* new_path);

    /** Create directory (single level, parent must exist). */
    esp_err_t create_directory(const char* path);

    /** Copy file (within same or between mounted volumes). */
    esp_err_t copy_file(const char* src_path, const char* dst_path);

    /** Calculate CRC32 (IEEE 802.3) hash of file contents. */
    esp_err_t hash_file(const char* path, uint32_t* hash);

    /** Format SD card (WARNING: destroys all data). */
    esp_err_t format_sd();

    /** Validate that a path stays inside the configured SD mount point. */
    esp_err_t validate_path(const char* path);

private:
    bool m_initialized  = false;
    bool m_sd_mounted   = false;
    bool m_owns_mount   = false;  // true = we mounted, we must unmount
    char m_mount_point[16] = "/sd";

    sdmmc_card_t* m_sd_card    = nullptr;
    void*         m_sd_pwr_ctrl = nullptr;  // ESP32-P4 LDO handle (or nullptr)

    bool      is_sd_path(const char* path);
    esp_err_t delete_directory_recursive(const char* path);
};
