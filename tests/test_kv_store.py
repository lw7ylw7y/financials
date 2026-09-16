import json
import os
import sys
import unittest
from unittest import mock

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (_SRC, os.path.join(_SRC, "web")):
    sys.path.insert(0, _p)

import kv_store
from kv_store import KvStoreError, get_json, hget_json, hgetall_json, hset_json, is_configured, set_json

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
            with mock.patch("kv_store._session.get", return_value=mock_response(json_body={"result": None})):
                self.assertIsNone(get_json("nope"))

    def test_round_trips_a_dict_value(self):
        stored = {"a": 1, "b": [1, 2, 3]}
        with mock.patch.dict(os.environ, ENV):
            with mock.patch(
                "kv_store._session.get",
                return_value=mock_response(json_body={"result": json.dumps(stored)}),
            ) as get:
                result = get_json("mykey")

            self.assertEqual(result, stored)
            called_url = get.call_args[0][0]
            self.assertIn("/get/mykey", called_url)
            self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer test-token")

    def test_raises_on_non_200(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.get", return_value=mock_response(status_code=500)):
                with self.assertRaises(KvStoreError):
                    get_json("mykey")

    def test_raises_on_request_exception(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch(
                "kv_store._session.get",
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

    def test_strips_stray_quotes_pasted_around_the_url(self):
        """Confirmed live: Render's env var fields aren't shell-parsed,
        so a value pasted with literal surrounding quotes (e.g.
        '"https://x.upstash.io"') keeps those quotes as part of the
        string -- `requests` then raises InvalidSchema on the malformed
        URL rather than anything pointing at the real cause."""
        quoted_env = {**ENV, "UPSTASH_REDIS_REST_URL": '"https://example-db.upstash.io"'}
        with mock.patch.dict(os.environ, quoted_env):
            with mock.patch(
                "kv_store._session.get",
                return_value=mock_response(json_body={"result": None}),
            ) as get:
                get_json("mykey")

            called_url = get.call_args[0][0]
            self.assertTrue(called_url.startswith("https://example-db.upstash.io/"))
            self.assertNotIn('"', called_url)

    def test_strips_stray_quotes_pasted_around_the_token(self):
        quoted_env = {**ENV, "UPSTASH_REDIS_REST_TOKEN": "'test-token'"}
        with mock.patch.dict(os.environ, quoted_env):
            with mock.patch(
                "kv_store._session.get",
                return_value=mock_response(json_body={"result": None}),
            ) as get:
                get_json("mykey")

            self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer test-token")


class TestSetJson(unittest.TestCase):
    def test_posts_json_encoded_value(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.post", return_value=mock_response()) as post:
                set_json("mykey", {"a": 1})

            called_url = post.call_args[0][0]
            self.assertIn("/set/mykey", called_url)
            self.assertEqual(json.loads(post.call_args.kwargs["data"]), {"a": 1})

    def test_raises_on_non_200(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.post", return_value=mock_response(status_code=500)):
                with self.assertRaises(KvStoreError):
                    set_json("mykey", {"a": 1})


class TestHsetJson(unittest.TestCase):
    """hset_json/hgetall_json are the per-field alternative to
    get_json/set_json's whole-key replace -- used where a single
    caller shouldn't have to read and rewrite every other field just
    to update one (see ticker_dashboard.save_ticker_snapshot). Wire
    format confirmed live against a real Upstash instance: `POST
    {url}/hset/{key}/{field}` with the raw JSON value as the body
    (mirrors `/set/{key}`'s shape), `GET {url}/hgetall/{key}` returning
    `{"result": [field1, value1, field2, value2, ...]}` as a flat,
    alternating array.
    """

    def test_posts_json_encoded_value_to_the_field_path(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.post", return_value=mock_response()) as post:
                hset_json("ticker_cache", "SPY", {"price": 452.31})

            called_url = post.call_args[0][0]
            self.assertIn("/hset/ticker_cache/SPY", called_url)
            self.assertEqual(json.loads(post.call_args.kwargs["data"]), {"price": 452.31})

    def test_raises_on_non_200(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.post", return_value=mock_response(status_code=500)):
                with self.assertRaises(KvStoreError):
                    hset_json("ticker_cache", "SPY", {"price": 452.31})

    def test_raises_on_request_exception(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch(
                "kv_store._session.post",
                side_effect=kv_store.requests.exceptions.ConnectionError("boom"),
            ):
                with self.assertRaises(KvStoreError):
                    hset_json("ticker_cache", "SPY", {"price": 452.31})


class TestHgetJson(unittest.TestCase):
    """hget_json reads one hash field without fetching every other
    field the way hgetall_json does -- used to check a group exists
    and read its current value before mutating just that one field
    (see ticker_dashboard.add_ticker_to_group). Wire format confirmed
    live: `GET {url}/hget/{key}/{field}` returning `{"result": null}`
    for a missing field, `{"result": "<json>"}` for an existing one.
    """

    def test_decodes_an_existing_field(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch(
                "kv_store._session.get",
                return_value=mock_response(json_body={"result": json.dumps({"symbols": ["SPY"], "order": 0})}),
            ) as get:
                result = hget_json("ticker_config", "stocks")

            self.assertEqual(result, {"symbols": ["SPY"], "order": 0})
            called_url = get.call_args[0][0]
            self.assertIn("/hget/ticker_config/stocks", called_url)

    def test_returns_none_for_missing_field(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.get", return_value=mock_response(json_body={"result": None})):
                self.assertIsNone(hget_json("ticker_config", "nonexistent"))

    def test_raises_on_non_200(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.get", return_value=mock_response(status_code=500)):
                with self.assertRaises(KvStoreError):
                    hget_json("ticker_config", "stocks")

    def test_raises_on_corrupt_value(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch(
                "kv_store._session.get",
                return_value=mock_response(json_body={"result": "{not valid json"}),
            ):
                with self.assertRaises(KvStoreError):
                    hget_json("ticker_config", "stocks")


class TestHgetallJson(unittest.TestCase):
    def test_decodes_the_flat_field_value_array_into_a_dict(self):
        flat = ["SPY", json.dumps({"price": 452.31}), "VGIT", json.dumps({"price": 60.1})]
        with mock.patch.dict(os.environ, ENV):
            with mock.patch(
                "kv_store._session.get",
                return_value=mock_response(json_body={"result": flat}),
            ) as get:
                result = hgetall_json("ticker_cache")

            self.assertEqual(result, {"SPY": {"price": 452.31}, "VGIT": {"price": 60.1}})
            called_url = get.call_args[0][0]
            self.assertIn("/hgetall/ticker_cache", called_url)

    def test_empty_hash_returns_empty_dict(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.get", return_value=mock_response(json_body={"result": []})):
                self.assertEqual(hgetall_json("ticker_cache"), {})

    def test_raises_on_non_200(self):
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.get", return_value=mock_response(status_code=500)):
                with self.assertRaises(KvStoreError):
                    hgetall_json("ticker_cache")

    def test_raises_on_corrupt_field_value(self):
        flat = ["SPY", "{not valid json"]
        with mock.patch.dict(os.environ, ENV):
            with mock.patch("kv_store._session.get", return_value=mock_response(json_body={"result": flat})):
                with self.assertRaises(KvStoreError):
                    hgetall_json("ticker_cache")


if __name__ == "__main__":
    unittest.main()
