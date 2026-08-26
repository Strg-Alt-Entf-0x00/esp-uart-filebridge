/*
 * esp-uart-filebridge - Filesystem Manager Implementation
 *
 * Multi-target SD card management via ESP-IDF SDMMC + VFS FAT.
 * ESP32-P4 LDO power control is guarded by CONFIG_UART_FILEBRIDGE_P4_LDO_ENABLE.
 */

#include "filesystem_manager.h"
#include "esp_log.h"
#include "driver/sdmmc_host.h"
#include "driver/sdspi_host.h"
#include "esp_vfs_fat.h"
#include <sys/stat.h>
#include <sys/unistd.h>
#include <cstring>
#include <dirent.h>

/* ESP32-P4 requires on-chip LDO to power the SD card slot.
 * All other targets use external power - no special handling needed. */
#if defined(CONFIG_IDF_TARGET_ESP32P4) && defined(CONFIG_UART_FILEBRIDGE_P4_LDO_ENABLE)
#include "sd_pwr_ctrl_by_on_chip_ldo.h"
#define FILEBRIDGE_P4_LDO 1
#else
#define FILEBRIDGE_P4_LDO 0
#endif

static const char *TAG = "fs_manager";

FilesystemManager::FilesystemManager() {}

FilesystemManager::~FilesystemManager() {
    if (m_owns_mount) {
        unmount_sd();
    }
}

esp_err_t FilesystemManager::init(const char *mount_point, bool do_mount) {
    if (m_initialized) {
        ESP_LOGW(TAG, "Already initialized");
        return ESP_OK;
    }

    if (mount_point && strlen(mount_point) >= sizeof(m_mount_point)) {
        ESP_LOGE(TAG, "Mount point is too long");
        return ESP_ERR_INVALID_SIZE;
    }

    if (mount_point) {
        strncpy(m_mount_point, mount_point, sizeof(m_mount_point) - 1);
        m_mount_point[sizeof(m_mount_point) - 1] = '\0';
    }

    m_initialized = true;

    if (!do_mount) {
        ESP_LOGI(TAG, "External SD mount assumed at %s", m_mount_point);
        m_sd_mounted = true;  // Trust caller
        m_owns_mount = false;
        return ESP_OK;
    }

    esp_err_t ret = mount_sd();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "SD mount failed: %s - file transfer unavailable", esp_err_to_name(ret));
        /* Non-fatal: system continues, transfers will return ERR_FS_NOT_MOUNTED */
    }
    return ESP_OK;
}

esp_err_t FilesystemManager::mount_sd() {
    if (m_sd_mounted) return ESP_OK;

    esp_vfs_fat_sdmmc_mount_config_t mount_config = {
        .format_if_mount_failed = false,
        .max_files              = CONFIG_UART_FILEBRIDGE_SD_MAX_FILES,
        .allocation_unit_size   = 16 * 1024,
        .disk_status_check_enable = true,
        .use_one_fat            = false,
    };

    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    host.max_freq_khz = SDMMC_FREQ_HIGHSPEED;  /* 40 MHz */

#if FILEBRIDGE_P4_LDO
    /* ESP32-P4: power the SD slot via on-chip LDO before initializing SDMMC */
    sd_pwr_ctrl_ldo_config_t ldo_config = {
        .ldo_chan_id = CONFIG_UART_FILEBRIDGE_P4_LDO_CHAN,
    };
    sd_pwr_ctrl_handle_t pwr_ctrl = NULL;
    esp_err_t ret = sd_pwr_ctrl_new_on_chip_ldo(&ldo_config, &pwr_ctrl);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "ESP32-P4 SD LDO init failed: %s", esp_err_to_name(ret));
        return ret;
    }
    host.pwr_ctrl_handle = pwr_ctrl;
    m_sd_pwr_ctrl = pwr_ctrl;
#endif /* FILEBRIDGE_P4_LDO */

    sdmmc_slot_config_t slot_config = SDMMC_SLOT_CONFIG_DEFAULT();

    /* SD pin configuration is board-specific.
     * On ESP32-P4 (Waveshare ESP32-P4-WIFI6) the defaults match the hardware.
     * For other boards, override via Kconfig when those options are added,
     * or set manually in your application before calling init(). */
#if defined(CONFIG_IDF_TARGET_ESP32P4)
    slot_config.clk   = (gpio_num_t)43;
    slot_config.cmd   = (gpio_num_t)44;
    slot_config.d0    = (gpio_num_t)39;
    slot_config.d1    = (gpio_num_t)40;
    slot_config.d2    = (gpio_num_t)41;
    slot_config.d3    = (gpio_num_t)42;
    slot_config.width = 4;
    slot_config.flags |= SDMMC_SLOT_FLAG_INTERNAL_PULLUP;
#endif
    ret = esp_vfs_fat_sdmmc_mount(m_mount_point, &host,
                                            &slot_config, &mount_config, &m_sd_card);
    if (ret != ESP_OK) {
#if FILEBRIDGE_P4_LDO
        if (m_sd_pwr_ctrl) {
            sd_pwr_ctrl_del_on_chip_ldo((sd_pwr_ctrl_handle_t)m_sd_pwr_ctrl);
            m_sd_pwr_ctrl = nullptr;
        }
#endif
        ESP_LOGE(TAG, "SD mount failed: %s", esp_err_to_name(ret));
        return ret;
    }

    if (m_sd_card) {
        uint32_t freq_khz = m_sd_card->max_freq_khz;
        ESP_LOGI(TAG, "SD card mounted successfully");
        ESP_LOGI(TAG, "  Name: %s", m_sd_card->cid.name);
        ESP_LOGI(TAG, "  Frequency: %u kHz (%u MHz)", freq_khz, freq_khz / 1000);
        ESP_LOGI(TAG, "  Capacity: %llu MB",
                 ((uint64_t)m_sd_card->csd.capacity * m_sd_card->csd.sector_size) / (1024 * 1024));
    }

    m_sd_mounted = true;
    m_owns_mount = true;
    return ESP_OK;
}

void FilesystemManager::unmount_sd() {
    if (!m_sd_mounted) return;

    ESP_LOGI(TAG, "Unmounting SD card...");
    esp_vfs_fat_sdcard_unmount(m_mount_point, m_sd_card);
    m_sd_card = nullptr;

#if FILEBRIDGE_P4_LDO
    if (m_sd_pwr_ctrl) {
        sd_pwr_ctrl_del_on_chip_ldo((sd_pwr_ctrl_handle_t)m_sd_pwr_ctrl);
        m_sd_pwr_ctrl = nullptr;
    }
#endif

    m_sd_mounted = false;
}

esp_err_t FilesystemManager::get_space_info(const char *path,
                                             uint64_t *total_bytes,
                                             uint64_t *free_bytes) {
    if (!path || !total_bytes || !free_bytes) return ESP_ERR_INVALID_ARG;
    if (!m_sd_mounted)                        return ESP_ERR_INVALID_STATE;

    FATFS *fs;
    DWORD fre_clust;
    FRESULT res = f_getfree("0:", &fre_clust, &fs);
    if (res != FR_OK) {
        ESP_LOGE(TAG, "f_getfree failed: %d", res);
        return ESP_FAIL;
    }

    uint64_t tot_sect = (fs->n_fatent - 2) * fs->csize;
    uint64_t fre_sect = fre_clust * fs->csize;
    *total_bytes = tot_sect * fs->ssize;
    *free_bytes  = fre_sect * fs->ssize;
    return ESP_OK;
}

esp_err_t FilesystemManager::list_directory(const char *path,
                                             void (*callback)(const char*, uint64_t, bool, uint32_t, void*),
                                             void *user_data) {
    if (!callback || validate_path(path) != ESP_OK) return ESP_ERR_INVALID_ARG;

    DIR *dir = opendir(path);
    if (!dir) {
        ESP_LOGE(TAG, "opendir failed: %s", path);
        return ESP_ERR_NOT_FOUND;
    }

    struct dirent *entry;
    while ((entry = readdir(dir)) != nullptr) {
        char full_path[512];
        snprintf(full_path, sizeof(full_path), "%s/%s", path, entry->d_name);
        struct stat st;
        if (stat(full_path, &st) == 0) {
            callback(entry->d_name, (uint64_t)st.st_size,
                     S_ISDIR(st.st_mode), (uint32_t)st.st_mtime, user_data);
        }
    }

    closedir(dir);
    return ESP_OK;
}

esp_err_t FilesystemManager::stat_file(const char *path, uint64_t *size,
                                        uint32_t *timestamp, bool *is_dir) {
    if (validate_path(path) != ESP_OK) return ESP_ERR_INVALID_ARG;

    struct stat st;
    if (stat(path, &st) != 0) return ESP_ERR_NOT_FOUND;

    if (size)      *size      = (uint64_t)st.st_size;
    if (timestamp) *timestamp = (uint32_t)st.st_mtime;
    if (is_dir)    *is_dir    = S_ISDIR(st.st_mode);
    return ESP_OK;
}

esp_err_t FilesystemManager::delete_file(const char *path) {
    if (validate_path(path) != ESP_OK || strcmp(path, m_mount_point) == 0) return ESP_ERR_INVALID_ARG;

    struct stat st;
    if (stat(path, &st) != 0) return ESP_ERR_NOT_FOUND;

    if (S_ISDIR(st.st_mode)) {
        return delete_directory_recursive(path);
    }

    return (unlink(path) == 0) ? ESP_OK : ESP_FAIL;
}

esp_err_t FilesystemManager::delete_directory_recursive(const char *path) {
    DIR *dir = opendir(path);
    if (!dir) return ESP_ERR_NOT_FOUND;

    struct dirent *entry;
    esp_err_t result = ESP_OK;

    while ((entry = readdir(dir)) != nullptr) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) continue;

        char full_path[512];
        int len = snprintf(full_path, sizeof(full_path), "%s/%s", path, entry->d_name);
        if (len >= (int)sizeof(full_path)) {
            result = ESP_ERR_INVALID_SIZE;
            continue;
        }

        struct stat st;
        if (stat(full_path, &st) == 0) {
            esp_err_t ret = S_ISDIR(st.st_mode)
                ? delete_directory_recursive(full_path)
                : (unlink(full_path) == 0 ? ESP_OK : ESP_FAIL);
            if (ret != ESP_OK) result = ret;
        }
    }

    closedir(dir);
    if (rmdir(path) != 0) return ESP_FAIL;
    return result;
}

esp_err_t FilesystemManager::rename_file(const char *old_path, const char *new_path) {
    if (validate_path(old_path) != ESP_OK || validate_path(new_path) != ESP_OK) return ESP_ERR_INVALID_ARG;
    if (strcmp(old_path, m_mount_point) == 0 || strcmp(new_path, m_mount_point) == 0) return ESP_ERR_INVALID_ARG;
    return (rename(old_path, new_path) == 0) ? ESP_OK : ESP_FAIL;
}

esp_err_t FilesystemManager::create_directory(const char *path) {
    if (validate_path(path) != ESP_OK || strcmp(path, m_mount_point) == 0) return ESP_ERR_INVALID_ARG;
    return (mkdir(path, 0755) == 0) ? ESP_OK : ESP_FAIL;
}

esp_err_t FilesystemManager::copy_file(const char *src_path, const char *dst_path) {
    if (validate_path(src_path) != ESP_OK || validate_path(dst_path) != ESP_OK) return ESP_ERR_INVALID_ARG;
    if (strcmp(src_path, m_mount_point) == 0 || strcmp(dst_path, m_mount_point) == 0) return ESP_ERR_INVALID_ARG;

    FILE *src = fopen(src_path, "rb");
    if (!src) return ESP_ERR_NOT_FOUND;

    FILE *dst = fopen(dst_path, "wb");
    if (!dst) { fclose(src); return ESP_FAIL; }

    uint8_t buf[4096];
    size_t n;
    esp_err_t ret = ESP_OK;

    while ((n = fread(buf, 1, sizeof(buf), src)) > 0) {
        if (fwrite(buf, 1, n, dst) != n) {
            ret = ESP_FAIL;
            break;
        }
    }

    fclose(src);
    fclose(dst);
    if (ret != ESP_OK) unlink(dst_path);
    return ret;
}

esp_err_t FilesystemManager::hash_file(const char *path, uint32_t *hash) {
    if (validate_path(path) != ESP_OK || !hash) return ESP_ERR_INVALID_ARG;

    FILE *f = fopen(path, "rb");
    if (!f) return ESP_ERR_NOT_FOUND;

    uint32_t crc = 0xFFFFFFFF;
    uint8_t  buf[4096];
    size_t   n;

    while ((n = fread(buf, 1, sizeof(buf), f)) > 0) {
        for (size_t i = 0; i < n; i++) {
            crc ^= buf[i];
            for (int j = 0; j < 8; j++) {
                crc = (crc >> 1) ^ (0xEDB88320 & -(crc & 1));
            }
        }
    }

    fclose(f);
    *hash = ~crc;
    return ESP_OK;
}

esp_err_t FilesystemManager::format_sd() {
    if (!m_sd_card || !m_sd_mounted) {
        ESP_LOGE(TAG, "No SD card available to format");
        return ESP_ERR_INVALID_STATE;
    }

    ESP_LOGW(TAG, "Formatting SD card at %s ...", m_mount_point);
    esp_err_t ret = esp_vfs_fat_sdcard_format(m_mount_point, m_sd_card);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Format failed: %s", esp_err_to_name(ret));
        mount_sd();  /* Attempt remount to recover */
    } else {
        ESP_LOGI(TAG, "SD card formatted successfully");
    }
    return ret;
}

bool FilesystemManager::is_sd_path(const char *path) {
    const size_t mount_length = strlen(m_mount_point);
    return path && (strcmp(path, m_mount_point) == 0 ||
                    (strncmp(path, m_mount_point, mount_length) == 0 &&
                     path[mount_length] == '/'));
}

esp_err_t FilesystemManager::validate_path(const char *path) {
    if (!path || strlen(path) == 0 || path[0] != '/') return ESP_ERR_INVALID_ARG;
    if (!is_sd_path(path))         return ESP_ERR_INVALID_ARG;
    const char *segment = path;
    while ((segment = strstr(segment, "..")) != nullptr) {
        const char before = segment == path ? '/' : segment[-1];
        const char after = segment[2];
        if ((before == '/' || before == '\\') && (after == '/' || after == '\\' || after == '\0')) {
            return ESP_ERR_INVALID_ARG;
        }
        segment += 2;
    }
    return ESP_OK;
}

