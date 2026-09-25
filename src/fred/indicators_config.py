"""Static mapping of the 8 tracked indicators to their FRED series and category.

`fred_release_id` identifies the FRED *release* (e.g. "Employment
Situation") each series is published under, used to fetch the next
scheduled release date. Series that update continuously rather than on
a discrete release schedule (the yield curve spread) have no release ID
and are skipped for that lookup.
"""

INDICATORS = {
    "initial_jobless_claims": {
        "name": "Initial Jobless Claims",
        "category": "leading",
        "fred_series_id": "ICSA",
        "fred_release_id": "180",  # Unemployment Insurance Weekly Claims Report
    },
    "yield_curve_spread": {
        "name": "10yr-2yr Treasury Spread",
        "category": "leading",
        "fred_series_id": "T10Y2Y",
        "fred_release_id": None,  # updated daily, no discrete release
    },
    "building_permits": {
        "name": "Building Permits",
        "category": "leading",
        "fred_series_id": "PERMIT",
        "fred_release_id": "27",  # New Residential Construction
    },
    "nonfarm_payrolls": {
        "name": "Nonfarm Payrolls",
        "category": "coincident",
        "fred_series_id": "PAYEMS",
        "fred_release_id": "50",  # Employment Situation
    },
    "industrial_production": {
        "name": "Industrial Production",
        "category": "coincident",
        "fred_series_id": "INDPRO",
        "fred_release_id": "13",  # G.17 Industrial Production and Capacity Utilization
    },
    "fed_funds_rate": {
        "name": "Fed Funds Rate",
        "category": "lagging",
        # The daily effective rate (DFF), not the monthly average
        # (FEDFUNDS): the monthly series only publishes once a month is
        # over and blends a rate change with the days before it, so a
        # change stayed invisible for weeks.
        "fred_series_id": "DFF",
        # No discrete release: a daily series, like the yield curve
        # spread. (H.15 publishes on nearly every business day since it
        # bundles many rate series, so a countdown against it is never
        # meaningful.)
        "fred_release_id": None,
    },
    "cpi": {
        "name": "CPI",
        "category": "lagging",
        "fred_series_id": "CPIAUCSL",
        "fred_release_id": "10",  # Consumer Price Index
    },
    "unemployment_rate": {
        "name": "Unemployment Rate",
        "category": "lagging",
        "fred_series_id": "UNRATE",
        "fred_release_id": "50",  # Employment Situation
    },
}
