import os
import sys
import time
import unittest
from unittest import mock

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

from kv_store import KvStoreError
from ticker_dashboard import (
    TickerConfigError,
    add_ticker_to_group,
    build_ticker_cards,
    check_for_market_news,
    check_for_ticker_updates,
    delete_ticker_snapshot,
    get_initial_market_news,
    get_initial_ticker_page_data,
    load_market_news_state,
    load_ticker_config,
    load_ticker_state,
    remove_ticker_from_group,
    save_market_news_state,
    save_ticker_snapshot,
    save_ticker_state,
)


def config_hash(groups: dict) -> dict:
    """What `hgetall_json("ticker_config")` returns for a given
    `{group_name: [symbols]}` map -- one hash field per group, each
    carrying an `order` index matching the map's own iteration order."""
    return {name: {"symbols": list(symbols), "order": i} for i, (name, symbols) in enumerate(groups.items())}


def fake_hash_store(initial: dict | None = None):
    """A tiny in-memory Redis-hash stand-in shared by hset_json/hget_json/
    hgetall_json/hdel_json mocks, for tests that need a real
    read-after-write round trip rather than asserting individual call
    arguments. Returns (store, fake_hset, fake_hget, fake_hgetall, fake_hdel);
    `store` is the live backing dict, keyed by field name (the `key`
    argument every fake ignores, since each test only ever exercises
    one logical hash key at a time)."""
    store = dict(initial or {})

    def fake_hset(key, field, value):
        store[field] = value

    def fake_hget(key, field):
        return store.get(field)

    def fake_hgetall(key):
        return dict(store)

    def fake_hdel(key, field):
        store.pop(field, None)

    return store, fake_hset, fake_hget, fake_hgetall, fake_hdel


class TestLoadTickerConfig(unittest.TestCase):
    """`ticker_config` is a Redis hash, one field per group (see
    `ticker_dashboard._load_raw_config`'s docstring) -- `hgetall_json`
    is mocked here since these are unit tests, not a live Upstash
    instance, patched on `ticker_dashboard` itself (not `kv_store`)
    because `ticker_dashboard.py` imports the name directly via
    `from kv_store import ...`, so patching the origin module wouldn't
    affect the already-bound name in ticker_dashboard's namespace."""

    def test_loads_groups_and_tickers_in_config_order(self):
        with mock.patch(
            "ticker_dashboard.hgetall_json",
            return_value=config_hash({"bonds": ["VGIT", "VGLT"], "stocks": ["SPY", "IVW", "DGRO"]}),
        ):
            groups = load_ticker_config()

        self.assertEqual(list(groups.keys()), ["bonds", "stocks"])
        self.assertEqual(groups["bonds"], ["VGIT", "VGLT"])
        self.assertEqual(groups["stocks"], ["SPY", "IVW", "DGRO"])

    def test_new_group_key_requires_no_code_change(self):
        with mock.patch("ticker_dashboard.hgetall_json", return_value=config_hash({"crypto": ["BTC"]})):
            groups = load_ticker_config()

        self.assertEqual(groups, {"crypto": ["BTC"]})

    def test_malformed_ticker_skipped_with_warning_others_still_load(self):
        with mock.patch(
            "ticker_dashboard.hgetall_json",
            return_value=config_hash({"stocks": ["SPY", "", "BAD TICKER", "IVW"]}),
        ):
            with self.assertLogs("ticker_dashboard", level="WARNING") as log:
                groups = load_ticker_config()

        self.assertEqual(groups["stocks"], ["SPY", "IVW"])
        self.assertTrue(any("SPY" not in m and "malformed" in m for m in log.output))

    def test_non_string_ticker_entry_is_skipped(self):
        with mock.patch(
            "ticker_dashboard.hgetall_json", return_value=config_hash({"stocks": ["SPY", 123, None]})
        ):
            with self.assertLogs("ticker_dashboard", level="WARNING"):
                groups = load_ticker_config()

        self.assertEqual(groups["stocks"], ["SPY"])

    def test_restores_order_despite_unordered_hash_fields(self):
        """The whole point of the embedded `order` index: Redis doesn't
        guarantee HGETALL returns fields in insertion order (confirmed
        live against a real Upstash instance), so the fields here are
        deliberately handed back already out of order to prove the
        sort-by-`order` step is what fixes display order, not
        incidental dict luck."""
        redis_hash = {
            "sector": {"symbols": ["FTEC"], "order": 3},
            "bonds": {"symbols": ["VGIT"], "order": 1},
            "stocks": {"symbols": ["SPY"], "order": 0},
        }
        with mock.patch("ticker_dashboard.hgetall_json", return_value=redis_hash):
            groups = load_ticker_config()

        self.assertEqual(list(groups.keys()), ["stocks", "bonds", "sector"])

    def test_load_failure_propagates_rather_than_degrading(self):
        """A broken config load should fail loudly, not silently
        render an empty watchlist."""
        with mock.patch("ticker_dashboard.hgetall_json", side_effect=KvStoreError("redis down")):
            with self.assertRaises(KvStoreError):
                load_ticker_config()


class TestAddTickerToGroup(unittest.TestCase):
    def test_appends_to_group(self):
        store, fake_hset, fake_hget, fake_hgetall, _ = fake_hash_store(config_hash({"stocks": ["SPY", "IVW"]}))
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_hset
        ):
            add_ticker_to_group("DGRO", "stocks")

        with mock.patch("ticker_dashboard.hgetall_json", side_effect=fake_hgetall):
            self.assertEqual(load_ticker_config()["stocks"], ["SPY", "IVW", "DGRO"])

    def test_normalizes_case_and_whitespace(self):
        store, fake_hset, fake_hget, _, _ = fake_hash_store(config_hash({"stocks": ["SPY"]}))
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_hset
        ):
            add_ticker_to_group("  dgro  ", "stocks")

        self.assertEqual(store["stocks"]["symbols"], ["SPY", "DGRO"])

    def test_idempotent_if_already_present(self):
        store, fake_hset, fake_hget, _, _ = fake_hash_store(config_hash({"stocks": ["SPY", "IVW"]}))
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_hset
        ) as hset_mock:
            add_ticker_to_group("SPY", "stocks")

        self.assertEqual(store["stocks"]["symbols"], ["SPY", "IVW"])
        hset_mock.assert_not_called()

    def test_rejects_malformed_symbol(self):
        store, fake_hset, fake_hget, _, _ = fake_hash_store(config_hash({"stocks": ["SPY"]}))
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_hset
        ):
            with self.assertRaises(TickerConfigError):
                add_ticker_to_group("BAD TICKER", "stocks")

        self.assertEqual(store["stocks"]["symbols"], ["SPY"])

    def test_rejects_unknown_group(self):
        with mock.patch("ticker_dashboard.hget_json", return_value=None), mock.patch(
            "ticker_dashboard.hset_json"
        ) as hset_mock:
            with self.assertRaises(TickerConfigError):
                add_ticker_to_group("DGRO", "crypto")

        hset_mock.assert_not_called()

    def test_reads_and_writes_only_its_own_group_field(self):
        with mock.patch(
            "ticker_dashboard.hget_json", return_value={"symbols": ["SPY"], "order": 2}
        ) as hget_mock, mock.patch("ticker_dashboard.hset_json") as hset_mock:
            add_ticker_to_group("IVW", "stocks")

        hget_mock.assert_called_once_with("ticker_config", "stocks")
        hset_mock.assert_called_once_with("ticker_config", "stocks", {"symbols": ["SPY", "IVW"], "order": 2})


class TestRemoveTickerFromGroup(unittest.TestCase):
    def test_removes_from_group(self):
        store, fake_hset, fake_hget, fake_hgetall, fake_hdel = fake_hash_store(
            config_hash({"stocks": ["SPY", "IVW", "DGRO"]})
        )
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_hset
        ), mock.patch("ticker_dashboard.hgetall_json", side_effect=fake_hgetall), mock.patch(
            "ticker_dashboard.hdel_json", side_effect=fake_hdel
        ):
            remove_ticker_from_group("IVW", "stocks")

        self.assertEqual(store["stocks"]["symbols"], ["SPY", "DGRO"])

    def test_idempotent_if_not_present(self):
        store, fake_hset, fake_hget, fake_hgetall, fake_hdel = fake_hash_store(
            config_hash({"stocks": ["SPY", "IVW"]})
        )
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_hset
        ) as hset_mock, mock.patch("ticker_dashboard.hgetall_json", side_effect=fake_hgetall):
            remove_ticker_from_group("DGRO", "stocks")

        self.assertEqual(store["stocks"]["symbols"], ["SPY", "IVW"])
        hset_mock.assert_not_called()

    def test_rejects_unknown_group(self):
        with mock.patch("ticker_dashboard.hget_json", return_value=None):
            with self.assertRaises(TickerConfigError):
                remove_ticker_from_group("SPY", "crypto")

    def test_other_groups_are_preserved(self):
        store, fake_hset, fake_hget, fake_hgetall, fake_hdel = fake_hash_store(
            config_hash({"bonds": ["VGIT"], "stocks": ["SPY", "IVW"]})
        )
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_hset
        ), mock.patch("ticker_dashboard.hgetall_json", side_effect=fake_hgetall), mock.patch(
            "ticker_dashboard.hdel_json", side_effect=fake_hdel
        ):
            remove_ticker_from_group("SPY", "stocks")

        self.assertEqual(store["bonds"]["symbols"], ["VGIT"])
        self.assertEqual(store["stocks"]["symbols"], ["IVW"])

    def test_can_empty_a_group_without_removing_it(self):
        store, fake_hset, fake_hget, fake_hgetall, fake_hdel = fake_hash_store(config_hash({"stocks": ["SPY"]}))
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_hset
        ), mock.patch("ticker_dashboard.hgetall_json", side_effect=fake_hgetall), mock.patch(
            "ticker_dashboard.hdel_json", side_effect=fake_hdel
        ):
            remove_ticker_from_group("SPY", "stocks")

        self.assertIn("stocks", store)
        self.assertEqual(store["stocks"]["symbols"], [])

    def test_deletes_cache_entry_once_unused_by_any_group(self):
        config_store, fake_c_hset, fake_c_hget, fake_c_hgetall, fake_c_hdel = fake_hash_store(
            config_hash({"stocks": ["SPY", "IVW"]})
        )
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_c_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_c_hset
        ), mock.patch("ticker_dashboard.hgetall_json", side_effect=fake_c_hgetall), mock.patch(
            "ticker_dashboard.hdel_json"
        ) as hdel_mock:
            remove_ticker_from_group("IVW", "stocks")

        hdel_mock.assert_called_once_with("ticker_cache", "IVW")

    def test_keeps_cache_entry_when_still_used_by_another_group(self):
        _, fake_c_hset, fake_c_hget, fake_c_hgetall, _ = fake_hash_store(
            config_hash({"stocks": ["SPY", "IVW"], "individual": ["IVW"]})
        )
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_c_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_c_hset
        ), mock.patch("ticker_dashboard.hgetall_json", side_effect=fake_c_hgetall), mock.patch(
            "ticker_dashboard.hdel_json"
        ) as hdel_mock:
            remove_ticker_from_group("IVW", "stocks")

        hdel_mock.assert_not_called()

    def test_concurrent_edits_to_different_groups_dont_clobber_each_other(self):
        """The whole point of the per-field design: adding to one
        group and removing from another (standing in for two
        different tabs' concurrent edits) only ever touch their own
        hash field, never each other's."""
        store, fake_hset, fake_hget, fake_hgetall, fake_hdel = fake_hash_store(
            config_hash({"stocks": ["SPY"], "bonds": ["VGIT", "VGLT"]})
        )
        with mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget), mock.patch(
            "ticker_dashboard.hset_json", side_effect=fake_hset
        ), mock.patch("ticker_dashboard.hgetall_json", side_effect=fake_hgetall), mock.patch(
            "ticker_dashboard.hdel_json", side_effect=fake_hdel
        ):
            add_ticker_to_group("IVW", "stocks")
            remove_ticker_from_group("VGLT", "bonds")

        self.assertEqual(store["stocks"]["symbols"], ["SPY", "IVW"])
        self.assertEqual(store["bonds"]["symbols"], ["VGIT"])


class TestBuildTickerCards(unittest.TestCase):
    def test_successful_ticker_computes_price_and_range(self):
        def fake_quote(symbol):
            return {"price": 452.31}

        def fake_metrics(symbol):
            return {"low": 400.0, "high": 480.0}

        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=fake_quote,
            fetch_metrics_fn=fake_metrics,
        )

        card = cards["stocks"][0]
        self.assertEqual(card["symbol"], "SPY")
        self.assertEqual(card["group"], "stocks")
        self.assertEqual(card["price"], 452.31)
        self.assertEqual(card["week52_low"], 400.0)
        self.assertEqual(card["week52_high"], 480.0)
        self.assertIsNone(card["error"])

    def test_one_ticker_failure_does_not_affect_others(self):
        def fake_quote(symbol):
            if symbol == "BADSYM":
                raise RuntimeError("no quote data for BADSYM")
            return {"price": 100.0}

        cards = build_ticker_cards(
            config={"stocks": ["SPY", "BADSYM", "IVW"]},
            fetch_quote_fn=fake_quote,
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 3.0},
        )

        spy, badsym, ivw = cards["stocks"]
        self.assertIsNone(spy["error"])
        self.assertIsNone(ivw["error"])
        self.assertIsNotNone(badsym["error"])
        self.assertIn("BADSYM", badsym["error"])
        self.assertIsNone(badsym["price"])

    def test_week52_failure_also_errors_the_card(self):
        def fake_metrics(symbol):
            raise RuntimeError("no 52-week range for SPY")

        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 100.0},
            fetch_metrics_fn=fake_metrics,
        )

        card = cards["stocks"][0]
        self.assertIsNotNone(card["error"])
        self.assertIsNone(card["price"])

    def test_groups_and_order_match_config(self):
        cards = build_ticker_cards(
            config={"bonds": ["VGIT", "VGLT"], "stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 1.0},
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
        )

        self.assertEqual(list(cards.keys()), ["bonds", "stocks"])
        self.assertEqual([c["symbol"] for c in cards["bonds"]], ["VGIT", "VGLT"])
        self.assertEqual([c["symbol"] for c in cards["stocks"]], ["SPY"])

    def test_defaults_to_loading_config_from_redis(self):
        with mock.patch(
            "ticker_dashboard.hgetall_json",
            return_value=config_hash({"stocks": ["SPY", "IVW", "DGRO"]}),
        ):
            cards = build_ticker_cards(
                fetch_quote_fn=lambda s: {"price": 1.0},
                fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
            )

        self.assertEqual(list(cards.keys()), ["stocks"])
        self.assertEqual([c["symbol"] for c in cards["stocks"]], ["SPY", "IVW", "DGRO"])

    def test_computes_pct_off_high_and_passes_through_change(self):
        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 450.0, "change": -2.5, "change_percent": -0.55},
            fetch_metrics_fn=lambda s: {"low": 400.0, "high": 500.0},
        )

        card = cards["stocks"][0]
        self.assertEqual(card["change"], -2.5)
        self.assertEqual(card["change_percent"], -0.55)
        self.assertEqual(card["pct_off_high"], 10.0)  # (500-450)/500 * 100

    def test_missing_change_fields_in_quote_degrade_to_none(self):
        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 450.0},  # no change/change_percent keys
            fetch_metrics_fn=lambda s: {"low": 400.0, "high": 500.0},
        )

        card = cards["stocks"][0]
        self.assertIsNone(card["change"])
        self.assertIsNone(card["change_percent"])
        self.assertIsNotNone(card["pct_off_high"])

    def test_passes_through_market_cap_and_pe_ratio(self):
        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 450.0},
            fetch_metrics_fn=lambda s: {
                "low": 400.0, "high": 500.0, "market_cap": 3500000.0, "pe_ratio": 34.2,
            },
        )

        card = cards["stocks"][0]
        self.assertEqual(card["market_cap"], 3500000.0)
        self.assertEqual(card["pe_ratio"], 34.2)

    def test_missing_market_cap_and_pe_ratio_degrade_to_none(self):
        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 450.0},
            fetch_metrics_fn=lambda s: {"low": 400.0, "high": 500.0},  # no market_cap/pe_ratio keys
        )

        card = cards["stocks"][0]
        self.assertIsNone(card["market_cap"])
        self.assertIsNone(card["pe_ratio"])

    def test_successful_card_is_not_pending(self):
        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 1.0},
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
        )

        self.assertFalse(cards["stocks"][0]["pending"])

    def test_order_preserved_even_when_slower_tickers_finish_first(self):
        # SPY is made to sleep longest and IVW shortest, forcing them to
        # resolve out of submission order -- output order must still
        # follow config order, not completion order.
        delays = {"SPY": 0.06, "IVW": 0.0, "DGRO": 0.03}

        def fake_quote(symbol):
            time.sleep(delays[symbol])
            return {"price": float(len(symbol))}

        cards = build_ticker_cards(
            config={"stocks": ["SPY", "IVW", "DGRO"]},
            fetch_quote_fn=fake_quote,
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
        )

        self.assertEqual([c["symbol"] for c in cards["stocks"]], ["SPY", "IVW", "DGRO"])

    def test_fetches_run_concurrently_not_sequentially(self):
        # 5 tickers each sleeping 0.1s: sequential would take >=0.5s;
        # concurrent (max_workers=5 default) should take close to 0.1s.
        symbols = ["A", "B", "C", "D", "E"]

        def slow_quote(symbol):
            time.sleep(0.1)
            return {"price": 1.0}

        started = time.monotonic()
        build_ticker_cards(
            config={"stocks": symbols},
            fetch_quote_fn=slow_quote,
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
        )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.3)

    def test_more_tickers_than_max_workers_still_processes_all(self):
        symbols = [f"SYM{i}" for i in range(12)]

        cards = build_ticker_cards(
            config={"stocks": symbols},
            fetch_quote_fn=lambda s: {"price": 1.0},
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
            max_workers=5,
        )

        self.assertEqual([c["symbol"] for c in cards["stocks"]], symbols)
        self.assertTrue(all(c["error"] is None for c in cards["stocks"]))

    def test_errored_card_is_not_pending(self):
        def failing_quote(symbol):
            raise RuntimeError("boom")

        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=failing_quote,
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
        )

        self.assertFalse(cards["stocks"][0]["pending"])


class TestTickerCachePersistence(unittest.TestCase):
    """`ticker_cache` is a Redis hash, one field per symbol
    (`ticker_dashboard.save_ticker_snapshot`'s docstring) -- a
    per-symbol write is a genuinely atomic HSET, never a
    read-modify-write of every other symbol's data."""

    def test_write_then_reload_matches(self):
        _, fake_hset, _, fake_hgetall, _ = fake_hash_store()
        state = {"SPY": {"price": 452.31, "week52_low": 400.0, "week52_high": 480.0,
                          "fetched_at": "2026-09-13T12:00:00+00:00"}}

        with mock.patch("ticker_dashboard.hset_json", side_effect=fake_hset), mock.patch(
            "ticker_dashboard.hgetall_json", side_effect=fake_hgetall
        ):
            save_ticker_state(state)
            reloaded = load_ticker_state()

        self.assertEqual(reloaded, state)

    def test_missing_key_returns_empty_dict(self):
        with mock.patch("ticker_dashboard.hgetall_json", return_value={}):
            self.assertEqual(load_ticker_state(), {})

    def test_load_degrades_to_empty_dict_on_redis_outage(self):
        with mock.patch("ticker_dashboard.hgetall_json", side_effect=KvStoreError("redis down")):
            self.assertEqual(load_ticker_state(), {})

    def test_save_snapshot_writes_one_hash_field(self):
        with mock.patch("ticker_dashboard.hset_json") as hset_mock:
            save_ticker_snapshot("SPY", {"price": 1.0})

        hset_mock.assert_called_once_with("ticker_cache", "SPY", {"price": 1.0})

    def test_save_snapshot_outage_is_swallowed_not_raised(self):
        with mock.patch("ticker_dashboard.hset_json", side_effect=KvStoreError("redis down")):
            save_ticker_snapshot("SPY", {"price": 1.0})

    def test_save_state_bulk_writes_one_hash_field_per_symbol(self):
        with mock.patch("ticker_dashboard.hset_json") as hset_mock:
            save_ticker_state({"SPY": {"price": 1.0}, "VGIT": {"price": 2.0}})

        hset_mock.assert_any_call("ticker_cache", "SPY", {"price": 1.0})
        hset_mock.assert_any_call("ticker_cache", "VGIT", {"price": 2.0})
        self.assertEqual(hset_mock.call_count, 2)

    def test_concurrent_snapshot_writes_to_different_symbols_dont_clobber_each_other(self):
        """The whole point of the hash-field design: two symbols'
        writes (standing in for two different groups', or two
        different users', concurrent live checks) never touch a shared
        blob, so neither can wipe out the other's data -- unlike the
        old load-the-whole-cache-then-save-it-all-back pattern this
        replaced."""
        store, fake_hset, _, _, _ = fake_hash_store()

        with mock.patch("ticker_dashboard.hset_json", side_effect=fake_hset):
            save_ticker_snapshot("SPY", {"price": 1.0})
            save_ticker_snapshot("VGIT", {"price": 2.0})

        self.assertEqual(store, {"SPY": {"price": 1.0}, "VGIT": {"price": 2.0}})

    def test_delete_snapshot_removes_one_field(self):
        with mock.patch("ticker_dashboard.hdel_json") as hdel_mock:
            delete_ticker_snapshot("SPY")

        hdel_mock.assert_called_once_with("ticker_cache", "SPY")

    def test_delete_snapshot_outage_is_swallowed_not_raised(self):
        with mock.patch("ticker_dashboard.hdel_json", side_effect=KvStoreError("redis down")):
            delete_ticker_snapshot("SPY")


class TestGetInitialTickerPageData(unittest.TestCase):
    def test_ticker_with_stored_snapshot_renders_its_values(self):
        with mock.patch(
            "ticker_dashboard.hgetall_json",
            return_value={"SPY": {"price": 452.31, "week52_low": 400.0, "week52_high": 480.0}},
        ):
            cards = get_initial_ticker_page_data(config={"stocks": ["SPY"]})

        card = cards["stocks"][0]
        self.assertFalse(card["pending"])
        self.assertIsNone(card["error"])
        self.assertEqual(card["price"], 452.31)

    def test_ticker_with_no_stored_snapshot_renders_pending(self):
        with mock.patch("ticker_dashboard.hgetall_json", return_value={}):
            cards = get_initial_ticker_page_data(config={"stocks": ["NEWTICKER"]})

        card = cards["stocks"][0]
        self.assertTrue(card["pending"])
        self.assertIsNone(card["error"])
        self.assertIsNone(card["price"])

    def test_never_makes_a_network_call(self):
        # No fetch_fn parameters exist on this function at all -- if it took
        # any, that would itself indicate a live call snuck into the "instant" path.
        with mock.patch("ticker_dashboard.hgetall_json", return_value={}):
            cards = get_initial_ticker_page_data(config={"stocks": ["SPY"]})
        self.assertEqual(len(cards["stocks"]), 1)


class TestCheckForTickerUpdates(unittest.TestCase):
    def test_successful_fetch_persists_snapshot(self):
        store, fake_hset, _, fake_hgetall, _ = fake_hash_store()
        with mock.patch("ticker_dashboard.hset_json", side_effect=fake_hset), mock.patch(
            "ticker_dashboard.hgetall_json", side_effect=fake_hgetall
        ):
            cards = check_for_ticker_updates(
                config={"stocks": ["SPY"]},
                fetch_quote_fn=lambda s: {"price": 452.31},
                fetch_metrics_fn=lambda s: {"low": 400.0, "high": 480.0},
            )

        self.assertFalse(cards["stocks"][0]["pending"])
        self.assertIsNone(cards["stocks"][0]["error"])
        self.assertEqual(cards["stocks"][0]["price"], 452.31)
        self.assertEqual(store["SPY"]["price"], 452.31)
        self.assertIn("fetched_at", store["SPY"])

    def test_failed_fetch_falls_back_to_stored_snapshot_silently(self):
        _, fake_hset, _, fake_hgetall, _ = fake_hash_store(
            {"SPY": {"price": 440.0, "week52_low": 400.0, "week52_high": 480.0}}
        )

        def failing_quote(symbol):
            raise RuntimeError("finnhub is down")

        with mock.patch("ticker_dashboard.hset_json", side_effect=fake_hset), mock.patch(
            "ticker_dashboard.hgetall_json", side_effect=fake_hgetall
        ):
            cards = check_for_ticker_updates(
                config={"stocks": ["SPY"]},
                fetch_quote_fn=failing_quote,
                fetch_metrics_fn=lambda s: {"low": 400.0, "high": 480.0},
            )

        card = cards["stocks"][0]
        self.assertIsNone(card["error"])
        self.assertFalse(card["pending"])
        self.assertEqual(card["price"], 440.0)

    def test_failed_fetch_with_no_stored_snapshot_is_a_genuine_error(self):
        def failing_quote(symbol):
            raise RuntimeError("no quote data for NEWTICKER")

        with mock.patch("ticker_dashboard.hgetall_json", return_value={}):
            cards = check_for_ticker_updates(
                config={"stocks": ["NEWTICKER"]},
                fetch_quote_fn=failing_quote,
                fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
            )

        card = cards["stocks"][0]
        self.assertIsNotNone(card["error"])
        self.assertFalse(card["pending"])

    def test_always_refetches_even_when_a_snapshot_already_exists(self):
        _, fake_hset, _, fake_hgetall, _ = fake_hash_store(
            {"SPY": {"price": 100.0, "week52_low": 90.0, "week52_high": 110.0}}
        )
        call_count = {"n": 0}

        def counting_quote(symbol):
            call_count["n"] += 1
            return {"price": 999.0}

        with mock.patch("ticker_dashboard.hset_json", side_effect=fake_hset), mock.patch(
            "ticker_dashboard.hgetall_json", side_effect=fake_hgetall
        ):
            cards = check_for_ticker_updates(
                config={"stocks": ["SPY"]},
                fetch_quote_fn=counting_quote,
                fetch_metrics_fn=lambda s: {"low": 90.0, "high": 110.0},
            )

        self.assertEqual(call_count["n"], 1)
        self.assertEqual(cards["stocks"][0]["price"], 999.0)


class TestMarketNewsCachePersistence(unittest.TestCase):
    def test_write_then_reload_matches(self):
        store = {}
        state = {"headlines": [{"headline": "Stocks rally", "url": "https://a", "source": "CNBC", "datetime": 1}],
                 "fetched_at": "2026-09-14T12:00:00+00:00"}

        with mock.patch("ticker_dashboard.set_json", side_effect=lambda k, v: store.__setitem__(k, v)), mock.patch(
            "ticker_dashboard.get_json", side_effect=lambda k: store.get(k)
        ):
            save_market_news_state(state)
            reloaded = load_market_news_state()

        self.assertEqual(reloaded, state)

    def test_missing_key_returns_none(self):
        with mock.patch("ticker_dashboard.get_json", return_value=None):
            self.assertIsNone(load_market_news_state())

    def test_load_degrades_to_none_on_redis_outage(self):
        with mock.patch("ticker_dashboard.get_json", side_effect=KvStoreError("redis down")):
            self.assertIsNone(load_market_news_state())

    def test_save_outage_is_swallowed_not_raised(self):
        with mock.patch("ticker_dashboard.set_json", side_effect=KvStoreError("redis down")):
            save_market_news_state({"headlines": []})


class TestGetInitialMarketNews(unittest.TestCase):
    def test_no_cache_yet_is_pending(self):
        with mock.patch("ticker_dashboard.get_json", return_value=None):
            result = get_initial_market_news()

        self.assertTrue(result["pending"])
        self.assertEqual(result["headlines"], [])

    def test_cached_headlines_render_without_network(self):
        with mock.patch(
            "ticker_dashboard.get_json",
            return_value={"headlines": [{"headline": "Stocks rally", "url": "https://a", "source": "CNBC", "datetime": 1}]},
        ):
            result = get_initial_market_news()

        self.assertFalse(result["pending"])
        self.assertEqual(len(result["headlines"]), 1)


class TestCheckForMarketNews(unittest.TestCase):
    def test_successful_fetch_persists(self):
        store = {}
        headlines = [{"headline": "Stocks rally", "url": "https://a", "source": "CNBC", "datetime": 1}]

        with mock.patch("ticker_dashboard.set_json", side_effect=lambda k, v: store.__setitem__(k, v)), mock.patch(
            "ticker_dashboard.get_json", side_effect=lambda k: store.get(k)
        ):
            result = check_for_market_news(fetch_news_fn=lambda: headlines)

        self.assertFalse(result["pending"])
        self.assertEqual(result["headlines"], headlines)
        self.assertEqual(store["market_news_cache"]["headlines"], headlines)
        self.assertIn("fetched_at", store["market_news_cache"])

    def test_failed_fetch_falls_back_to_cached_headlines_silently(self):
        cached = [{"headline": "Old news", "url": "https://a", "source": "CNBC", "datetime": 1}]

        def failing_fetch():
            raise RuntimeError("finnhub is down")

        with mock.patch("ticker_dashboard.get_json", return_value={"headlines": cached}):
            result = check_for_market_news(fetch_news_fn=failing_fetch)

        self.assertFalse(result["pending"])
        self.assertEqual(result["headlines"], cached)

    def test_failed_fetch_with_no_cache_returns_empty_list(self):
        def failing_fetch():
            raise RuntimeError("finnhub is down")

        with mock.patch("ticker_dashboard.get_json", return_value=None):
            result = check_for_market_news(fetch_news_fn=failing_fetch)

        self.assertFalse(result["pending"])
        self.assertEqual(result["headlines"], [])


if __name__ == "__main__":
    unittest.main()
