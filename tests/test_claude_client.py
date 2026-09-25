import os
import sys
import unittest
from unittest.mock import Mock, patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

import requests
from pydantic import BaseModel

from claude_client import ClaudeApiError, generate_json


class Schema(BaseModel):
    answer: str


def ok_response(text):
    return Mock(json=lambda: {"content": [{"type": "text", "text": text}]})


class TestGenerateJson(unittest.TestCase):
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key"}, clear=True)
    @patch("claude_client._session.post")
    def test_returns_json_and_sends_schema_key_and_prompt(self, mock_post):
        mock_post.return_value = ok_response('{"answer": "hi"}')

        result = generate_json("sys", "user", Schema)

        self.assertEqual(result, '{"answer": "hi"}')
        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["x-api-key"], "key")
        self.assertIn("answer", kwargs["json"]["system"])
        self.assertEqual(kwargs["json"]["messages"], [{"role": "user", "content": "user"}])

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key", "CLAUDE_FALLBACK_MODEL": "claude-x"}, clear=True)
    @patch("claude_client._session.post")
    def test_model_is_overridable(self, mock_post):
        mock_post.return_value = ok_response("{}")
        generate_json("sys", "user", Schema)
        self.assertEqual(mock_post.call_args.kwargs["json"]["model"], "claude-x")

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key"}, clear=True)
    @patch("claude_client._session.post")
    def test_strips_code_fence_around_json(self, mock_post):
        mock_post.return_value = ok_response('```json\n{"answer": "hi"}\n```')
        self.assertEqual(generate_json("sys", "user", Schema), '{"answer": "hi"}')

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_a_key(self):
        with self.assertRaises(ClaudeApiError):
            generate_json("sys", "user", Schema)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key"}, clear=True)
    @patch("claude_client._session.post", side_effect=requests.ConnectionError("down"))
    def test_raises_on_request_failure(self, _):
        with self.assertRaises(ClaudeApiError):
            generate_json("sys", "user", Schema)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key"}, clear=True)
    @patch("claude_client._session.post")
    def test_raises_on_unexpected_shape(self, mock_post):
        mock_post.return_value = Mock(json=lambda: {"nope": 1})
        with self.assertRaises(ClaudeApiError):
            generate_json("sys", "user", Schema)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key"}, clear=True)
    @patch("claude_client._session.post")
    def test_raises_when_reply_has_no_json(self, mock_post):
        mock_post.return_value = ok_response("sorry, no")
        with self.assertRaises(ClaudeApiError):
            generate_json("sys", "user", Schema)


if __name__ == "__main__":
    unittest.main()
