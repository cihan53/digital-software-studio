"""Reddedilen yazma isteği işlenmemeli (issue #192)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_web as W


class Sahte:
    def __init__(self, headers):
        self.headers, self.cevaplar = headers, []

    def _json(self, obj, code=200):
        self.cevaplar.append(code)



class YazmaGuvenligi(unittest.TestCase):
    def _handler_sinifi(self):
        for ad in dir(W):
            o = getattr(W, ad)
            if isinstance(o, type) and hasattr(o, "_yazma_guvenligi"):
                return o
        self.fail("handler sınıfı yok")

    def test_ret_edilen_istek_true_dondurur(self):
        H = self._handler_sinifi()
        s = Sahte({"Origin": "http://evil.example", "Host": "127.0.0.1:8090", "Content-Type": "application/json"})
        self.assertTrue(H._yazma_guvenligi(s))                       # çağıran işlemeyi bırakır
        self.assertEqual(s.cevaplar, [403])
        s = Sahte({"Host": "127.0.0.1:8090", "Content-Type": "text/plain"})
        self.assertTrue(H._yazma_guvenligi(s))
        self.assertEqual(s.cevaplar, [400])

    def test_gecerli_istek_none_dondurur(self):
        H = self._handler_sinifi()
        s = Sahte({"Origin": "http://127.0.0.1:8090", "Host": "127.0.0.1:8090", "Content-Type": "application/json"})
        self.assertFalse(H._yazma_guvenligi(s))
        self.assertEqual(s.cevaplar, [])


if __name__ == "__main__":
    unittest.main()
