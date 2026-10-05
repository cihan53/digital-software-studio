"""Canlı ortam kontrolü IPv6 loopback'i de görmeli (issue #198)."""
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_board as B


class LiveIPv6(unittest.TestCase):
    def test_ipv4_ve_ipv6_dinleyici(self):
        for fam, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            s = socket.socket(fam)
            try:
                s.bind((host, 0))
            except OSError:
                s.close()
                continue                                                    # ortamda IPv6 yoksa atla
            s.listen(1)
            port = s.getsockname()[1]
            eski = B.live_ports
            B.live_ports = lambda p=port: (p,)
            try:
                self.assertEqual(B.live_status(), {port: True}, host)
            finally:
                B.live_ports = eski
                s.close()


if __name__ == "__main__":
    unittest.main()
