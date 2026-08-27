#!/usr/bin/env python3
"""
Comprehensive test suite for esp-uart-filebridge.

Tests all functionality end-to-end:
- Basic connection and device info
- File operations (upload, download, delete)
- Directory operations (mkdir, list, delete)
- Streaming operations
- CRC32 verification
- Edge cases and error handling
- WebDAV functionality (if available)

Usage:
    python test_all.py --port COM13
    python test_all.py --port COM13 --test-webdav
"""

import sys
import os
import argparse
import tempfile
import time
import binascii
from pathlib import Path

# Add parent to path for local testing
sys.path.insert(0, str(Path(__file__).parent))

from esp_uart_filebridge.protocol import ESP32Protocol, ESP32ProtocolError
from esp_uart_filebridge.file_manager import ESP32FileManager

# Test configuration
TEST_DIR = "/sd/test_filebridge"
TEST_FILES = {
    "small.txt": b"Hello ESP32!",
    "medium.bin": b"\xAA" * 1024,  # 1 KB
    "large.bin": b"\x55" * (100 * 1024),  # 100 KB
    "unicode.txt": "Test UTF-8: äöü 中文 🚀".encode('utf-8')
}

class Colors:
    """ANSI color codes for terminal output."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def log_test(name):
    """Print test name."""
    print(f"\n{Colors.CYAN}{'='*70}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.BLUE}TEST: {name}{Colors.ENDC}")
    print(f"{Colors.CYAN}{'='*70}{Colors.ENDC}")

def log_pass(msg):
    """Print success message."""
    print(f"{Colors.GREEN}[PASS]{Colors.ENDC} {msg}")

def log_fail(msg):
    """Print failure message."""
    print(f"{Colors.RED}[FAIL]{Colors.ENDC} {msg}")

def log_info(msg):
    """Print info message."""
    print(f"{Colors.CYAN}[INFO]{Colors.ENDC} {msg}")

def log_warn(msg):
    """Print warning message."""
    print(f"{Colors.YELLOW}[WARN]{Colors.ENDC} {msg}")


class LiveTestRunner:
    def __init__(self, port, baud=3000000):
        self.port = port
        self.baud = baud
        self.proto = None
        self.manager = None
        self.passed = 0
        self.failed = 0
        self.skipped = 0
    
    def setup(self):
        """Connect to ESP32."""
        log_test("Setup - Connect to ESP32")
        try:
            self.proto = ESP32Protocol()
            self.proto.connect(self.port, self.baud)
            self.manager = ESP32FileManager(self.proto)
            log_pass(f"Connected to {self.port} @ {self.baud:,} baud")
            return True
        except Exception as e:
            log_fail(f"Connection failed: {e}")
            return False
    
    def teardown(self):
        """Disconnect and cleanup."""
        log_test("Teardown - Cleanup")
        
        # Try to cleanup test directory
        try:
            log_info(f"Cleaning up test directory: {TEST_DIR}")
            self.proto.delete_file(TEST_DIR)
            log_pass("Test directory deleted")
        except Exception as e:
            log_warn(f"Cleanup failed (might not exist): {e}")
        
        if self.proto:
            self.proto.disconnect()
            log_pass("Disconnected")
    
    def test_device_info(self):
        """Test getting device information."""
        log_test("Device Info")
        try:
            info = self.manager.get_device_info()
            
            log_info(f"Device: {info.device_name}")
            log_info(f"Firmware: {info.fw_version}")
            log_info(f"SD Present: {info.sd_present}")
            
            if info.sd_present:
                sd_size_mb = info.sd_size / (1024 * 1024) if hasattr(info, 'sd_size') else 0
                sd_free_mb = info.sd_free / (1024 * 1024) if hasattr(info, 'sd_free') else 0
                log_info(f"SD Size: {sd_size_mb:.0f} MB (Free: {sd_free_mb:.0f} MB)")
            
            log_info(f"Max Payload: {info.max_payload_size:,} bytes")
            log_info(f"Chunk Size: {info.optimal_chunk_size:,} bytes")
            
            if not info.sd_present:
                log_fail("SD card not detected!")
                self.failed += 1
                return False
            
            log_pass("Device info retrieved")
            self.passed += 1
            return True
        
        except Exception as e:
            log_fail(f"Failed: {e}")
            self.failed += 1
            return False
    
    def test_mkdir(self):
        """Test directory creation."""
        log_test("Create Directory (mkdir)")
        try:
            # Create main test directory
            log_info(f"Creating directory: {TEST_DIR}")
            self.manager.create_directory(TEST_DIR)
            log_pass(f"Created: {TEST_DIR}")
            
            # Create subdirectory
            subdir = f"{TEST_DIR}/subdir"
            log_info(f"Creating subdirectory: {subdir}")
            self.manager.create_directory(subdir)
            log_pass(f"Created: {subdir}")
            
            # Create nested directory
            nested = f"{TEST_DIR}/subdir/nested"
            log_info(f"Creating nested directory: {nested}")
            self.manager.create_directory(nested)
            log_pass(f"Created: {nested}")
            
            self.passed += 1
            return True
        
        except Exception as e:
            log_fail(f"Failed: {e}")
            self.failed += 1
            return False
    
    def test_list_directory(self):
        """Test directory listing."""
        log_test("List Directory (ls)")
        try:
            # List test directory
            log_info(f"Listing: {TEST_DIR}")
            entries = self.manager.list_directory(TEST_DIR)
            
            log_info(f"Found {len(entries)} entries")
            for entry in entries:
                name = entry.name if hasattr(entry, 'name') else entry.get('name', '?')
                is_dir = entry.is_directory if hasattr(entry, 'is_directory') else entry.get('is_dir', False)
                
                if is_dir:
                    log_info(f"  [DIR]  {name}")
                else:
                    size = entry.size if hasattr(entry, 'size') else entry.get('size', 0)
                    log_info(f"  [FILE] {name} ({size:,} bytes)")
            
            # Check if subdirectory exists
            found_subdir = any(
                ((e.name if hasattr(e, 'name') else e.get('name')) == 'subdir' and
                 (e.is_directory if hasattr(e, 'is_directory') else e.get('is_dir')))
                for e in entries
            )
            if not found_subdir:
                log_fail("Subdirectory not found in listing!")
                self.failed += 1
                return False
            
            log_pass("Directory listing works")
            self.passed += 1
            return True
        
        except Exception as e:
            log_fail(f"Failed: {e}")
            self.failed += 1
            return False
    
    def test_file_upload(self):
        """Test file upload (all sizes)."""
        log_test("File Upload")
        
        success = True
        for filename, content in TEST_FILES.items():
            try:
                remote_path = f"{TEST_DIR}/{filename}"
                log_info(f"Uploading {filename} ({len(content):,} bytes)...")
                
                # Upload via bytes
                start = time.time()
                self.manager.upload_file_from_bytes(content, remote_path)
                elapsed = time.time() - start
                
                speed_kbps = (len(content) / 1024) / elapsed if elapsed > 0 else 0
                log_pass(f"Uploaded {filename} in {elapsed:.2f}s ({speed_kbps:.0f} KB/s)")
            
            except Exception as e:
                log_fail(f"Upload {filename} failed: {e}")
                success = False
        
        if success:
            self.passed += 1
        else:
            self.failed += 1
        
        return success
    
    def test_file_download(self):
        """Test file download and verify content."""
        log_test("File Download & Verification")
        
        success = True
        for filename, expected_content in TEST_FILES.items():
            try:
                remote_path = f"{TEST_DIR}/{filename}"
                log_info(f"Downloading {filename}...")
                
                # Download
                start = time.time()
                downloaded = self.manager.download_file_to_bytes(remote_path)
                elapsed = time.time() - start
                
                speed_kbps = (len(downloaded) / 1024) / elapsed if elapsed > 0 else 0
                
                # Verify content
                if downloaded == expected_content:
                    log_pass(f"Downloaded & verified {filename} ({speed_kbps:.0f} KB/s)")
                else:
                    log_fail(f"Content mismatch for {filename}!")
                    log_info(f"  Expected: {len(expected_content)} bytes")
                    log_info(f"  Got: {len(downloaded)} bytes")
                    success = False
            
            except Exception as e:
                log_fail(f"Download {filename} failed: {e}")
                success = False
        
        if success:
            self.passed += 1
        else:
            self.failed += 1
        
        return success
    
    def test_file_hash(self):
        """Test CRC32 hash calculation."""
        log_test("File Hash (CRC32)")
        
        try:
            filename = "medium.bin"
            remote_path = f"{TEST_DIR}/{filename}"
            expected_content = TEST_FILES[filename]
            
            log_info(f"Calculating CRC32 for {filename}...")
            
            # Get remote CRC32
            remote_crc = self.manager.get_file_hash(remote_path)
            
            # Calculate local CRC32
            local_crc = binascii.crc32(expected_content) & 0xFFFFFFFF
            
            log_info(f"  Remote CRC32: 0x{remote_crc:08X}")
            log_info(f"  Local CRC32:  0x{local_crc:08X}")
            
            if remote_crc == local_crc:
                log_pass("CRC32 verification passed")
                self.passed += 1
                return True
            else:
                log_fail("CRC32 mismatch!")
                self.failed += 1
                return False
        
        except Exception as e:
            log_fail(f"Failed: {e}")
            self.failed += 1
            return False
    
    def test_file_delete(self):
        """Test file deletion."""
        log_test("File Delete")
        
        try:
            filename = "small.txt"
            remote_path = f"{TEST_DIR}/{filename}"
            
            log_info(f"Deleting {filename}...")
            self.manager.delete_file(remote_path)
            log_pass(f"Deleted {filename}")
            
            # Verify it's gone
            entries = self.manager.list_directory(TEST_DIR)
            found = any(
                (e.name if hasattr(e, 'name') else e.get('name')) == filename
                for e in entries
            )
            
            if found:
                log_fail(f"{filename} still exists after delete!")
                self.failed += 1
                return False
            
            log_pass("File deletion verified")
            self.passed += 1
            return True
        
        except Exception as e:
            log_fail(f"Failed: {e}")
            self.failed += 1
            return False
    
    def test_directory_delete(self):
        """Test directory deletion."""
        log_test("Directory Delete")
        
        try:
            # Delete nested directory (should be empty)
            nested = f"{TEST_DIR}/subdir/nested"
            log_info(f"Deleting empty directory: {nested}")
            self.manager.delete_file(nested)
            log_pass(f"Deleted: {nested}")
            
            # Try to delete non-empty directory (should fail or work recursively)
            log_info(f"Deleting directory: {TEST_DIR}/subdir")
            try:
                self.manager.delete_file(f"{TEST_DIR}/subdir")
                log_pass("Directory deleted")
            except Exception as e:
                log_warn(f"Non-empty directory delete failed (expected): {e}")
            
            self.passed += 1
            return True
        
        except Exception as e:
            log_fail(f"Failed: {e}")
            self.failed += 1
            return False
    
    def test_streaming_upload(self):
        """Test large file streaming upload."""
        log_test("Streaming Upload (Large File)")
        
        try:
            # Create temporary large file
            size_mb = 1
            log_info(f"Creating {size_mb} MB test file...")
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
                f.write(b'\xCC' * (size_mb * 1024 * 1024))
                temp_file = f.name
            
            try:
                remote_path = f"{TEST_DIR}/stream_test.bin"
                log_info(f"Uploading {size_mb} MB via streaming...")
                
                start = time.time()
                self.manager.upload_file(temp_file, remote_path)
                elapsed = time.time() - start
                
                speed_kbps = (size_mb * 1024) / elapsed if elapsed > 0 else 0
                log_pass(f"Streamed {size_mb} MB in {elapsed:.2f}s ({speed_kbps:.0f} KB/s)")
                
                self.passed += 1
                return True
            
            finally:
                os.unlink(temp_file)
        
        except Exception as e:
            log_fail(f"Failed: {e}")
            self.failed += 1
            return False
    
    def test_speed_benchmark(self):
        """Test pure UART speed via /dev/null."""
        log_test("Speed Benchmark (/dev/null)")
        
        try:
            size_mb = 2
            log_info(f"Creating {size_mb} MB test data...")
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
                f.write(b'\xAA' * (size_mb * 1024 * 1024))
                temp_file = f.name
            
            try:
                log_info(f"Uploading to /dev/null (no SD write)...")
                
                start = time.time()
                self.manager.upload_file(temp_file, "/dev/null")
                elapsed = time.time() - start
                
                speed_kbps = (size_mb * 1024) / elapsed if elapsed > 0 else 0
                log_pass(f"Pure UART speed: {speed_kbps:.0f} KB/s ({elapsed:.2f}s for {size_mb} MB)")
                
                self.passed += 1
                return True
            
            finally:
                os.unlink(temp_file)
        
        except Exception as e:
            log_fail(f"Failed: {e}")
            self.failed += 1
            return False
    
    def test_noise_recovery(self):
        """Test UART noise tolerance and recovery."""
        log_test("Noise Recovery")
        try:
            log_info("Injecting random noise into UART TX buffer...")
            self.manager.proto.ser.write(b'\x00\xFF\x55\xAA' * 10)
            
            # Immediately try to upload a file (parser should discard noise and sync)
            test_data = b"Noise recovery test data"
            remote_path = f"{TEST_DIR}/noise_test.txt"
            self.manager.upload_file_from_bytes(test_data, remote_path)
            
            # Verify
            downloaded = self.manager.download_file_to_bytes(remote_path)
            if downloaded == test_data:
                log_pass("Recovered from noise and transferred successfully")
                self.passed += 1
                return True
            else:
                log_fail("Data corrupted after noise injection")
                self.failed += 1
                return False
        except Exception as e:
            log_fail(f"Failed to recover from noise: {e}")
            self.failed += 1
            return False

    def test_stress_upload(self):
        """Test uploading a file repeatedly without resetting."""
        log_test("Stress Upload (10 Iterations)")
        try:
            test_data = b"Stress test chunk " * 1024  # ~18KB
            success_count = 0
            for i in range(10):
                remote_path = f"{TEST_DIR}/stress_test_{i}.bin"
                try:
                    self.manager.upload_file_from_bytes(test_data, remote_path)
                    success_count += 1
                except Exception as e:
                    log_warn(f"Iteration {i} failed: {e}")
            
            if success_count == 10:
                log_pass("All 10 stress uploads successful")
                self.passed += 1
                return True
            else:
                log_fail(f"Only {success_count}/10 stress uploads succeeded")
                self.failed += 1
                return False
        except Exception as e:
            log_fail(f"Stress test crashed: {e}")
            self.failed += 1
            return False

    def test_webdav(self):
        """Test WebDAV functionality (if available)."""
        log_test("WebDAV Module")
        
        try:
            from esp_uart_filebridge.webdav import is_available
            
            if is_available():
                log_pass("WebDAV dependencies installed")
                log_info("WebDAV server test requires manual verification")
                log_info("Run: esp-file-bridge --port COM13 webdav")
                self.passed += 1
                return True
            else:
                log_warn("WebDAV dependencies not installed")
                log_info("Install with: pip install esp-uart-filebridge[webdav]")
                self.skipped += 1
                return False
        
        except ImportError:
            log_warn("WebDAV module not available")
            self.skipped += 1
            return False
    
    def run_all_tests(self, test_webdav=False):
        """Run all tests."""
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}")
        print(f"ESP-UART-FILEBRIDGE - COMPREHENSIVE TEST SUITE")
        print(f"{'='*70}{Colors.ENDC}\n")
        
        if not self.setup():
            log_fail("Setup failed - cannot run tests")
            return False
        
        try:
            # Core functionality tests
            self.test_device_info()
            self.test_mkdir()
            self.test_list_directory()
            self.test_file_upload()
            self.test_file_download()
            self.test_file_hash()
            self.test_file_delete()
            self.test_directory_delete()
            self.test_streaming_upload()
            self.test_speed_benchmark()
            self.test_noise_recovery()
            self.test_stress_upload()
            
            # Optional WebDAV test
            if test_webdav:
                self.test_webdav()
        
        finally:
            self.teardown()
        
        # Print summary
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*70}")
        print(f"TEST SUMMARY")
        print(f"{'='*70}{Colors.ENDC}\n")
        
        total = self.passed + self.failed + self.skipped
        print(f"{Colors.GREEN}[PASS] Passed: {self.passed}/{total}{Colors.ENDC}")
        if self.failed > 0:
            print(f"{Colors.RED}[FAIL] Failed: {self.failed}/{total}{Colors.ENDC}")
        if self.skipped > 0:
            print(f"{Colors.YELLOW}[SKIP] Skipped: {self.skipped}/{total}{Colors.ENDC}")
        
        print()
        
        if self.failed == 0:
            print(f"{Colors.GREEN}{Colors.BOLD}[PASS] ALL TESTS PASSED!{Colors.ENDC}\n")
            return True
        else:
            print(f"{Colors.RED}{Colors.BOLD}[FAIL] SOME TESTS FAILED!{Colors.ENDC}\n")
            return False


def main():
    parser = argparse.ArgumentParser(description="Comprehensive test suite for esp-uart-filebridge")
    parser.add_argument("--port", "-p", required=True, help="Serial port (e.g., COM13, /dev/ttyUSB0)")
    parser.add_argument("--baud", "-b", type=int, default=3000000, help="Baud rate (default: 3000000)")
    parser.add_argument("--test-webdav", action="store_true", help="Test WebDAV functionality")
    
    args = parser.parse_args()
    
    runner = LiveTestRunner(args.port, args.baud)
    success = runner.run_all_tests(test_webdav=args.test_webdav)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()


