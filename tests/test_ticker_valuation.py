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
from gemini_models import DEFAULT_FALLBACK_MODELS
from ticker_valuation import (
    MODEL,
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


def valuation_response_json(groups=None, tickers=None):
    return json.dumps(
        {
            "overview": "Bonds look cheapest, stocks priciest.",
            "groups": groups
            if groups is not None
            else [
                {"group": "stocks", "verdict": "overpriced", "reasoning": "near highs"},
                {"group": "bonds", "verdict": "discount", "reasoning": "off highs"},
            ],
            "tickers": tickers
            if tickers is not None
            else [
                {"symbol": "SPY", "verdict": "fair", "reasoning": "close to its high"},
                {"symbol": "VGIT", "verdict": "discount", "reasoning": "off its high"},
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


class TestPriceReturnsInPrompt(unittest.TestCase):
    def test_returns_are_shown_for_etfs_and_individual_stocks(self):
        cards = {
            "sector": [{"symbol": "FTEC", "price": 301.2, "pct_off_high": 0.31,
                        "return_13w": 8.2, "return_26w": 39.4, "return_ytd": 33.5}],
            "individual": [{"symbol": "AMD", "price": 545.0, "pct_off_high": 6.8,
                            "return_13w": -3.0, "return_26w": 10.0, "return_ytd": 20.0}],
        }

        prompt = build_user_prompt(cards)

        self.assertIn("FTEC: price=$301.2, pct_off_52wk_high=0.31%, return_13w=8.2%, return_26w=39.4%, return_ytd=33.5%", prompt)
        self.assertIn("return_13w=-3.0%, return_26w=10.0%, return_ytd=20.0%", prompt)

    def test_missing_returns_show_as_n_a(self):
        prompt = build_user_prompt(CARDS_BY_GROUP)

        self.assertIn("return_13w=n/a, return_26w=n/a, return_ytd=n/a", prompt)


class TestMacroContext(unittest.TestCase):
    MACRO = {"summary": "Growth is steady and inflation is cooling.", "directional_read": "neutral"}

    def test_macro_backdrop_is_prepended_when_given(self):
        prompt = build_user_prompt(CARDS_BY_GROUP, self.MACRO)

        self.assertTrue(prompt.startswith("### Macro backdrop"))
        self.assertIn("Direction: neutral", prompt)
        self.assertIn("Growth is steady and inflation is cooling.", prompt)
        self.assertLess(prompt.index("Macro backdrop"), prompt.index("### Group: stocks"))

    def test_no_macro_section_without_context(self):
        self.assertNotIn("Macro backdrop", build_user_prompt(CARDS_BY_GROUP))
        self.assertNotIn("Macro backdrop", build_user_prompt(CARDS_BY_GROUP, {"summary": None}))

    def test_interpret_passes_the_context_into_the_prompt(self):
        client = fake_client(text=valuation_response_json())

        interpret_ticker_valuation(CARDS_BY_GROUP, client=client, macro_context=self.MACRO)

        contents = client.models.generate_content.call_args.kwargs["contents"]
        self.assertIn("Growth is steady", contents)


class TestInterpretTickerValuation(unittest.TestCase):
    def test_parses_overview_groups_and_ticker_buckets_across_every_group(self):
        client = fake_client(text=valuation_response_json())

        result = interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

        self.assertEqual(result["overview"], "Bonds look cheapest, stocks priciest.")
        self.assertEqual(
            result["tickers_by_verdict"],
            {
                "discount": [
                    {"symbol": "VGIT", "group": "bonds", "reasoning": "off its high"},
                    {"symbol": "RELY", "group": "individual", "reasoning": "P/E below sector, strong growth"},
                ],
                "fair": [{"symbol": "SPY", "group": "stocks", "reasoning": "close to its high"}],
                "overpriced": [{"symbol": "AMD", "group": "individual", "reasoning": "P/E far above sector"}],
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
        # SPY, VGIT, AMD and RELY all come back "discount" -- the bucket
        # order must follow CARDS_BY_GROUP (stocks, bonds, individual: AMD,
        # RELY), not whatever order the AI happened to list them in.
        client = fake_client(
            text=valuation_response_json(
                tickers=[
                    {"symbol": "RELY", "verdict": "discount", "reasoning": "cheap"},
                    {"symbol": "AMD", "verdict": "discount", "reasoning": "also cheap"},
                    {"symbol": "VGIT", "verdict": "discount", "reasoning": "cheap too"},
                    {"symbol": "SPY", "verdict": "discount", "reasoning": "cheap as well"},
                ]
            )
        )

        result = interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

        self.assertEqual(
            [t["symbol"] for t in result["tickers_by_verdict"]["discount"]],
            ["SPY", "VGIT", "AMD", "RELY"],
        )

    def test_ticker_omitted_by_ai_is_simply_absent_not_fatal(self):
        client = fake_client(
            text=valuation_response_json(
                tickers=[
                    {"symbol": "AMD", "verdict": "overpriced", "reasoning": "expensive"},
                    # every other ticker omitted despite the system prompt's instruction not to.
                ]
            )
        )

        result = interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

        all_symbols = sum((v for v in result["tickers_by_verdict"].values()), [])
        self.assertEqual([t["symbol"] for t in all_symbols], ["AMD"])

    def test_etfs_are_included_with_their_group(self):
        client = fake_client(text=valuation_response_json())

        result = interpret_ticker_valuation(CARDS_BY_GROUP, client=client)

        by_symbol = {
            t["symbol"]: (verdict, t["group"])
            for verdict, tickers in result["tickers_by_verdict"].items()
            for t in tickers
        }
        self.assertEqual(by_symbol["VGIT"], ("discount", "bonds"))
        self.assertEqual(by_symbol["SPY"], ("fair", "stocks"))

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


class TestGeminiModelFallbackChain(unittest.TestCase):
    def called_models(self, client):
        return [c.kwargs["model"] for c in client.models.generate_content.call_args_list]

    def test_each_fallback_model_is_tried_in_order_until_one_succeeds(self):
        client = Mock()
        client.models.generate_content.side_effect = [
            make_api_error(),
            make_api_error(),
            make_api_error(),
            SimpleNamespace(text=valuation_response_json()),
        ]
        with patch("ticker_valuation.genai.Client", return_value=client):
            interpret_ticker_valuation(CARDS_BY_GROUP)
        self.assertEqual(self.called_models(client), [MODEL, *DEFAULT_FALLBACK_MODELS[:3]])

    def test_later_models_are_not_called_once_one_succeeds(self):
        client = fake_client(text=valuation_response_json())
        with patch("ticker_valuation.genai.Client", return_value=client):
            interpret_ticker_valuation(CARDS_BY_GROUP)
        client.models.generate_content.assert_called_once()

    def test_injected_client_never_falls_back(self):
        client = fake_client(side_effect=make_api_error())
        with self.assertRaises(TickerValuationError):
            interpret_ticker_valuation(CARDS_BY_GROUP, client=client)
        client.models.generate_content.assert_called_once()

    def test_raises_after_trying_every_model_and_names_each_in_the_error(self):
        client = fake_client(side_effect=make_api_error())
        with patch("ticker_valuation.genai.Client", return_value=client):
            with self.assertRaises(TickerValuationError) as raised:
                interpret_ticker_valuation(CARDS_BY_GROUP)
        self.assertEqual(self.called_models(client), [MODEL, *DEFAULT_FALLBACK_MODELS])
        for model in (MODEL, *DEFAULT_FALLBACK_MODELS):
            self.assertIn(model, str(raised.exception))

    @patch.dict(os.environ, {"GEMINI_FALLBACK_MODELS": "model-a, model-b"})
    def test_fallback_models_are_configurable(self):
        client = fake_client(side_effect=make_api_error())
        with patch("ticker_valuation.genai.Client", return_value=client):
            with self.assertRaises(TickerValuationError):
                interpret_ticker_valuation(CARDS_BY_GROUP)
        self.assertEqual(self.called_models(client), [MODEL, "model-a", "model-b"])


if __name__ == "__main__":
    unittest.main()
