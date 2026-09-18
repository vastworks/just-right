"""Pure arithmetic tests for the ratio menu."""

import unittest

from sizer_ratios import RATIOS, largest_fitting_size, sizes_for_ratio


class RatioTests(unittest.TestCase):
    def test_requested_ratios_include_three_to_two(self):
        self.assertIn((3, 2), RATIOS)
        self.assertIn((1500, 1000), sizes_for_ratio(3, 2, 1920, 1200))

    def test_largest_fitting_size_never_overflows(self):
        width, height = largest_fitting_size(16, 9, 1920, 1040)
        self.assertLessEqual(width, 1920)
        self.assertLessEqual(height, 1040)
        self.assertEqual(width * 9, height * 16 + 1)


if __name__ == "__main__":
    unittest.main()
