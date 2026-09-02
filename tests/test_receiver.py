from __future__ import annotations

import unittest

from fluorosuite.capture.receiver import _FrameRateEstimator, _StreamAssembler
from fluorosuite.config import GVCP_CONTROL_PORT


class _ProcessorSpy:
    def __init__(self) -> None:
        self.submissions: list[dict[int, bytes]] = []

    def submit(self, payloads: dict[int, bytes]) -> None:
        self.submissions.append(payloads)


def udp_packet(
    source_port: int,
    destination_port: int,
    packet_format: int = 3,
    packet_id: int = 1,
    payload: bytes = b"pixels",
) -> bytes:
    packet = bytearray(50)
    packet[12:14] = b"\x08\x00"
    packet[14] = 0x45
    packet[23] = 17
    packet[34:36] = source_port.to_bytes(2, "big")
    packet[36:38] = destination_port.to_bytes(2, "big")
    packet[44:46] = (7).to_bytes(2, "big")
    packet[46] = packet_format
    packet[47:50] = packet_id.to_bytes(3, "big")
    return bytes(packet) + payload


class StreamAssemblerTests(unittest.TestCase):
    def test_ignores_gvcp_in_both_directions(self) -> None:
        processor = _ProcessorSpy()
        assembler = _StreamAssembler(processor)

        assembler.feed(udp_packet(GVCP_CONTROL_PORT, 5000))
        assembler.feed(udp_packet(5000, GVCP_CONTROL_PORT))

        self.assertIsNone(assembler.current_block)
        self.assertEqual(assembler.payloads, {})
        self.assertEqual(processor.submissions, [])

    def test_duplicate_gvsp_packet_id_is_not_appended_twice(self) -> None:
        processor = _ProcessorSpy()
        assembler = _StreamAssembler(processor)

        assembler.feed(udp_packet(5000, 5001, payload=b"first"))
        assembler.feed(udp_packet(5000, 5001, payload=b"replacement"))
        assembler.feed(udp_packet(5000, 5001, packet_format=2, payload=b""))

        self.assertEqual(processor.submissions, [{1: b"replacement"}])


class FrameRateEstimatorTests(unittest.TestCase):
    def test_smooths_half_second_frame_count_quantization(self) -> None:
        estimator = _FrameRateEstimator(window=3.0, warmup=1.5)

        self.assertIsNone(estimator.sample(0.0, 0))
        self.assertIsNone(estimator.sample(0.5, 16))
        self.assertIsNone(estimator.sample(1.0, 30))
        self.assertEqual(estimator.sample(1.5, 45), 30.0)
        self.assertEqual(estimator.sample(2.0, 60), 30.0)


if __name__ == "__main__":
    unittest.main()