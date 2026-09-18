"""Unit tests for config/model helpers that do not need a KDE session."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sizer_engine


class SizerEngineTests(unittest.TestCase):
    def test_legacy_preset_defaults_to_outer_mode(self):
        preset = sizer_engine._with_identifier({"name": "Old", "width": 800, "height": 600})
        self.assertEqual(preset["sizeMode"], "outer")
        self.assertTrue(preset["identifier"])

    def test_invalid_size_mode_falls_back_to_outer(self):
        preset = sizer_engine._with_identifier(
            {"name": "Bad", "width": 800, "height": 600, "sizeMode": "anything"}
        )
        self.assertEqual(preset["sizeMode"], "outer")

    def test_custom_ratios_are_reduced_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            ratios_path = Path(temporary_directory) / "custom-ratios.json"
            with patch.object(sizer_engine, "CONFIG_DIRECTORY", Path(temporary_directory)), \
                 patch.object(sizer_engine, "CUSTOM_RATIOS_PATH", ratios_path):
                self.assertEqual(sizer_engine.add_custom_ratio(64, 18), [(32, 9)])
                self.assertEqual(sizer_engine.add_custom_ratio(32, 9), [(32, 9)])
                self.assertEqual(sizer_engine.load_custom_ratios(), [(32, 9)])

    def test_developer_templates_are_normal_presets(self):
        templates = sizer_engine.developer_preset_templates()
        self.assertEqual([item["width"] for item in templates], [640, 854, 1280, 1600, 1920])
        self.assertTrue(all(item["category"] == "Developer sizes" for item in templates))
        self.assertTrue(all(item["position"] == "center" for item in templates))

    def test_preset_aspect_ratio_is_derived(self):
        self.assertEqual(
            sizer_engine.preset_aspect_ratio({"width": 1280, "height": 720}),
            (16, 9),
        )

    def test_generated_script_contains_client_and_fit_actions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "window-sizer.js"
            with patch.object(sizer_engine, "CONFIG_DIRECTORY", Path(temporary_directory)), \
                 patch.object(sizer_engine, "GENERATED_SCRIPT_PATH", output):
                path = sizer_engine.generate_script([
                    {"name": "Client", "width": 1280, "height": 720,
                     "sizeMode": "client", "identifier": "client"}
                ])
            source = path.read_text(encoding="utf-8")
        self.assertIn('"sizeMode": "client"', source)
        self.assertIn('"aspectRatio": [16, 9]', source)
        self.assertIn("win.clientGeometry", source)
        self.assertIn("WindowSizer_FitRatio_", source)


if __name__ == "__main__":
    unittest.main()
