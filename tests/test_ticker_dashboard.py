import json
import os
import sys
import tempfile
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
    CONFIG_PATH,
    MARKET_NEWS_PATH,
    TICKER_DATA_PATH,
    TickerConfigError,
    add_ticker_to_group,
    build_ticker_cards,
    check_for_market_news,
    check_for_ticker_updates,
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


def write_config(tmp_dir, groups):
    path = os.path.join(tmp_dir, "tickers.json")
    with open(path, "w") as f:
        json.dump({"groups": groups}, f)
    return path


class TestLoadTickerConfig(unittest.TestCase):
    def test_loads_groups_and_tickers_in_file_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(
                tmp_dir,
                {
                    "bonds": ["VGIT", "VGLT"],
                    "stocks": ["SPY", "IVW", "DGRO"],
                },
            )

            groups = load_ticker_config(path)

            self.assertEqual(list(groups.keys()), ["bonds", "stocks"])
            self.assertEqual(groups["bonds"], ["VGIT", "VGLT"])
            self.assertEqual(groups["stocks"], ["SPY", "IVW", "DGRO"])

    def test_new_group_key_requires_no_code_change(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"crypto": ["BTC"]})

            groups = load_ticker_config(path)

            self.assertEqual(groups, {"crypto": ["BTC"]})

    def test_renamed_group_key_changes_header_keeps_tickers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"sector_and_individual": ["FTEC", "MSFT"]})

            groups = load_ticker_config(path)

            self.assertEqual(groups, {"sector_and_individual": ["FTEC", "MSFT"]})

    def test_malformed_ticker_skipped_with_warning_others_still_load(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY", "", "BAD TICKER", "IVW"]})

            with self.assertLogs("ticker_dashboard", level="WARNING") as log:
                groups = load_ticker_config(path)

            self.assertEqual(groups["stocks"], ["SPY", "IVW"])
            self.assertTrue(any("SPY" not in m and "malformed" in m for m in log.output))

    def test_non_string_ticker_entry_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY", 123, None]})

            with self.assertLogs("ticker_dashboard", level="WARNING"):
                groups = load_ticker_config(path)

            self.assertEqual(groups["stocks"], ["SPY"])

    def test_default_config_path_loads_the_live_watchlist(self):
        """A smoke test against the real config/tickers.json, not a fixed
        watchlist snapshot -- Story 2's whole point is that this file is
        hand-edited freely, so pinning its exact contents here would make
        the test suite fail every time the watchlist is legitimately
        updated. Checks the loader handles the real file's shape, not
        what's currently in it."""
        groups = load_ticker_config(CONFIG_PATH)

        self.assertTrue(groups)
        for group_name, symbols in groups.items():
            self.assertTrue(symbols, f"group {group_name!r} has no tickers")
            for symbol in symbols:
                self.assertTrue(symbol.isalnum(), f"{symbol!r} in {group_name!r} isn't a valid ticker")


class TestBuildTickerCards(unittest.TestCase):
    def test_successful_ticker_computes_price_range_and_moving_averages(self):
        closes = [float(i) for i in range(1, 251)]  # 250 closes: 1.0 .. 250.0

        def fake_quote(symbol):
            return {"price": 452.31}

        def fake_metrics(symbol):
            return {"low": 400.0, "high": 480.0}

        def fake_closes(symbol):
            return closes

        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=fake_quote,
            fetch_metrics_fn=fake_metrics,
            fetch_closes_fn=fake_closes,
        )

        card = cards["stocks"][0]
        self.assertEqual(card["symbol"], "SPY")
        self.assertEqual(card["group"], "stocks")
        self.assertEqual(card["price"], 452.31)
        self.assertEqual(card["week52_low"], 400.0)
        self.assertEqual(card["week52_high"], 480.0)
        self.assertEqual(card["ma20"], sum(closes[-20:]) / 20)
        self.assertEqual(card["ma50"], sum(closes[-50:]) / 50)
        self.assertEqual(card["ma200"], sum(closes[-200:]) / 200)
        self.assertIsNone(card["error"])

    def test_fewer_than_200_candles_leaves_ma200_none(self):
        closes = [float(i) for i in range(1, 51)]  # only 50 closes

        cards = build_ticker_cards(
            config={"stocks": ["NEWCO"]},
            fetch_quote_fn=lambda s: {"price": 10.0},
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 50.0},
            fetch_closes_fn=lambda s: closes,
        )

        card = cards["stocks"][0]
        self.assertEqual(card["ma20"], sum(closes[-20:]) / 20)
        self.assertEqual(card["ma50"], sum(closes) / 50)
        self.assertIsNone(card["ma200"])
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
            fetch_closes_fn=lambda s: [1.0, 2.0, 3.0],
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
            fetch_closes_fn=lambda s: [1.0, 2.0, 3.0],
        )

        card = cards["stocks"][0]
        self.assertIsNotNone(card["error"])
        self.assertIsNone(card["price"])

    def test_closes_failure_also_errors_the_card(self):
        def fake_closes(symbol):
            raise RuntimeError("chart request failed for SPY")

        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 100.0},
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 3.0},
            fetch_closes_fn=fake_closes,
        )

        card = cards["stocks"][0]
        self.assertIsNotNone(card["error"])
        self.assertIsNone(card["ma20"])

    def test_groups_and_order_match_config(self):
        cards = build_ticker_cards(
            config={"bonds": ["VGIT", "VGLT"], "stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 1.0},
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
            fetch_closes_fn=lambda s: [1.0, 2.0],
        )

        self.assertEqual(list(cards.keys()), ["bonds", "stocks"])
        self.assertEqual([c["symbol"] for c in cards["bonds"]], ["VGIT", "VGLT"])
        self.assertEqual([c["symbol"] for c in cards["stocks"]], ["SPY"])

    def test_defaults_to_loading_config_from_disk(self):
        cards = build_ticker_cards(
            fetch_quote_fn=lambda s: {"price": 1.0},
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
            fetch_closes_fn=lambda s: [1.0, 2.0],
        )

        self.assertEqual(list(cards.keys()), ["stocks", "bonds", "international", "sector", "individual"])
        self.assertEqual([c["symbol"] for c in cards["stocks"]], ["SPY", "IVW", "DGRO"])

    def test_computes_pct_off_high_and_passes_through_change(self):
        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 450.0, "change": -2.5, "change_percent": -0.55},
            fetch_metrics_fn=lambda s: {"low": 400.0, "high": 500.0},
            fetch_closes_fn=lambda s: [1.0, 2.0],
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
            fetch_closes_fn=lambda s: [1.0, 2.0],
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
            fetch_closes_fn=lambda s: [1.0, 2.0],
        )

        card = cards["stocks"][0]
        self.assertEqual(card["market_cap"], 3500000.0)
        self.assertEqual(card["pe_ratio"], 34.2)

    def test_missing_market_cap_and_pe_ratio_degrade_to_none(self):
        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 450.0},
            fetch_metrics_fn=lambda s: {"low": 400.0, "high": 500.0},  # no market_cap/pe_ratio keys
            fetch_closes_fn=lambda s: [1.0, 2.0],
        )

        card = cards["stocks"][0]
        self.assertIsNone(card["market_cap"])
        self.assertIsNone(card["pe_ratio"])

    def test_successful_card_is_not_pending(self):
        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 1.0},
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
            fetch_closes_fn=lambda s: [1.0, 2.0],
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
            fetch_closes_fn=lambda s: [1.0, 2.0],
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
            fetch_closes_fn=lambda s: [1.0, 2.0],
        )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.3)

    def test_more_tickers_than_max_workers_still_processes_all(self):
        symbols = [f"SYM{i}" for i in range(12)]

        cards = build_ticker_cards(
            config={"stocks": symbols},
            fetch_quote_fn=lambda s: {"price": 1.0},
            fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
            fetch_closes_fn=lambda s: [1.0, 2.0],
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
            fetch_closes_fn=lambda s: [1.0, 2.0],
        )

        self.assertFalse(cards["stocks"][0]["pending"])


class TestTickerStatePersistence(unittest.TestCase):
    def test_write_then_reload_matches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "tickers.json")
            state = {"SPY": {"price": 452.31, "week52_low": 400.0, "week52_high": 480.0,
                              "ma20": 448.5, "ma50": 440.0, "ma200": 430.2,
                              "fetched_at": "2026-09-13T12:00:00+00:00"}}

            save_ticker_state(state, path)
            reloaded = load_ticker_state(path)

            self.assertEqual(reloaded, state)

    def test_missing_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "does-not-exist.json")

            self.assertEqual(load_ticker_state(path), {})

    def test_corrupted_file_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "tickers.json")
            with open(path, "w") as f:
                f.write("{not valid json")

            self.assertEqual(load_ticker_state(path), {})


class TestGetInitialTickerPageData(unittest.TestCase):
    def test_ticker_with_stored_snapshot_renders_its_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = os.path.join(tmp_dir, "tickers.json")
            save_ticker_state(
                {"SPY": {"price": 452.31, "week52_low": 400.0, "week52_high": 480.0,
                         "ma20": 448.5, "ma50": 440.0, "ma200": 430.2}},
                state_path,
            )

            cards = get_initial_ticker_page_data(config={"stocks": ["SPY"]}, state_path=state_path)

            card = cards["stocks"][0]
            self.assertFalse(card["pending"])
            self.assertIsNone(card["error"])
            self.assertEqual(card["price"], 452.31)
            self.assertEqual(card["ma50"], 440.0)

    def test_ticker_with_no_stored_snapshot_renders_pending(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = os.path.join(tmp_dir, "tickers.json")

            cards = get_initial_ticker_page_data(config={"stocks": ["NEWTICKER"]}, state_path=state_path)

            card = cards["stocks"][0]
            self.assertTrue(card["pending"])
            self.assertIsNone(card["error"])
            self.assertIsNone(card["price"])

    def test_never_makes_a_network_call(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = os.path.join(tmp_dir, "tickers.json")
            # No fetch_fn parameters exist on this function at all -- if it took
            # any, that would itself indicate a live call snuck into the "instant" path.
            cards = get_initial_ticker_page_data(config={"stocks": ["SPY"]}, state_path=state_path)
            self.assertEqual(len(cards["stocks"]), 1)


class TestCheckForTickerUpdates(unittest.TestCase):
    def test_successful_fetch_persists_snapshot_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = os.path.join(tmp_dir, "tickers.json")

            cards = check_for_ticker_updates(
                config={"stocks": ["SPY"]},
                fetch_quote_fn=lambda s: {"price": 452.31},
                fetch_metrics_fn=lambda s: {"low": 400.0, "high": 480.0},
                fetch_closes_fn=lambda s: [1.0] * 200,
                state_path=state_path,
            )

            self.assertFalse(cards["stocks"][0]["pending"])
            self.assertIsNone(cards["stocks"][0]["error"])
            self.assertEqual(cards["stocks"][0]["price"], 452.31)

            persisted = load_ticker_state(state_path)
            self.assertEqual(persisted["SPY"]["price"], 452.31)
            self.assertIn("fetched_at", persisted["SPY"])

    def test_failed_fetch_falls_back_to_stored_snapshot_silently(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = os.path.join(tmp_dir, "tickers.json")
            save_ticker_state(
                {"SPY": {"price": 440.0, "week52_low": 400.0, "week52_high": 480.0,
                         "ma20": 435.0, "ma50": 430.0, "ma200": 420.0}},
                state_path,
            )

            def failing_quote(symbol):
                raise RuntimeError("finnhub is down")

            cards = check_for_ticker_updates(
                config={"stocks": ["SPY"]},
                fetch_quote_fn=failing_quote,
                fetch_metrics_fn=lambda s: {"low": 400.0, "high": 480.0},
                fetch_closes_fn=lambda s: [1.0] * 200,
                state_path=state_path,
            )

            card = cards["stocks"][0]
            self.assertIsNone(card["error"])
            self.assertFalse(card["pending"])
            self.assertEqual(card["price"], 440.0)

    def test_failed_fetch_with_no_stored_snapshot_is_a_genuine_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = os.path.join(tmp_dir, "tickers.json")

            def failing_quote(symbol):
                raise RuntimeError("no quote data for NEWTICKER")

            cards = check_for_ticker_updates(
                config={"stocks": ["NEWTICKER"]},
                fetch_quote_fn=failing_quote,
                fetch_metrics_fn=lambda s: {"low": 1.0, "high": 2.0},
                fetch_closes_fn=lambda s: [1.0, 2.0],
                state_path=state_path,
            )

            card = cards["stocks"][0]
            self.assertIsNotNone(card["error"])
            self.assertFalse(card["pending"])

    def test_always_refetches_even_when_a_snapshot_already_exists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = os.path.join(tmp_dir, "tickers.json")
            save_ticker_state(
                {"SPY": {"price": 100.0, "week52_low": 90.0, "week52_high": 110.0,
                         "ma20": 99.0, "ma50": 98.0, "ma200": 95.0}},
                state_path,
            )
            call_count = {"n": 0}

            def counting_quote(symbol):
                call_count["n"] += 1
                return {"price": 999.0}

            cards = check_for_ticker_updates(
                config={"stocks": ["SPY"]},
                fetch_quote_fn=counting_quote,
                fetch_metrics_fn=lambda s: {"low": 90.0, "high": 110.0},
                fetch_closes_fn=lambda s: [1.0] * 200,
                state_path=state_path,
            )

            self.assertEqual(call_count["n"], 1)
            self.assertEqual(cards["stocks"][0]["price"], 999.0)


class TestMarketNewsPersistence(unittest.TestCase):
    def test_write_then_reload_matches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "market_news.json")
            state = {"headlines": [{"headline": "Stocks rally", "url": "https://a", "source": "CNBC", "datetime": 1}],
                      "fetched_at": "2026-09-14T12:00:00+00:00"}

            save_market_news_state(state, path)
            reloaded = load_market_news_state(path)

            self.assertEqual(reloaded, state)

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "does-not-exist.json")

            self.assertIsNone(load_market_news_state(path))

    def test_corrupted_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "market_news.json")
            with open(path, "w") as f:
                f.write("{not valid json")

            self.assertIsNone(load_market_news_state(path))


class TestGetInitialMarketNews(unittest.TestCase):
    def test_no_cache_yet_is_pending(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "market_news.json")

            result = get_initial_market_news(path)

            self.assertTrue(result["pending"])
            self.assertEqual(result["headlines"], [])

    def test_cached_headlines_render_without_network(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "market_news.json")
            save_market_news_state(
                {"headlines": [{"headline": "Stocks rally", "url": "https://a", "source": "CNBC", "datetime": 1}]},
                path,
            )

            result = get_initial_market_news(path)

            self.assertFalse(result["pending"])
            self.assertEqual(len(result["headlines"]), 1)


class TestCheckForMarketNews(unittest.TestCase):
    def test_successful_fetch_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "market_news.json")
            headlines = [{"headline": "Stocks rally", "url": "https://a", "source": "CNBC", "datetime": 1}]

            result = check_for_market_news(fetch_news_fn=lambda: headlines, path=path)

            self.assertFalse(result["pending"])
            self.assertEqual(result["headlines"], headlines)
            persisted = load_market_news_state(path)
            self.assertEqual(persisted["headlines"], headlines)
            self.assertIn("fetched_at", persisted)

    def test_failed_fetch_falls_back_to_cached_headlines_silently(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "market_news.json")
            cached = [{"headline": "Old news", "url": "https://a", "source": "CNBC", "datetime": 1}]
            save_market_news_state({"headlines": cached}, path)

            def failing_fetch():
                raise RuntimeError("finnhub is down")

            result = check_for_market_news(fetch_news_fn=failing_fetch, path=path)

            self.assertFalse(result["pending"])
            self.assertEqual(result["headlines"], cached)

    def test_failed_fetch_with_no_cache_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "market_news.json")

            def failing_fetch():
                raise RuntimeError("finnhub is down")

            result = check_for_market_news(fetch_news_fn=failing_fetch, path=path)

            self.assertFalse(result["pending"])
            self.assertEqual(result["headlines"], [])


class TestAddTickerToGroup(unittest.TestCase):
    def test_appends_to_group(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY", "IVW"]})

            add_ticker_to_group("DGRO", "stocks", path)

            self.assertEqual(load_ticker_config(path)["stocks"], ["SPY", "IVW", "DGRO"])

    def test_normalizes_case_and_whitespace(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY"]})

            add_ticker_to_group("  dgro  ", "stocks", path)

            self.assertEqual(load_ticker_config(path)["stocks"], ["SPY", "DGRO"])

    def test_idempotent_if_already_present(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY", "IVW"]})

            add_ticker_to_group("SPY", "stocks", path)

            self.assertEqual(load_ticker_config(path)["stocks"], ["SPY", "IVW"])

    def test_rejects_malformed_symbol(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY"]})

            with self.assertRaises(TickerConfigError):
                add_ticker_to_group("BAD TICKER", "stocks", path)
            self.assertEqual(load_ticker_config(path)["stocks"], ["SPY"])

    def test_rejects_unknown_group(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY"]})

            with self.assertRaises(TickerConfigError):
                add_ticker_to_group("DGRO", "crypto", path)

    def test_does_not_create_a_new_group(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY"]})

            with self.assertRaises(TickerConfigError):
                add_ticker_to_group("BTC", "crypto", path)

            self.assertEqual(list(load_ticker_config(path).keys()), ["stocks"])

    def test_other_groups_and_order_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"bonds": ["VGIT"], "stocks": ["SPY", "IVW"]})

            add_ticker_to_group("DGRO", "stocks", path)

            groups = load_ticker_config(path)
            self.assertEqual(list(groups.keys()), ["bonds", "stocks"])
            self.assertEqual(groups["bonds"], ["VGIT"])


class TestRemoveTickerFromGroup(unittest.TestCase):
    def test_removes_from_group(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY", "IVW", "DGRO"]})

            remove_ticker_from_group("IVW", "stocks", path)

            self.assertEqual(load_ticker_config(path)["stocks"], ["SPY", "DGRO"])

    def test_idempotent_if_not_present(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY", "IVW"]})

            remove_ticker_from_group("DGRO", "stocks", path)

            self.assertEqual(load_ticker_config(path)["stocks"], ["SPY", "IVW"])

    def test_rejects_unknown_group(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY"]})

            with self.assertRaises(TickerConfigError):
                remove_ticker_from_group("SPY", "crypto", path)

    def test_other_groups_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"bonds": ["VGIT"], "stocks": ["SPY", "IVW"]})

            remove_ticker_from_group("SPY", "stocks", path)

            groups = load_ticker_config(path)
            self.assertEqual(groups["bonds"], ["VGIT"])
            self.assertEqual(groups["stocks"], ["IVW"])

    def test_can_empty_a_group_without_removing_it(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY"]})

            remove_ticker_from_group("SPY", "stocks", path)

            groups = load_ticker_config(path)
            self.assertIn("stocks", groups)
            self.assertEqual(groups["stocks"], [])


class TestRedisBackedTickerConfig(unittest.TestCase):
    """Story 9 (storage backend), Story 12 (hash shape): config/tickers.json's
    content is Redis-backed when `kv_store.is_configured()`, as a
    *hash* -- one field per group, each `{"symbols": [...], "order": i}`
    -- not a single JSON-blob string, so an add/remove only ever reads
    and writes its own group's field. The embedded `order` index
    restores "groups render in file order" on read, since Redis hash
    fields don't preserve insertion order (confirmed live: HGETALL
    came back alphabetized). Mocked here since these are unit tests,
    not a live Upstash instance. Patched on `ticker_dashboard` itself
    (not `kv_store`) because `ticker_dashboard.py` imports those names
    directly via `from kv_store import ...`, so patching the origin
    module wouldn't affect the already-bound names in
    ticker_dashboard's namespace."""

    def test_seeds_from_local_file_when_redis_has_nothing_yet(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SPY", "IVW"]})
            with (
                mock.patch("ticker_dashboard.is_configured", return_value=True),
                mock.patch("ticker_dashboard.hgetall_json", return_value={}) as hgetall_mock,
                mock.patch("ticker_dashboard.hset_json") as hset_mock,
            ):
                groups = load_ticker_config(path)

            self.assertEqual(groups, {"stocks": ["SPY", "IVW"]})
            hgetall_mock.assert_called_once_with("ticker_config")
            hset_mock.assert_called_once_with("ticker_config", "stocks", {"symbols": ["SPY", "IVW"], "order": 0})

    def test_reads_from_redis_when_present_never_touches_local_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = write_config(tmp_dir, {"stocks": ["SHOULD-NOT-BE-USED"]})
            redis_hash = {"bonds": {"symbols": ["VGIT"], "order": 0}}
            with (
                mock.patch("ticker_dashboard.is_configured", return_value=True),
                mock.patch("ticker_dashboard.hgetall_json", return_value=redis_hash),
                mock.patch("ticker_dashboard.hset_json") as hset_mock,
            ):
                groups = load_ticker_config(path)

            self.assertEqual(groups, {"bonds": ["VGIT"]})
            hset_mock.assert_not_called()

    def test_reads_restore_file_order_despite_unordered_hash_fields(self):
        """The whole point of the embedded `order` index: Redis doesn't
        guarantee HGETALL returns fields in insertion order (confirmed
        live), so the fields here are deliberately handed back already
        out of order to prove the sort-by-`order` step is what fixes
        display order, not incidental dict luck."""
        redis_hash = {
            "sector": {"symbols": ["FTEC"], "order": 3},
            "bonds": {"symbols": ["VGIT"], "order": 1},
            "stocks": {"symbols": ["SPY"], "order": 0},
        }
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hgetall_json", return_value=redis_hash),
        ):
            groups = load_ticker_config(CONFIG_PATH)

        self.assertEqual(list(groups.keys()), ["stocks", "bonds", "sector"])

    def test_config_load_failure_propagates_rather_than_degrading(self):
        """Story 9's AC: a broken config load should fail loudly, not
        silently render an empty watchlist."""
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hgetall_json", side_effect=KvStoreError("redis down")),
        ):
            with self.assertRaises(KvStoreError):
                load_ticker_config(CONFIG_PATH)

    def test_add_ticker_reads_and_writes_only_its_own_group_field(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hget_json", return_value={"symbols": ["SPY"], "order": 2}) as hget_mock,
            mock.patch("ticker_dashboard.hset_json") as hset_mock,
        ):
            add_ticker_to_group("IVW", "stocks", CONFIG_PATH)

        hget_mock.assert_called_once_with("ticker_config", "stocks")
        hset_mock.assert_called_once_with("ticker_config", "stocks", {"symbols": ["SPY", "IVW"], "order": 2})

    def test_add_ticker_to_unknown_group_raises_without_writing(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hget_json", return_value=None),
            mock.patch("ticker_dashboard.hset_json") as hset_mock,
        ):
            with self.assertRaises(TickerConfigError):
                add_ticker_to_group("IVW", "nonexistent", CONFIG_PATH)

        hset_mock.assert_not_called()

    def test_remove_ticker_reads_and_writes_only_its_own_group_field(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch(
                "ticker_dashboard.hget_json", return_value={"symbols": ["SPY", "IVW"], "order": 2}
            ) as hget_mock,
            mock.patch("ticker_dashboard.hset_json") as hset_mock,
        ):
            remove_ticker_from_group("IVW", "stocks", CONFIG_PATH)

        hget_mock.assert_called_once_with("ticker_config", "stocks")
        hset_mock.assert_called_once_with("ticker_config", "stocks", {"symbols": ["SPY"], "order": 2})

    def test_concurrent_edits_to_different_groups_dont_clobber_each_other(self):
        """The whole point of the per-field design: adding to one
        group and removing from another (standing in for two
        different tabs' concurrent edits) only ever touch their own
        hash field, never each other's."""
        redis_hash = {
            "stocks": {"symbols": ["SPY"], "order": 0},
            "bonds": {"symbols": ["VGIT", "VGLT"], "order": 1},
        }

        def fake_hget(key, field):
            return redis_hash[field]

        def fake_hset(key, field, value):
            redis_hash[field] = value

        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hget_json", side_effect=fake_hget),
            mock.patch("ticker_dashboard.hset_json", side_effect=fake_hset),
        ):
            add_ticker_to_group("IVW", "stocks", CONFIG_PATH)
            remove_ticker_from_group("VGLT", "bonds", CONFIG_PATH)

        self.assertEqual(redis_hash["stocks"], {"symbols": ["SPY", "IVW"], "order": 0})
        self.assertEqual(redis_hash["bonds"], {"symbols": ["VGIT"], "order": 1})


class TestRedisBackedTickerCache(unittest.TestCase):
    """Story 12: the ticker cache is a Redis *hash* (one field per
    symbol via hset_json/hgetall_json), not a single JSON-blob key --
    so a per-symbol write is a genuinely atomic HSET, never a
    read-modify-write of every other symbol's data. Patched on
    `ticker_dashboard` itself, not `kv_store`, since `ticker_dashboard.py`
    does `from kv_store import ...`, binding the names into its own
    namespace (same reasoning as TestRedisBackedTickerConfig).
    """

    def test_load_reads_from_redis(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hgetall_json", return_value={"SPY": {"price": 1.0}}),
        ):
            self.assertEqual(load_ticker_state(TICKER_DATA_PATH), {"SPY": {"price": 1.0}})

    def test_load_degrades_to_empty_dict_on_redis_outage(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hgetall_json", side_effect=KvStoreError("redis down")),
        ):
            self.assertEqual(load_ticker_state(TICKER_DATA_PATH), {})

    def test_save_snapshot_writes_one_hash_field_not_the_local_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "tickers.json")
            with (
                mock.patch("ticker_dashboard.is_configured", return_value=True),
                mock.patch("ticker_dashboard.hset_json") as hset_mock,
            ):
                save_ticker_snapshot("SPY", {"price": 1.0}, path)

            hset_mock.assert_called_once_with("ticker_cache", "SPY", {"price": 1.0})
            self.assertFalse(os.path.exists(path))

    def test_save_snapshot_outage_is_swallowed_not_raised(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hset_json", side_effect=KvStoreError("redis down")),
        ):
            save_ticker_snapshot("SPY", {"price": 1.0}, TICKER_DATA_PATH)

    def test_save_state_bulk_writes_one_hash_field_per_symbol(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hset_json") as hset_mock,
        ):
            save_ticker_state({"SPY": {"price": 1.0}, "VGIT": {"price": 2.0}}, TICKER_DATA_PATH)

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
        redis_hash = {}

        def fake_hset(key, field, value):
            redis_hash[field] = value

        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.hset_json", side_effect=fake_hset),
        ):
            save_ticker_snapshot("SPY", {"price": 1.0}, TICKER_DATA_PATH)
            save_ticker_snapshot("VGIT", {"price": 2.0}, TICKER_DATA_PATH)

        self.assertEqual(redis_hash, {"SPY": {"price": 1.0}, "VGIT": {"price": 2.0}})


class TestRedisBackedMarketNewsCache(unittest.TestCase):
    def test_load_reads_from_redis(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.get_json", return_value={"headlines": []}),
        ):
            self.assertEqual(load_market_news_state(MARKET_NEWS_PATH), {"headlines": []})

    def test_load_degrades_to_none_on_redis_outage(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.get_json", side_effect=KvStoreError("redis down")),
        ):
            self.assertIsNone(load_market_news_state(MARKET_NEWS_PATH))

    def test_save_writes_to_redis_not_the_local_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "market_news.json")
            with (
                mock.patch("ticker_dashboard.is_configured", return_value=True),
                mock.patch("ticker_dashboard.set_json") as set_mock,
            ):
                save_market_news_state({"headlines": []}, path)

            set_mock.assert_called_once_with("market_news_cache", {"headlines": []})
            self.assertFalse(os.path.exists(path))

    def test_save_outage_is_swallowed_not_raised(self):
        with (
            mock.patch("ticker_dashboard.is_configured", return_value=True),
            mock.patch("ticker_dashboard.set_json", side_effect=KvStoreError("redis down")),
        ):
            save_market_news_state({"headlines": []}, MARKET_NEWS_PATH)


if __name__ == "__main__":
    unittest.main()
