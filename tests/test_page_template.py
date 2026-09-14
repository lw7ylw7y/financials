import os
import sys
import unittest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
    os.path.join(_SRC, "web"),
):
    sys.path.insert(0, _p)

from page_template import (
    render_check_response,
    render_indicator_digest_page,
    render_ticker_check_response,
    render_ticker_dashboard_page,
)

TABLE = {
    "leading": [],
    "coincident": [
        {
            "name": "Nonfarm Payrolls",
            "latest_value": 159075.0,
            "latest_date": "2026-08-01",
            "prior_value": 158000.0,
            "sparkline_cid": "spark-nonfarm_payrolls",
            "sparkline_values": [158000.0, 159075.0],
        }
    ],
    "lagging": [],
}

COUNTDOWN = {
    "entries": [
        {"key": "cpi", "name": "CPI", "next_release_date": "2026-09-20", "days_until": 3}
    ],
    "soonest": {"key": "cpi", "name": "CPI", "next_release_date": "2026-09-20", "days_until": 3},
}


def base_data(**overrides):
    data = {
        "table": TABLE,
        "countdown": COUNTDOWN,
        "ai_result": {"summary": "Payrolls ticked up.", "directional_read": "bullish"},
    }
    data.update(overrides)
    return data


class TestRenderIndicatorDigestPage(unittest.TestCase):
    def test_renders_ai_summary_and_directional_label(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("Payrolls ticked up.", html)
        self.assertIn("Bullish", html)

    def test_renders_disclaimer_when_ai_present(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("not personalized financial advice", html)

    def test_renders_table_rows(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("Nonfarm Payrolls", html)
        self.assertIn("159075", html)
        self.assertIn("prior: 158000", html)

    def test_renders_countdown(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn("CPI", html)
        self.assertIn("in 3 day(s)", html)

    def test_no_ai_response_on_file_renders_placeholder_not_crash(self):
        html = render_indicator_digest_page(base_data(ai_result=None))

        self.assertIn("No AI interpretation on file yet.", html)

    def test_html_escapes_indicator_names(self):
        table = {"leading": [], "coincident": [], "lagging": [
            {
                "name": "<script>alert(1)</script>",
                "latest_value": 1.0,
                "latest_date": "2026-09-01",
                "prior_value": None,
                "sparkline_cid": None,
                "sparkline_values": [1.0],
            }
        ]}
        html = render_indicator_digest_page(base_data(table=table))

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_renders_checking_indicator_and_script_hides_it_on_settle(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn('id="checking-indicator"', html)
        self.assertIn("Checking for updates", html)
        self.assertIn("hideCheckingIndicator", html)

    def test_renders_sparkline_svg_for_row_with_history(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn('<svg class="sparkline"', html)
        self.assertIn("<polyline", html)

    def test_renders_dot_only_sparkline_for_single_point_history(self):
        table = {"leading": [], "coincident": [], "lagging": [
            {
                "name": "CPI",
                "latest_value": 334.1,
                "latest_date": "2026-09-01",
                "prior_value": None,
                "sparkline_cid": None,
                "sparkline_values": [334.1],
            }
        ]}
        html = render_indicator_digest_page(base_data(table=table))

        self.assertIn('<svg class="sparkline"', html)
        self.assertNotIn("<polyline", html)
        self.assertIn("<circle", html)

    def test_renders_nav_linking_to_ticker_dashboard(self):
        html = render_indicator_digest_page(base_data())

        self.assertIn('class="site-nav"', html)
        self.assertIn('href="/tickers"', html)
        self.assertIn('href="/" class="active"', html)


class TestRenderCheckResponse(unittest.TestCase):
    def test_includes_table_and_countdown(self):
        content = {"table": TABLE, "countdown": COUNTDOWN, "ai_result": None}

        fragments = render_check_response(content)

        self.assertIn("Nonfarm Payrolls", fragments["table_html"])
        self.assertIn("CPI", fragments["countdown_html"])
        self.assertIsNone(fragments["ai_html"])

    def test_ai_html_present_when_ai_result_given(self):
        content = {
            "table": TABLE,
            "countdown": COUNTDOWN,
            "ai_result": {"summary": "Fresh read.", "directional_read": "bullish"},
        }

        fragments = render_check_response(content)

        self.assertIsNotNone(fragments["ai_html"])
        self.assertIn("Fresh read.", fragments["ai_html"])


def make_card(**overrides):
    card = {
        "symbol": "SPY",
        "group": "stocks",
        "price": 452.31,
        "change": 3.81,
        "change_percent": 0.85,
        "week52_low": 400.0,
        "week52_high": 480.0,
        "pct_off_high": 5.8,
        "ma20": 448.5,
        "ma50": 440.0,
        "ma200": 430.2,
        "error": None,
        "pending": False,
    }
    card.update(overrides)
    return card


def make_pending_card(**overrides):
    return make_card(
        price=None, change=None, change_percent=None, week52_low=None, week52_high=None,
        pct_off_high=None, ma20=None, ma50=None, ma200=None, error=None, pending=True,
        **overrides,
    )


NO_NEWS = {"headlines": [], "pending": False}
PENDING_NEWS = {"headlines": [], "pending": True}
SAMPLE_NEWS = {
    "headlines": [
        {"headline": "Stocks rally on rate-cut hopes", "url": "https://example.com/a", "source": "CNBC", "datetime": 1},
        {"headline": "Tech leads Monday gains", "url": "https://example.com/b", "source": "Reuters", "datetime": 2},
    ],
    "pending": False,
}


def row_for(html: str, symbol: str) -> str:
    """The full <tr>...</tr> markup for the row whose Ticker cell
    starts with `symbol` -- a space (not </td>) follows the symbol now
    that each row also carries a remove-ticker button in that cell."""
    cell_start = html.index(f"<td>{symbol} ")
    row_start = html.rfind("<tr", 0, cell_start)
    row_end = html.index("</tr>", cell_start) + len("</tr>")
    return html[row_start:row_end]


class TestRenderTickerDashboardPage(unittest.TestCase):
    def test_renders_row_fields_as_a_table(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("<table", html)
        self.assertIn("SPY", html)
        self.assertIn("452.31", html)
        self.assertIn("400.00", html)
        self.assertIn("480.00", html)
        self.assertIn("448.50", html)
        self.assertIn("440.00", html)
        self.assertIn("430.20", html)

    def test_renders_column_headers(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("<th>Ticker</th>", html)
        self.assertIn(">Change<", html)
        self.assertIn("52-Week Range", html)
        self.assertIn("% Off High", html)
        self.assertIn("20d MA", html)
        self.assertIn("50d MA", html)
        self.assertIn("200d MA", html)

    def test_no_per_ticker_news_list(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertNotIn("market-news-list", html)

    def test_renders_nav_linking_to_indicator_digest(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn('class="site-nav"', html)
        self.assertIn('href="/" ', html)
        self.assertIn('href="/tickers" class="active"', html)

    def test_group_header_derived_from_config_key(self):
        html = render_ticker_dashboard_page({"sector_and_individual": [make_card()]}, NO_NEWS)

        self.assertIn("Sector And Individual", html)

    def test_new_group_key_renders_with_no_code_change(self):
        html = render_ticker_dashboard_page({"crypto": [make_card(symbol="BTC")]}, NO_NEWS)

        self.assertIn("Crypto", html)
        self.assertIn("BTC", html)

    def test_groups_render_in_file_order(self):
        html = render_ticker_dashboard_page(
            {"bonds": [make_card(symbol="VGIT")], "stocks": [make_card(symbol="SPY")]}, NO_NEWS
        )

        self.assertLess(html.index("Bonds"), html.index("Stocks"))

    def test_errored_row_shows_error_state_without_crashing(self):
        error_card = make_card(
            price=None,
            change=None,
            change_percent=None,
            week52_low=None,
            week52_high=None,
            pct_off_high=None,
            ma20=None,
            ma50=None,
            ma200=None,
            error="no quote data for SPY",
        )

        html = render_ticker_dashboard_page({"stocks": [error_card]}, NO_NEWS)

        self.assertIn("Unable to load data.", html)

    def test_one_row_erroring_does_not_affect_sibling_row(self):
        error_card = make_card(
            symbol="BADSYM",
            price=None,
            change=None,
            change_percent=None,
            week52_low=None,
            week52_high=None,
            pct_off_high=None,
            ma20=None,
            ma50=None,
            ma200=None,
            error="no quote data for BADSYM",
        )
        ok_card = make_card(symbol="SPY")

        html = render_ticker_dashboard_page({"stocks": [error_card, ok_card]}, NO_NEWS)

        self.assertIn("Unable to load data.", html)
        self.assertIn("452.31", html)

    def test_missing_ma200_renders_not_available(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(ma200=None)]}, NO_NEWS)

        self.assertIn("n/a", html)

    def test_price_above_ma_colored_as_up(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(price=500.0, ma20=450.0)]}, NO_NEWS)

        self.assertIn('class="ma-delta up"', html)

    def test_price_below_ma_colored_as_down(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(price=400.0, ma20=450.0)]}, NO_NEWS)

        self.assertIn('class="ma-delta down"', html)

    def test_positive_change_colored_up(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(change=3.81, change_percent=0.85)]}, NO_NEWS)

        self.assertIn('class="ma-delta up"', html)
        self.assertIn("+3.81", html)
        self.assertIn("0.85%", html)

    def test_negative_change_colored_down(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(change=-2.08, change_percent=-0.27)]}, NO_NEWS)

        self.assertIn('class="ma-delta down"', html)
        self.assertIn("-2.08", html)

    def test_missing_change_renders_not_available(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(change=None, change_percent=None)]}, NO_NEWS)

        self.assertIn("n/a", html)

    def test_renders_pct_off_high(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(pct_off_high=5.8)]}, NO_NEWS)

        self.assertIn("5.8%", html)

    def test_missing_pct_off_high_renders_not_available(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(pct_off_high=None)]}, NO_NEWS)

        self.assertIn("n/a", html)

    def test_highlight_count_scales_with_group_size(self):
        # ceil(group_size / 4): 3 tickers -> 1, 8 -> 2, 10 -> 3.
        for group_size, expected_highlighted in ((3, 1), (8, 2), (10, 3)):
            with self.subTest(group_size=group_size):
                cards = [
                    make_card(symbol=f"S{i}", pct_off_high=float(group_size - i))
                    for i in range(group_size)
                ]  # S0 has the highest pct_off_high, S1 next, etc.

                html = render_ticker_dashboard_page({"stocks": cards}, NO_NEWS)

                self.assertEqual(html.count('class="row-highlight"'), expected_highlighted)
                for i in range(expected_highlighted):
                    symbol = f"S{i}"
                    row = row_for(html, symbol)
                    self.assertIn('class="row-highlight"', row, f"{symbol} should be highlighted in a group of {group_size}")

    def test_small_group_still_highlights_at_least_one(self):
        cards = [make_card(symbol="A", pct_off_high=1.0), make_card(symbol="B", pct_off_high=2.0)]

        html = render_ticker_dashboard_page({"stocks": cards}, NO_NEWS)

        self.assertEqual(html.count('class="row-highlight"'), 1)
        self.assertIn('class="row-highlight"', row_for(html, "B"))

    def test_pending_and_errored_rows_are_never_highlighted(self):
        cards = [
            make_pending_card(symbol="PENDING"),
            make_card(symbol="ERRORED", pct_off_high=None, price=None, error="boom"),
            make_card(symbol="OK", pct_off_high=1.0),
        ]

        html = render_ticker_dashboard_page({"stocks": cards}, NO_NEWS)

        self.assertEqual(html.count('class="row-highlight"'), 1)
        self.assertIn('class="row-highlight"', row_for(html, "OK"))

    def test_ranking_is_per_group_not_global(self):
        # "stocks" has 8 tickers with generally higher pct_off_high than
        # "bonds" -- bonds' own top pick must still get highlighted even
        # though it's far below stocks' cutoff, since ranking is per-group.
        stocks = [
            make_card(symbol=s, pct_off_high=v)
            for s, v in [("A", 90), ("B", 80), ("C", 70), ("D", 60), ("E", 50), ("F", 40), ("G", 30), ("H", 20)]
        ]
        bonds = [make_card(symbol=s, pct_off_high=v) for s, v in [("X", 5.0), ("Y", 2.0)]]

        html = render_ticker_dashboard_page({"stocks": stocks, "bonds": bonds}, NO_NEWS)

        self.assertIn('class="row-highlight"', row_for(html, "X"))
        self.assertNotIn("row-highlight", row_for(html, "Y"))
        # stocks (8 tickers) highlights 2 (A, B), not down through H
        self.assertNotIn("row-highlight", row_for(html, "H"))

    def test_renders_range_bar_gradient_and_marker(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn('<svg class="range-bar"', html)
        self.assertIn("linearGradient", html)
        self.assertIn("<circle", html)

    def test_html_escapes_ticker_symbol(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(symbol="<script>alert(1)</script>")]}, NO_NEWS)

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_renders_remove_button_on_every_row_shape(self):
        cards = [make_card(symbol="SPY"), make_pending_card(symbol="NEWTICKER"), make_card(symbol="BADSYM", error="boom")]

        html = render_ticker_dashboard_page({"stocks": cards}, NO_NEWS)

        for symbol in ("SPY", "NEWTICKER", "BADSYM"):
            row = row_for(html, symbol)
            self.assertIn('class="remove-ticker"', row)
            self.assertIn(f'data-symbol="{symbol}"', row)
            self.assertIn('data-group="stocks"', row)

    def test_renders_add_ticker_form_per_group(self):
        html = render_ticker_dashboard_page(
            {"stocks": [make_card()], "bonds": [make_card(symbol="VGIT")]}, NO_NEWS
        )

        self.assertEqual(html.count('class="add-ticker-form"'), 2)
        self.assertIn('data-group="stocks"', html)
        self.assertIn('data-group="bonds"', html)

    def test_editor_actions_wired_up_in_script(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("/api/tickers/remove", html)
        self.assertIn("/api/tickers/add", html)
        self.assertIn("remove-ticker", html)
        self.assertIn("add-ticker-form", html)

    def test_pending_row_shows_loading_placeholder(self):
        html = render_ticker_dashboard_page({"stocks": [make_pending_card()]}, NO_NEWS)

        self.assertIn("Loading&hellip;", html)
        self.assertNotIn("Unable to load data.", html)

    def test_pending_row_does_not_affect_sibling_row(self):
        html = render_ticker_dashboard_page(
            {"stocks": [make_pending_card(symbol="NEWTICKER"), make_card(symbol="SPY")]}, NO_NEWS
        )

        self.assertIn("Loading&hellip;", html)
        self.assertIn("452.31", html)

    def test_renders_ticker_groups_wrapper_and_checking_indicator(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn('id="ticker-groups"', html)
        self.assertIn('id="checking-indicator"', html)
        self.assertIn("Checking for updates", html)
        self.assertIn("/api/check-tickers", html)
        self.assertIn("hideCheckingIndicator", html)

    def test_renders_market_news_headlines_above_ticker_groups(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, SAMPLE_NEWS)

        self.assertIn('id="market-news"', html)
        self.assertIn("Stocks rally on rate-cut hopes", html)
        self.assertIn("https://example.com/a", html)
        self.assertIn("CNBC", html)
        self.assertLess(html.index('id="market-news"'), html.index('id="ticker-groups"'))

    def test_market_news_pending_shows_loading_placeholder(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, PENDING_NEWS)

        self.assertIn("Loading market news", html)

    def test_market_news_empty_shows_unavailable_message(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("Market news unavailable.", html)

    def test_market_news_html_escapes_headline(self):
        news = {
            "headlines": [{"headline": "<script>alert(1)</script>", "url": "https://example.com", "source": "X", "datetime": 1}],
            "pending": False,
        }
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, news)

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_market_news_patched_by_script(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("data.news_html", html)


class TestRenderTickerCheckResponse(unittest.TestCase):
    def test_returns_groups_html_for_the_same_cards(self):
        fragments = render_ticker_check_response({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn("groups_html", fragments)
        self.assertIn("SPY", fragments["groups_html"])
        self.assertIn("452.31", fragments["groups_html"])

    def test_returns_news_html(self):
        fragments = render_ticker_check_response({"stocks": [make_card()]}, SAMPLE_NEWS)

        self.assertIn("news_html", fragments)
        self.assertIn("Stocks rally on rate-cut hopes", fragments["news_html"])

    def test_does_not_include_the_full_page_shell(self):
        fragments = render_ticker_check_response({"stocks": [make_card()]}, NO_NEWS)

        self.assertNotIn("<!doctype html>", fragments["groups_html"])
        self.assertNotIn("<html", fragments["groups_html"])
        self.assertNotIn("<!doctype html>", fragments["news_html"])


if __name__ == "__main__":
    unittest.main()
