"""Static mapping of the 8 v1 indicators to their FRED series and category.

Per Section 4 of v1_technical_design.md. `fred_release_id` is only needed
for Story 3 (release calendar); most entries are left as None until that
story maps them — Story 1 doesn't depend on this field.
"""

INDICATORS = {
    "initial_jobless_claims": {
        "name": "Initial Jobless Claims",
        "category": "leading",
        "fred_series_id": "ICSA",
        "fred_release_id": "13",
    },
    "yield_curve_spread": {
        "name": "10yr-2yr Treasury Spread",
        "category": "leading",
        "fred_series_id": "T10Y2Y",
        "fred_release_id": None,
    },
    "building_permits": {
        "name": "Building Permits",
        "category": "leading",
        "fred_series_id": "PERMIT",
        "fred_release_id": None,
    },
    "nonfarm_payrolls": {
        "name": "Nonfarm Payrolls",
        "category": "coincident",
        "fred_series_id": "PAYEMS",
        "fred_release_id": None,
    },
    "industrial_production": {
        "name": "Industrial Production",
        "category": "coincident",
        "fred_series_id": "INDPRO",
        "fred_release_id": None,
    },
    "fed_funds_rate": {
        "name": "Fed Funds Rate",
        "category": "lagging",
        "fred_series_id": "FEDFUNDS",
        "fred_release_id": None,
    },
    "cpi": {
        "name": "CPI",
        "category": "lagging",
        "fred_series_id": "CPIAUCSL",
        "fred_release_id": None,
    },
    "unemployment_rate": {
        "name": "Unemployment Rate",
        "category": "lagging",
        "fred_series_id": "UNRATE",
        "fred_release_id": None,
    },
}
