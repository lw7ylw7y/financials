"""Gemini API call for the Ticker Dashboard's AI valuation section: one
batched call reasoning across the whole watchlist at once -- a
discount/fair/overpriced read for each group plus one for every ticker
(ETFs and individual stocks) -- rather than one call per ticker. Deliberate,
given the free tier's confirmed 20-requests/day quota for
gemini-3.8-flash (a single wide watchlist could otherwise burn through
that from ticker valuation alone, before the indicator digest's own
calls on the same model/quota); `ticker_dashboard.py`'s
`MIN_VALUATION_INTERVAL` throttle exists for the same reason.

Mirrors src/digest/interpret.py's conventions (same model, same
structured-output-via-pydantic-schema approach, same exception-per-call
contract) but lives under src/web/ since it's Ticker-Dashboard-specific
-- v1 never touches it.
"""

import logging
import os
from typing import Literal

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from gemini_models import fallback_models


logger = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"
# No retries: the free tier's 20-requests/day cap counts every attempt,
# including failed ones, so retrying against a sustained backend outage
# (the observed real-world failure mode) burns through the day's whole
# quota for zero successes rather than helping with a one-off blip.
MAX_ATTEMPTS = 1

_VERDICT_RANK = {"discount": 0, "fair": 1, "overpriced": 2}

SYSTEM_PROMPT = """You are an equity valuation assistant for a long-term, \
buy-and-hold individual investor reviewing their own watchlist. This is not \
personalized financial advice -- say so once, briefly, then move directly \
into the analysis.

You will be given the investor's ticker watchlist, grouped by category. \
Every group except "individual" holds one or more ETFs (a "bonds" group has \
no equity P/E at all); "individual" holds individual company stocks.

For each GROUP, judge whether it looks like a discount, fair value, or \
overpriced overall, based on the data given (trailing P/E where available, \
percent off its 52-week high). A "bonds" group has no P/E -- judge it \
primarily by where price sits in its 52-week range and say so explicitly \
rather than inventing a P/E-based read. Then write ONE short paragraph \
ranking the groups from most attractively priced to least, explaining why.

Then, for EVERY SINGLE ticker listed in ANY group below -- ETFs and \
individual stocks alike, all of them, with no exceptions or omissions -- give \
a one-word verdict of exactly "discount", "fair", or "overpriced", plus a \
one-sentence justification citing the SPECIFIC numbers you were given. For an \
individual stock, use its P/E versus its sector-peer benchmark P/E (if \
given), its PEG, and its growth/margin/debt figures; a low P/E paired with \
shrinking revenue, negative EPS growth, or high debt is a value trap, not a \
discount -- call that out explicitly rather than defaulting to "discount" \
whenever P/E is low. For an ETF there is usually no P/E, so judge it by how \
far it sits below its 52-week high together with its recent price returns \
(13-week, 26-week and year-to-date, in percent), relative to the other funds \
in its own group and to the market as a whole. Use the returns to tell apart \
a fund sitting at its high after a long, steep run (stretched) from one at its \
high after a flat stretch, and a fund that has fallen because it is weak from \
one that is merely resting after a big gain. Returns describe what has \
already happened, not what will happen, and price position alone is not a \
valuation -- say plainly when that is all you have. The tickers list in your response MUST have exactly one entry per \
ticker shown anywhere below -- never leave it empty and never skip a ticker.

You may also be given a macro backdrop: the investor's separately generated \
read of the economy. Use it as context (for example, whether stretched \
prices are at odds with a weakening economy, or cheap ones with a stable \
one), but let each ticker's own numbers decide its verdict, and don't just \
restate the backdrop.

Be concrete and numeric, not vague.
"""


class GroupVerdict(BaseModel):
    group: str
    verdict: Literal["discount", "fair", "overpriced"]
    reasoning: str


class TickerVerdict(BaseModel):
    symbol: str
    verdict: Literal["discount", "fair", "overpriced"]
    reasoning: str


class ValuationResponse(BaseModel):
    overview: str
    groups: list[GroupVerdict]
    tickers: list[TickerVerdict]


class TickerValuationError(Exception):
    """Raised for any failure to obtain a usable AI valuation."""


def _fmt(card: dict, key: str, suffix: str = "") -> str:
    value = card.get(key)
    return "n/a" if value is None else f"{value}{suffix}"


def _fmt_returns(card: dict) -> str:
    return (
        f"return_13w={_fmt(card, 'return_13w', '%')}, "
        f"return_26w={_fmt(card, 'return_26w', '%')}, "
        f"return_ytd={_fmt(card, 'return_ytd', '%')}"
    )


def _format_group_section(group_name: str, cards: list[dict]) -> str:
    lines = [f"### Group: {group_name}"]
    for c in cards:
        lines.append(
            f"- {c['symbol']}: price=${_fmt(c, 'price')}, "
            f"pct_off_52wk_high={_fmt(c, 'pct_off_high', '%')}, "
            f"{_fmt_returns(c)}, "
            f"pe_ratio={_fmt(c, 'pe_ratio')}"
        )
    return "\n".join(lines)


def _format_individual_section(cards: list[dict]) -> str:
    lines = ["### Group: individual (per-ticker detail)"]
    for c in cards:
        lines.append(
            f"- {c['symbol']}: price=${_fmt(c, 'price')}, "
            f"pct_off_52wk_high={_fmt(c, 'pct_off_high', '%')}, "
            f"{_fmt_returns(c)}, "
            f"pe_ratio={_fmt(c, 'pe_ratio')}, peg_ratio={_fmt(c, 'peg_ratio')}, "
            f"revenue_growth={_fmt(c, 'revenue_growth', '%')}, "
            f"eps_growth={_fmt(c, 'eps_growth', '%')}, roe={_fmt(c, 'roe', '%')}, "
            f"net_margin={_fmt(c, 'net_margin', '%')}, "
            f"debt_to_equity={_fmt(c, 'debt_to_equity')}, "
            f"dividend_yield={_fmt(c, 'dividend_yield', '%')}, "
            f"sector_pe_ratio={_fmt(c, 'sector_pe_ratio')} (benchmark: {_fmt(c, 'sector_symbol')})"
        )
    return "\n".join(lines)


def _format_macro_context(macro_context: dict) -> str:
    return (
        "### Macro backdrop (the investor's own economic read)\n"
        f"Direction: {macro_context.get('directional_read')}\n"
        f"Summary: {macro_context.get('summary')}"
    )


def build_user_prompt(
    cards_by_group: dict[str, list[dict]], macro_context: dict | None = None
) -> str:
    """`cards_by_group`: `{group_name: [card, ...]}`, each card at least
    `{"symbol", "price", "pct_off_high", "pe_ratio"}`, plus (for
    "individual") the growth/quality/sector-benchmark fields
    `ticker_dashboard._build_card` also attaches. A symbol with no
    cached data yet is expected to already be filtered out by the
    caller (`ticker_dashboard._build_valuation_cards`), not included
    here as a placeholder. `macro_context`, if given, is the saved
    indicator-digest take (`{"summary", "directional_read"}`),
    prepended as background.
    """
    sections = []
    if macro_context and macro_context.get("summary"):
        sections.append(_format_macro_context(macro_context))
    for group_name, cards in cards_by_group.items():
        if group_name == "individual":
            sections.append(_format_individual_section(cards))
        else:
            sections.append(_format_group_section(group_name, cards))
    return "\n\n".join(sections)


def _group_by_verdict(
    cards_by_group: dict[str, list[dict]], ticker_verdicts: list[TickerVerdict]
) -> dict[str, list[dict]]:
    """Buckets `ticker_verdicts` under "discount"/"fair"/"overpriced"
    headings, in `cards_by_group`' own order (group by group, then
    ticker by ticker) within each bucket -- not whatever order the AI
    happened to return them in, so the rendered page doesn't reshuffle
    from one refresh to the next for reasons unrelated to an actual
    verdict change. Each entry is `{"symbol", "group", "reasoning"}`. A
    ticker the AI omitted despite the system prompt's instruction not
    to is logged and simply absent from every bucket, not treated as a
    fatal error.
    """
    verdict_by_symbol = {tv.symbol: tv for tv in ticker_verdicts}
    buckets: dict[str, list[dict]] = {"discount": [], "fair": [], "overpriced": []}
    for group_name, cards in cards_by_group.items():
        for card in cards:
            verdict = verdict_by_symbol.get(card["symbol"])
            if verdict is None:
                logger.warning("AI valuation omitted ticker symbol=%s", card["symbol"])
                continue
            buckets[verdict.verdict].append(
                {"symbol": verdict.symbol, "group": group_name, "reasoning": verdict.reasoning}
            )
    return buckets


def _parse(text: str | None, source: str) -> ValuationResponse:
    if not text:
        raise TickerValuationError(f"{source} returned no text content")
    try:
        return ValuationResponse.model_validate_json(text)
    except ValidationError as e:
        raise TickerValuationError(f"could not parse {source} response: {e}") from e


def _valuation_with_gemini(prompt: str, client: genai.Client | None, model: str = MODEL) -> ValuationResponse:
    try:
        client = client or genai.Client(
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=MAX_ATTEMPTS)
            )
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=ValuationResponse,
            ),
        )
    except errors.APIError as e:
        raise TickerValuationError(f"Gemini API call failed: {e}") from e
    except ValueError as e:
        # genai.Client() raises a bare ValueError (not an APIError) when no
        # API key is configured -- still a "the AI call is unusable" case.
        raise TickerValuationError(f"Gemini client not configured: {e}") from e
    return _parse(response.text, "Gemini")


def _run_with_fallbacks(prompt: str, client: genai.Client | None) -> ValuationResponse:
    """Gemini, then each fallback Gemini model in turn; the first
    usable result wins. An explicitly injected `client` is used alone."""
    sources = [(MODEL, lambda: _valuation_with_gemini(prompt, client))]
    if client is None:
        sources += [
            (model, lambda model=model: _valuation_with_gemini(prompt, None, model))
            for model in fallback_models()
        ]

    failures = []
    for name, attempt in sources:
        try:
            return attempt()
        except TickerValuationError as e:
            logger.warning("%s valuation failed: %s", name, e)
            failures.append(f"{name}: {e}")
    raise TickerValuationError("; ".join(failures))


def interpret_ticker_valuation(
    cards_by_group: dict[str, list[dict]],
    client: genai.Client | None = None,
    macro_context: dict | None = None,
) -> dict:
    """Return {"overview": str, "groups": [{"group", "verdict",
    "reasoning"}, ...], "tickers_by_verdict": {"discount": [...],
    "fair": [...], "overpriced": [...]}} -- `groups` sorted
    discount-first/overpriced-last regardless of the order Gemini
    returned them in, since "sort by discount level" is a rendering
    guarantee this function makes, not something worth trusting an LLM
    to do consistently call to call. `tickers_by_verdict` covers every
    ticker in every group (ETFs and individual stocks); each entry is
    `{"symbol", "group", "reasoning"}`. `macro_context` is the saved
    indicator-digest take, given to the model as background.

    Tries Gemini first, then each fallback Gemini model in turn
    if each fails for any reason. An explicitly injected `client` is
    used alone, with no fallback.

    Raises TickerValuationError when every source fails (an API
    failure, including a quota/rate-limit 429, missing credentials, or
    an unusable response), or when there is no data to reason about at
    all (every group empty).
    """
    if not any(cards_by_group.values()):
        raise TickerValuationError("no ticker data available to evaluate")

    prompt = build_user_prompt(cards_by_group, macro_context)

    parsed = _run_with_fallbacks(prompt, client)

    groups = sorted(
        [g.model_dump() for g in parsed.groups],
        key=lambda g: _VERDICT_RANK.get(g["verdict"], len(_VERDICT_RANK)),
    )

    return {
        "overview": parsed.overview,
        "groups": groups,
        "tickers_by_verdict": _group_by_verdict(cards_by_group, parsed.tickers),
    }
