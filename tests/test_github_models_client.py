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

from github_models_client import GithubModelsError, generate_json


class Schema(BaseModel):
    answer: str


def ok_response(content):
    return Mock(json=lambda: {"choices": [{"message": {"content": content}}]})


class TestGenerateJson(unittest.TestCase):
    @patch.dict(os.environ, {"GITHUB_MODELS_TOKEN": "tok"}, clear=True)
    @patch("github_models_client._session.post")
    def test_returns_reply_text_and_sends_schema_and_auth(self, mock_post):
        mock_post.return_value = ok_response('{"answer": "hi"}')

        result = generate_json("sys", "user", Schema)

        self.assertEqual(result, '{"answer": "hi"}')
        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok")
        self.assertIn("answer", kwargs["json"]["messages"][0]["content"])
        self.assertEqual(kwargs["json"]["messages"][1]["content"], "user")

    @patch.dict(os.environ, {"GITHUB_TOKEN": "actions-tok"}, clear=True)
    @patch("github_models_client._session.post")
    def test_falls_back_to_github_token(self, mock_post):
        mock_post.return_value = ok_response("{}")

        generate_json("sys", "user", Schema)

        self.assertEqual(mock_post.call_args.kwargs["headers"]["Authorization"], "Bearer actions-tok")

    @patch.dict(os.environ, {}, clear=True)
    def test_raises_without_a_token(self):
        with self.assertRaises(GithubModelsError):
            generate_json("sys", "user", Schema)

    @patch.dict(os.environ, {"GITHUB_MODELS_TOKEN": "tok"}, clear=True)
    @patch("github_models_client._session.post", side_effect=requests.ConnectionError("down"))
    def test_raises_on_request_failure(self, _):
        with self.assertRaises(GithubModelsError):
            generate_json("sys", "user", Schema)

    @patch.dict(os.environ, {"GITHUB_MODELS_TOKEN": "tok"}, clear=True)
    @patch("github_models_client._session.post")
    def test_raises_on_unexpected_shape(self, mock_post):
        mock_post.return_value = Mock(json=lambda: {"nope": 1})
        with self.assertRaises(GithubModelsError):
            generate_json("sys", "user", Schema)

    @patch.dict(os.environ, {"GITHUB_MODELS_TOKEN": "tok"}, clear=True)
    @patch("github_models_client._session.post")
    def test_raises_on_empty_content(self, mock_post):
        mock_post.return_value = ok_response("")
        with self.assertRaises(GithubModelsError):
            generate_json("sys", "user", Schema)


if __name__ == "__main__":
    unittest.main()
