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
    render_market_news_check_response,
    render_ticker_dashboard_page,
    render_ticker_group_check_response,
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
        "market_cap": 3500000.0,
        "pe_ratio": 34.2,
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
        pct_off_high=None, market_cap=None, pe_ratio=None, ma20=None, ma50=None, ma200=None,
        error=None, pending=True,
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
    """The full <tr>...</tr> markup for the row whose Ticker cell holds
    `symbol` -- the remove-ticker button lives in its own trailing
    cell, not the Ticker cell, so this matches on the plain `<td>` here."""
    cell_start = html.index(f"<td>{symbol}</td>")
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

        self.assertIn('<th class="sortable" data-sort-key="symbol">Ticker</th>', html)
        self.assertIn(">Change<", html)
        self.assertIn("52-Week Range", html)
        self.assertIn("% Off High", html)
        self.assertIn("Market Cap", html)
        self.assertIn(">P/E<", html)
        self.assertIn("20d MA", html)
        self.assertIn("50d MA", html)
        self.assertIn("200d MA", html)

    def test_renders_market_cap_formatted_with_suffix(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(market_cap=3500000.0)]}, NO_NEWS)

        self.assertIn("$3.50T", html)

    def test_missing_market_cap_renders_not_available(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(market_cap=None)]}, NO_NEWS)

        self.assertIn("n/a", html)

    def test_renders_pe_ratio(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(pe_ratio=34.2)]}, NO_NEWS)

        self.assertIn("34.2", html)

    def test_missing_pe_ratio_renders_not_available(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(pe_ratio=None)]}, NO_NEWS)

        self.assertIn("n/a", html)

    def test_remove_button_is_the_rows_trailing_cell(self):
        row = row_for(render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS), "SPY")

        self.assertTrue(row.rstrip().endswith("</tr>"))
        last_cell = row[row.rindex("<td>") :]
        self.assertIn("remove-ticker", last_cell)

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

    def test_renders_sort_data_attributes_on_rows(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(symbol="SPY", pct_off_high=5.8)]}, NO_NEWS)

        row = row_for(html, "SPY")
        self.assertIn('data-symbol="SPY"', row)
        self.assertIn('data-pct-off-high="5.8"', row)

    def test_pending_and_errored_rows_have_empty_pct_off_high_attribute(self):
        cards = [
            make_pending_card(symbol="PENDING"),
            make_card(symbol="ERRORED", pct_off_high=None, price=None, error="boom"),
        ]

        html = render_ticker_dashboard_page({"stocks": cards}, NO_NEWS)

        self.assertIn('data-pct-off-high=""', row_for(html, "PENDING"))
        self.assertIn('data-pct-off-high=""', row_for(html, "ERRORED"))

    def test_renders_sortable_headers_with_sort_keys(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertIn('<th class="sortable" data-sort-key="symbol">Ticker</th>', html)
        self.assertIn('<th class="num sortable" data-sort-key="pctOffHigh">% Off High</th>', html)

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

    def test_add_ticker_does_not_reload_the_page(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]}, NO_NEWS)

        self.assertNotIn("location.reload", html)
        self.assertIn("checkGroup", html)

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
        self.assertIn("/api/tickers/groups/", html)
        self.assertIn("hideCheckingIndicator", html)

    def test_renders_data_group_attribute_on_each_block(self):
        html = render_ticker_dashboard_page(
            {"stocks": [make_card()], "bonds": [make_card(symbol="VGIT")]}, NO_NEWS
        )

        self.assertIn('data-group="stocks"', html)
        self.assertIn('data-group="bonds"', html)

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

        self.assertIn("/api/market-news/check", html)
        self.assertIn("data.news_html", html)


class TestRenderTickerGroupCheckResponse(unittest.TestCase):
    def test_returns_group_html_for_the_same_cards(self):
        fragments = render_ticker_group_check_response("stocks", [make_card()])

        self.assertIn("group_html", fragments)
        self.assertIn("SPY", fragments["group_html"])
        self.assertIn("452.31", fragments["group_html"])
        self.assertIn('data-group="stocks"', fragments["group_html"])

    def test_does_not_include_other_groups_or_the_full_page_shell(self):
        fragments = render_ticker_group_check_response("stocks", [make_card()])

        self.assertNotIn("<!doctype html>", fragments["group_html"])
        self.assertNotIn("<html", fragments["group_html"])
        self.assertNotIn('id="ticker-groups"', fragments["group_html"])


class TestRenderMarketNewsCheckResponse(unittest.TestCase):
    def test_returns_news_html(self):
        fragments = render_market_news_check_response(SAMPLE_NEWS)

        self.assertIn("news_html", fragments)
        self.assertIn("Stocks rally on rate-cut hopes", fragments["news_html"])

    def test_does_not_include_the_full_page_shell(self):
        fragments = render_market_news_check_response(NO_NEWS)

        self.assertNotIn("<!doctype html>", fragments["news_html"])


if __name__ == "__main__":
    unittest.main()
