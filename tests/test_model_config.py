"""Model-specific request parameters loaded from local INI files."""
import unittest
from unittest.mock import mock_open, patch

from atestservice.llm.models import default_llm_models


class ModelConfigTests(unittest.TestCase):
    def load(self, text):
        with patch("builtins.open", mock_open(read_data=text)):
            return default_llm_models("models.ini")

    def test_extra_body_preserves_false_and_nested_values_per_model(self):
        models = self.load(
            '[qwen]\nextra_body = {"enable_thinking": false}\n'
            '[local]\nextra_body = {"chat_template_kwargs": {"enable_thinking": false}}\n'
            '[other]\nmodel = other\n'
        )
        self.assertEqual(models["qwen"].extra_body, {"enable_thinking": False})
        self.assertEqual(models["local"].extra_body, {"chat_template_kwargs": {"enable_thinking": False}})
        self.assertEqual(models["other"].extra_body, {})

    def test_invalid_json_identifies_model_without_echoing_configuration(self):
        with self.assertRaisesRegex(ValueError, "模型 qwen 的 extra_body") as raised:
            self.load('[qwen]\nextra_body = {"private": "SECRET", "enable_thinking": False}\n')
        self.assertNotIn("SECRET", str(raised.exception))

    def test_extra_body_requires_an_object(self):
        for value in ('[]', 'null', 'false', '"text"', '42'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "JSON 对象"):
                self.load(f'[qwen]\nextra_body = {value}\n')
