import os
import sys
import unittest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
):
    sys.path.insert(0, _p)

from sparkline import render_sparkline

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def readings(values):
    return [{"date": f"2026-{i + 1:02d}-01", "value": v} for i, v in enumerate(values)]


class TestRenderSparkline(unittest.TestCase):
    def test_returns_valid_png_for_multi_point_series(self):
        png = render_sparkline(readings([100, 102, 101, 105, 108]))

        self.assertTrue(png.startswith(PNG_MAGIC))

    def test_handles_single_point_history(self):
        png = render_sparkline(readings([4.1]))

        self.assertTrue(png.startswith(PNG_MAGIC))

    def test_handles_flat_series(self):
        png = render_sparkline(readings([3.63, 3.63, 3.63]))

        self.assertTrue(png.startswith(PNG_MAGIC))

    def test_different_series_produce_different_images(self):
        up = render_sparkline(readings([1, 2, 3, 4, 5]))
        down = render_sparkline(readings([5, 4, 3, 2, 1]))

        self.assertNotEqual(up, down)


if __name__ == "__main__":
    unittest.main()
