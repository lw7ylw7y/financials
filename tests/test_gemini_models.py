import os
import sys
import unittest
from unittest.mock import patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

from gemini_models import DEFAULT_FALLBACK_MODELS, fallback_models


class TestFallbackModels(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_defaults_when_unset(self):
        self.assertEqual(fallback_models(), list(DEFAULT_FALLBACK_MODELS))

    @patch.dict(os.environ, {"GEMINI_FALLBACK_MODELS": " a , b,,c "}, clear=True)
    def test_parses_a_comma_separated_override(self):
        self.assertEqual(fallback_models(), ["a", "b", "c"])

    @patch.dict(os.environ, {"GEMINI_FALLBACK_MODELS": " , "}, clear=True)
    def test_blank_override_falls_back_to_defaults(self):
        self.assertEqual(fallback_models(), list(DEFAULT_FALLBACK_MODELS))


if __name__ == "__main__":
    unittest.main()
