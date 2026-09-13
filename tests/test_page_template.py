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

from page_template import render_check_response, render_indicator_digest_page

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


if __name__ == "__main__":
    unittest.main()
