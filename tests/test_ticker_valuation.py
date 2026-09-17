import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

from google.genai import errors
from ticker_valuation import (
    TickerValuationError,
    build_user_prompt,
    interpret_ticker_valuation,
)

CARDS_BY_GROUP = {
    "stocks": [
        {"symbol": "SPY", "price": 762.6, "pct_off_high": 2.15, "pe_ratio": 24.78},
    ],
    "bonds": [
        {"symbol": "VGIT", "price": 57.4, "pct_off_high": 5.53, "pe_ratio": None},
    ],
    "individual": [
        {
            "symbol": "AMD", "price": 545.09, "pct_off_high": 6.78, "pe_ratio": 130.96,
            "peg_ratio": 2.81, "revenue_growth": 39.54, "eps_growth": 124.33, "roe": 10.07,
            "net_margin": 15.58, "debt_to_equity": 0.0511, "dividend_yield": None,
            "sector_pe_ratio": 32.15, "sector_symbol": "FTEC",
        },
        {
            "symbol": "RELY", "price": 21.73, "pct_off_high": 20.92, "pe_ratio": 15.44,
            "peg_ratio": 0.74, "revenue_growth": 23.79, "eps_growth": 2130.02, "roe": 32.97,
            "net_margin": 16.85, "debt_to_equity": 0.1817, "dividend_yield": None,
            "sector_pe_ratio": 15.91, "sector_symbol": "FNCL",
        },
    ],
}


def fake_client(text=None, side_effect=None):
    client = Mock()
    if side_effect is not None:
        client.models.generate_content.side_effect = side_effect
    else:
        client.models.generate_content.return_value = SimpleNamespace(text=text)
    return client


def make_api_error():
    return errors.ClientError(400, {"error": {"message": "bad request"}})


def make_quota_error():
    return errors.ClientError(
        429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}}
    )


def valuation_response_json(groups=None, individual_tickers=None):
    return json.dumps(
        {
            "overview": "Bonds look cheapest, stocks priciest.",
            "groups": groups
            if groups is not None
            else [
                {"group": "stocks", "verdict": "overpriced", "reasoning": "near highs"},
                {"group": "bonds", "verdict": "discount", "reasoning": "off highs"},
            ],
            "individual_tickers": individual_tickers
            if individual_tickers is not None
            else [
                {"symbol": "AMD", "verdict": "overpriced", "reasoning": "P/E far above sector"},
                {"symbol": "RELY", "verdict": "discount", "reasoning": "P/E below sector, strong growth"},
            ],
        }
    )


class TestBuildUserPrompt(unittest.TestCase):
    def test_includes_a_section_per_group_and_individual_detail(self):
        prompt = build_user_prompt(CARDS_BY_GROUP)

        self.assertIn("### Group: stocks", prompt)
        self.assertIn("SPY: price=$762.6", prompt)
        self.assertIn("pe_ratio=24.78", prompt)
        self.assertIn("### Group: bonds", prompt)
        self.assertIn("VGIT: price=$57.4", prompt)
        self.assertIn("pe_ratio=n/a", prompt)
        self.assertIn("### Group: individual (per-ticker detail)", prompt)
        self.assertIn("AMD:", prompt)
        self.assertIn("sector_pe_ratio=32.15 (benchmark: FTEC)", prompt)


class TestInterpretTickerValuation(unittest.TestCase):
    def test_parses_overview_groups_and_individual_buckets(self):
        client = fake_client(text=valuation_response_json())

        result = interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

        self.assertEqual(result["overview"], "Bonds look cheapest, stocks priciest.")
        self.assertEqual(
            result["individual_by_verdict"],
            {
                "discount": [{"symbol": "RELY", "reasoning": "P/E below sector, strong growth"}],
                "fair": [],
                "overpriced": [{"symbol": "AMD", "reasoning": "P/E far above sector"}],
            },
        )

    def test_groups_are_sorted_discount_first_overpriced_last(self):
        # Gemini returned "stocks" (overpriced) before "bonds" (discount) --
        # the function must still sort discount-first regardless.
        client = fake_client(
            text=valuation_response_json(
                groups=[
                    {"group": "stocks", "verdict": "overpriced", "reasoning": "near highs"},
                    {"group": "sector", "verdict": "fair", "reasoning": "mixed"},
                    {"group": "bonds", "verdict": "discount", "reasoning": "off highs"},
                ]
            )
        )

        result = interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

        self.assertEqual([g["group"] for g in result["groups"]], ["bonds", "sector", "stocks"])

    def test_preserves_original_watchlist_order_within_each_bucket(self):
        # Both AMD and RELY come back "discount" -- the bucket order must
        # follow CARDS_BY_GROUP["individual"]'s order (AMD, RELY), not
        # whatever order the AI happened to list them in.
        client = fake_client(
            text=valuation_response_json(
                individual_tickers=[
                    {"symbol": "RELY", "verdict": "discount", "reasoning": "cheap"},
                    {"symbol": "AMD", "verdict": "discount", "reasoning": "also cheap"},
                ]
            )
        )

        result = interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

        self.assertEqual(
            [t["symbol"] for t in result["individual_by_verdict"]["discount"]], ["AMD", "RELY"]
        )

    def test_ticker_omitted_by_ai_is_simply_absent_not_fatal(self):
        client = fake_client(
            text=valuation_response_json(
                individual_tickers=[
                    {"symbol": "AMD", "verdict": "overpriced", "reasoning": "expensive"},
                    # RELY omitted despite the system prompt's instruction not to.
                ]
            )
        )

        result = interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

        all_symbols = sum((v for v in result["individual_by_verdict"].values()), [])
        self.assertEqual([t["symbol"] for t in all_symbols], ["AMD"])

    def test_raises_on_no_data_at_all(self):
        empty = {"stocks": [], "bonds": [], "individual": []}

        with self.assertRaises(TickerValuationError):
            interpret_ticker_valuation(empty, client=fake_client(text="unused"))

    def test_raises_on_api_error(self):
        client = fake_client(side_effect=make_api_error())

        with self.assertRaises(TickerValuationError):
            interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

    def test_raises_on_quota_exhausted(self):
        client = fake_client(side_effect=make_quota_error())

        with self.assertRaises(TickerValuationError):
            interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

    def test_raises_on_malformed_json(self):
        client = fake_client(text="not json")

        with self.assertRaises(TickerValuationError):
            interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

    def test_raises_on_empty_response_text(self):
        client = fake_client(text=None)

        with self.assertRaises(TickerValuationError):
            interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

    def test_raises_on_invalid_verdict(self):
        text = valuation_response_json(
            groups=[{"group": "stocks", "verdict": "cheap!!", "reasoning": "x"}]
        )
        client = fake_client(text=text)

        with self.assertRaises(TickerValuationError):
            interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

    def test_raises_when_no_credentials_configured(self):
        with patch(
            "ticker_valuation.genai.Client",
            side_effect=ValueError("No API key was provided."),
        ):
            with self.assertRaises(TickerValuationError):
                interpret_ticker_valuation(CARDS_BY_GROUP, client=None)


if __name__ == "__main__":
    unittest.main()
