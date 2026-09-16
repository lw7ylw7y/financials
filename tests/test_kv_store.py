import json
import os
import sys
import unittest
from unittest import mock

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "web")):
    sys.path.insert(0, _p)

import kv_store
from kv_store import KvStoreError, get_json, is_configured, set_json

ENV = {
    "UPSTASH_REDIS_REST_URL": "https://example-db.upstash.io",
    "UPSTASH_REDIS_REST_TOKEN": "test-token",
}


def mock_response(status_code=200, json_body=None):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = json_body or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = kv_store.requests.exceptions.HTTPError(
            f"{status_code} error"
        )
    else:
        response.raise_for_status.return_value = None
    return response


class TestIsConfigured(unittest.TestCase):
    def test_true_when_url_set(self):
        with mock.patch.dict(os.environ, ENV):
            self.assertTrue(is_configured())

    def test_false_when_unset(self):
        with mock.patch.dict(os.environ, {"UPSTASH_REDIS_REST_URL": ""}):
            self.assertFalse(is_configured())


class TestGetJson(unittest.TestCase):
    def test_returns_none_for_missing_key(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store.requests.get", return_value=mock_response(json_body={"result": None})):
                self.assertIsNone(get_json("nope"))

    def test_round_trips_a_dict_value(self):
        stored = {"a": 1, "b": [1, 2, 3]}
        with mock.patch.dict(os.environ, ENV):
            with mock.patch(
                "kv_store.requests.get",
                return_value=mock_response(json_body={"result": json.dumps(stored)}),
            ) as get:
                result = get_json("mykey")

            self.assertEqual(result, stored)
            called_url = get.call_args[0][0]
            self.assertIn("/get/mykey", called_url)
            self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer test-token")

    def test_raises_on_non_200(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store.requests.get", return_value=mock_response(status_code=500)):
                with self.assertRaises(KvStoreError):
                    get_json("mykey")

    def test_raises_on_request_exception(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch(
                "kv_store.requests.get",
                side_effect=kv_store.requests.exceptions.ConnectionError("boom"),
            ):
                with self.assertRaises(KvStoreError):
                    get_json("mykey")

    def test_raises_without_url_configured(self):
        with mock.patch.dict(os.environ, {"UPSTASH_REDIS_REST_URL": "", "UPSTASH_REDIS_REST_TOKEN": "t"}):
            with self.assertRaises(KvStoreError):
                get_json("mykey")

    def test_raises_without_token_configured(self):
        with mock.patch.dict(os.environ, {**ENV, "UPSTASH_REDIS_REST_TOKEN": ""}):
            with self.assertRaises(KvStoreError):
                get_json("mykey")


class TestSetJson(unittest.TestCase):
    def test_posts_json_encoded_value(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store.requests.post", return_value=mock_response()) as post:
                set_json("mykey", {"a": 1})

            called_url = post.call_args[0][0]
            self.assertIn("/set/mykey", called_url)
            self.assertEqual(json.loads(post.call_args.kwargs["data"]), {"a": 1})

    def test_raises_on_non_200(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store.requests.post", return_value=mock_response(status_code=500)):
                with self.assertRaises(KvStoreError):
                    set_json("mykey", {"a": 1})


if __name__ == "__main__":
    unittest.main()
