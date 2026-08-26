import binascii
import struct

import pytest

from esp_uart_filebridge.protocol import (
    CMD_ACK,
    CMD_GET_FILE_DATA,
    CMD_GET_FILE_END,
    ESP32Protocol,
    ESP32ProtocolError,
    PROTO_MAGIC_0,
    PROTO_MAGIC_1,
)


class DummySerial:
    def __init__(self, frame: bytes):
        self._frame = frame
        self._pos = 0
        self.timeout = 0.1
        self._is_open = True

    def read(self, size: int = 1):
        if self._pos >= len(self._frame):
            return b""
        chunk = self._frame[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    @property
    def is_open(self):
        return self._is_open

    def write(self, data):
        return len(data)

    def flush(self):
        pass

    @property
    def in_waiting(self):
        return 0


def build_frame(cmd: int, payload: bytes = b"", seq: int = 0):
    header = struct.pack("<BBBBBHH", PROTO_MAGIC_0, PROTO_MAGIC_1, 0x10, cmd, 0, seq, len(payload))
    crc = binascii.crc32(header + payload) & 0xFFFFFFFF
    return header + payload + struct.pack("<I", crc)


def test_receive_frame_tracks_initial_sequence_and_rejects_later_mismatch():
    proto = ESP32Protocol()
    proto.ser = DummySerial(build_frame(CMD_ACK, b"", seq=136))
    proto._rx_sequence = None
    assert proto._receive_frame(timeout_sec=0.2)[0] == CMD_ACK

    proto.ser = DummySerial(build_frame(CMD_ACK, b"", seq=138))
    with pytest.raises(ESP32ProtocolError, match="Sequence mismatch"):
        proto._receive_frame(timeout_sec=0.2)


def test_receive_frame_rejects_duplicate_sequence():
    proto = ESP32Protocol()
    proto.ser = DummySerial(build_frame(CMD_ACK, b"", seq=7))
    proto._rx_sequence = None
    assert proto._receive_frame(timeout_sec=0.2)[0] == CMD_ACK

    proto.ser = DummySerial(build_frame(CMD_ACK, b"", seq=7))
    with pytest.raises(ESP32ProtocolError, match="Sequence mismatch"):
        proto._receive_frame(timeout_sec=0.2)


def test_receive_frame_rejects_truncated_header():
    proto = ESP32Protocol()
    proto.ser = DummySerial(b'\xF1\x1E\x10\x10\x00')
    proto._rx_sequence = None

    with pytest.raises(ESP32ProtocolError, match="Header timeout"):
        proto._receive_frame(timeout_sec=0.2)


def test_disconnect_resets_expected_sequence_state():
    proto = ESP32Protocol()
    proto._rx_sequence = 42

    proto.disconnect()

    assert proto._rx_sequence is None


def test_read_file_rejects_download_size_mismatch():
    expected_size = 6
    proto = ESP32Protocol()
    proto.ser = DummySerial(
        build_frame(CMD_ACK, struct.pack('<Q', expected_size), seq=0)
        + build_frame(CMD_GET_FILE_DATA, b'abc', seq=1)
        + build_frame(CMD_GET_FILE_END, b'', seq=2)
    )
    proto._rx_sequence = 0

    with pytest.raises(ESP32ProtocolError, match="size"):
        proto.read_file('/sd/test.bin')
