import json
import os
import sys
import tempfile
import unittest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

from ticker_dashboard import CONFIG_PATH, build_ticker_cards, load_ticker_config


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

    def test_default_config_path_matches_initial_watchlist_draft(self):
        groups = load_ticker_config(CONFIG_PATH)

        self.assertEqual(
            groups,
            {
                "stocks": ["SPY", "IVW", "DGRO"],
                "bonds": ["VGIT", "VGLT"],
                "international": ["VIGI", "VYMI", "EMB"],
                "sector": ["FTEC"],
                "individual": ["MSFT", "RELY"],
            },
        )


class TestBuildTickerCards(unittest.TestCase):
    def test_successful_ticker_computes_price_range_and_moving_averages(self):
        closes = [float(i) for i in range(1, 251)]  # 250 closes: 1.0 .. 250.0

        def fake_quote(symbol):
            return {"price": 452.31}

        def fake_week52(symbol):
            return {"low": 400.0, "high": 480.0}

        def fake_closes(symbol):
            return closes

        def fake_news(symbol):
            return [{"headline": "Beats estimates", "url": "https://example.com/a", "datetime": 1}]

        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=fake_quote,
            fetch_week52_fn=fake_week52,
            fetch_closes_fn=fake_closes,
            fetch_news_fn=fake_news,
        )

        card = cards["stocks"][0]
        self.assertEqual(card["symbol"], "SPY")
        self.assertEqual(card["group"], "stocks")
        self.assertEqual(card["price"], 452.31)
        self.assertEqual(card["week52_low"], 400.0)
        self.assertEqual(card["week52_high"], 480.0)
        self.assertEqual(card["ma20"], sum(closes[-20:]) / 20)
        self.assertEqual(card["ma200"], sum(closes[-200:]) / 200)
        self.assertEqual(len(card["news"]), 1)
        self.assertIsNone(card["error"])

    def test_fewer_than_200_candles_leaves_ma200_none(self):
        closes = [float(i) for i in range(1, 51)]  # only 50 closes

        cards = build_ticker_cards(
            config={"stocks": ["NEWCO"]},
            fetch_quote_fn=lambda s: {"price": 10.0},
            fetch_week52_fn=lambda s: {"low": 1.0, "high": 50.0},
            fetch_closes_fn=lambda s: closes,
            fetch_news_fn=lambda s: [],
        )

        card = cards["stocks"][0]
        self.assertEqual(card["ma20"], sum(closes[-20:]) / 20)
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
            fetch_week52_fn=lambda s: {"low": 1.0, "high": 3.0},
            fetch_closes_fn=lambda s: [1.0, 2.0, 3.0],
            fetch_news_fn=lambda s: [],
        )

        spy, badsym, ivw = cards["stocks"]
        self.assertIsNone(spy["error"])
        self.assertIsNone(ivw["error"])
        self.assertIsNotNone(badsym["error"])
        self.assertIn("BADSYM", badsym["error"])
        self.assertIsNone(badsym["price"])
        self.assertEqual(badsym["news"], [])

    def test_week52_failure_also_errors_the_card(self):
        def fake_week52(symbol):
            raise RuntimeError("no 52-week range for SPY")

        cards = build_ticker_cards(
            config={"stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 100.0},
            fetch_week52_fn=fake_week52,
            fetch_closes_fn=lambda s: [1.0, 2.0, 3.0],
            fetch_news_fn=lambda s: [],
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
            fetch_week52_fn=lambda s: {"low": 1.0, "high": 3.0},
            fetch_closes_fn=fake_closes,
            fetch_news_fn=lambda s: [],
        )

        card = cards["stocks"][0]
        self.assertIsNotNone(card["error"])
        self.assertIsNone(card["ma20"])

    def test_groups_and_order_match_config(self):
        cards = build_ticker_cards(
            config={"bonds": ["VGIT", "VGLT"], "stocks": ["SPY"]},
            fetch_quote_fn=lambda s: {"price": 1.0},
            fetch_week52_fn=lambda s: {"low": 1.0, "high": 2.0},
            fetch_closes_fn=lambda s: [1.0, 2.0],
            fetch_news_fn=lambda s: [],
        )

        self.assertEqual(list(cards.keys()), ["bonds", "stocks"])
        self.assertEqual([c["symbol"] for c in cards["bonds"]], ["VGIT", "VGLT"])
        self.assertEqual([c["symbol"] for c in cards["stocks"]], ["SPY"])

    def test_defaults_to_loading_config_from_disk(self):
        cards = build_ticker_cards(
            fetch_quote_fn=lambda s: {"price": 1.0},
            fetch_week52_fn=lambda s: {"low": 1.0, "high": 2.0},
            fetch_closes_fn=lambda s: [1.0, 2.0],
            fetch_news_fn=lambda s: [],
        )

        self.assertEqual(list(cards.keys()), ["stocks", "bonds", "international", "sector", "individual"])
        self.assertEqual([c["symbol"] for c in cards["stocks"]], ["SPY", "IVW", "DGRO"])


if __name__ == "__main__":
    unittest.main()
