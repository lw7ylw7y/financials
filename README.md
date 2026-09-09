# Investment Dashboard

See `investment_dashboard_requirements.md`, `v1_user_stories.md`, `v1_technical_design.md`, and `v1_task_breakdown.md` for the full spec.

## Story 1 — Indicator Data Ingestion (prototype)

`src/main.py` fetches the latest value for all 8 v1 indicators from FRED,
tags each with its category, skips values already seen, and logs
(without halting) any per-indicator fetch failure. Results are persisted
to `data/indicators.json`.

### Run it

```
pip install -r requirements.txt
export FRED_API_KEY=your_key_here   # https://fred.stlouisfed.org/docs/api/api_key.html
python3 src/main.py
```

### Test it

```
python3 -m unittest discover -s tests -v
```

No network calls in tests — `fetch_fred.requests.get` is mocked, and
`run_ingestion` is exercised with a fake `fetch_fn`.
