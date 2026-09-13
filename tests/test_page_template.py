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
        "week52_low": 400.0,
        "week52_high": 480.0,
        "ma20": 448.5,
        "ma200": 430.2,
        "news": [{"headline": "Fund flows steady", "url": "https://example.com/a", "datetime": 1}],
        "error": None,
    }
    card.update(overrides)
    return card


class TestRenderTickerDashboardPage(unittest.TestCase):
    def test_renders_card_fields(self):
        html = render_ticker_dashboard_page({"stocks": [make_card()]})

        self.assertIn("SPY", html)
        self.assertIn("452.31", html)
        self.assertIn("400.00", html)
        self.assertIn("480.00", html)
        self.assertIn("448.50", html)
        self.assertIn("430.20", html)
        self.assertIn("Fund flows steady", html)
        self.assertIn("https://example.com/a", html)

    def test_group_header_derived_from_config_key(self):
        html = render_ticker_dashboard_page({"sector_and_individual": [make_card()]})

        self.assertIn("Sector And Individual", html)

    def test_new_group_key_renders_with_no_code_change(self):
        html = render_ticker_dashboard_page({"crypto": [make_card(symbol="BTC")]})

        self.assertIn("Crypto", html)
        self.assertIn("BTC", html)

    def test_groups_render_in_file_order(self):
        html = render_ticker_dashboard_page(
            {"bonds": [make_card(symbol="VGIT")], "stocks": [make_card(symbol="SPY")]}
        )

        self.assertLess(html.index("Bonds"), html.index("Stocks"))

    def test_errored_card_shows_error_state_without_crashing(self):
        error_card = make_card(
            price=None,
            week52_low=None,
            week52_high=None,
            ma20=None,
            ma200=None,
            news=[],
            error="no quote data for SPY",
        )

        html = render_ticker_dashboard_page({"stocks": [error_card]})

        self.assertIn("ticker-card-error", html)
        self.assertIn("Unable to load data.", html)

    def test_one_card_erroring_does_not_affect_sibling_card(self):
        error_card = make_card(
            symbol="BADSYM",
            price=None,
            week52_low=None,
            week52_high=None,
            ma20=None,
            ma200=None,
            news=[],
            error="no quote data for BADSYM",
        )
        ok_card = make_card(symbol="SPY")

        html = render_ticker_dashboard_page({"stocks": [error_card, ok_card]})

        self.assertIn("Unable to load data.", html)
        self.assertIn("452.31", html)

    def test_missing_ma200_renders_not_available(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(ma200=None)]})

        self.assertIn("n/a", html)

    def test_no_news_renders_placeholder(self):
        html = render_ticker_dashboard_page({"stocks": [make_card(news=[])]})

        self.assertIn("No recent news.", html)

    def test_html_escapes_headline(self):
        html = render_ticker_dashboard_page(
            {"stocks": [make_card(news=[{"headline": "<script>alert(1)</script>", "url": "https://example.com", "datetime": 1}])]}
        )

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
