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
):
    sys.path.insert(0, _p)

from email_template import render_html, render_subject, render_text

TABLE = {
    "leading": [
        {
            "name": "Building Permits",
            "latest_value": 1433.0,
            "latest_date": "2026-07-01",
            "prior_value": 1374.0,
            "sparkline_cid": "spark-building_permits",
        }
    ],
    "coincident": [
        {
            "name": "Nonfarm Payrolls",
            "latest_value": 159075.0,
            "latest_date": "2026-08-01",
            "prior_value": 158913.0,
            "sparkline_cid": "spark-nonfarm_payrolls",
        }
    ],
    "lagging": [
        {
            "name": "CPI",
            "latest_value": 334.131,
            "latest_date": "2026-08-01",
            "prior_value": None,
            "sparkline_cid": "spark-cpi",
        }
    ],
}
COUNTDOWN = {
    "entries": [
        {"key": "cpi", "name": "CPI", "next_release_date": "2026-09-11", "days_until": 0},
        {"key": "payrolls", "name": "Nonfarm Payrolls", "next_release_date": "2026-10-02", "days_until": 21},
    ],
    "soonest": {"key": "cpi", "name": "CPI", "next_release_date": "2026-09-11", "days_until": 0},
}


class TestRenderSubject(unittest.TestCase):
    def test_names_all_updated_indicators(self):
        subject = render_subject(["CPI", "Unemployment Rate"])

        self.assertIn("2 update(s)", subject)
        self.assertIn("CPI", subject)
        self.assertIn("Unemployment Rate", subject)


class TestRenderText(unittest.TestCase):
    def test_includes_ai_section_and_disclaimer_when_present(self):
        ai_result = {"summary": "Modest changes.", "directional_read": "neutral"}

        text = render_text(TABLE, COUNTDOWN, ai_result)

        self.assertIn("Modest changes.", text)
        self.assertIn("Overall directional read: neutral", text)
        self.assertIn("not personalized financial advice", text)

    def test_omits_ai_section_when_none(self):
        text = render_text(TABLE, COUNTDOWN, None)

        self.assertNotIn("Overall directional read", text)
        self.assertNotIn("not personalized financial advice", text)

    def test_includes_all_categories_and_countdown(self):
        text = render_text(TABLE, COUNTDOWN, None)

        self.assertIn("Building Permits", text)
        self.assertIn("Nonfarm Payrolls", text)
        self.assertIn("CPI", text)
        self.assertIn("Next up: CPI", text)

    def test_no_countdown_section_when_no_entries(self):
        empty_countdown = {"entries": [], "soonest": None}

        text = render_text(TABLE, empty_countdown, None)

        self.assertNotIn("Next releases", text)


class TestRenderHtml(unittest.TestCase):
    def test_embeds_sparkline_images_by_cid(self):
        html = render_html(TABLE, COUNTDOWN, None)

        self.assertIn('src="cid:spark-cpi"', html)
        self.assertIn('src="cid:spark-nonfarm_payrolls"', html)
        self.assertIn('src="cid:spark-building_permits"', html)

    def test_missing_sparkline_cid_falls_back_gracefully(self):
        table_without_cid = {
            "leading": [],
            "coincident": [],
            "lagging": [
                {"name": "CPI", "latest_value": 334.131, "latest_date": "2026-08-01", "prior_value": None}
            ],
        }

        html = render_html(table_without_cid, {"entries": [], "soonest": None}, None)

        self.assertNotIn("cid:None", html)

    def test_is_well_formed_html_document(self):
        html = render_html(TABLE, COUNTDOWN, None)

        self.assertTrue(html.lower().startswith("<!doctype html>"))
        self.assertIn("</html>", html.lower())

    def test_escapes_indicator_names_and_ai_summary(self):
        malicious_table = {
            "leading": [
                {
                    "name": "<script>alert(1)</script>",
                    "latest_value": 1.0,
                    "latest_date": "2026-08-01",
                    "prior_value": None,
                }
            ],
            "coincident": [],
            "lagging": [],
        }
        ai_result = {"summary": "<b>injected</b>", "directional_read": "neutral"}

        html = render_html(malicious_table, {"entries": [], "soonest": None}, ai_result)

        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<b>injected</b>", html)

    def test_directional_read_colors_are_distinct(self):
        bullish_html = render_html(TABLE, COUNTDOWN, {"summary": "x", "directional_read": "bullish"})
        bearish_html = render_html(TABLE, COUNTDOWN, {"summary": "x", "directional_read": "bearish"})

        self.assertIn("Bullish", bullish_html)
        self.assertIn("Bearish", bearish_html)
        self.assertNotEqual(bullish_html, bearish_html)

    def test_soonest_release_is_marked_next_up(self):
        html = render_html(TABLE, COUNTDOWN, None)

        self.assertIn("Next up", html)


if __name__ == "__main__":
    unittest.main()
