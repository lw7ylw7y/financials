"""Gemini API call for the Ticker Dashboard's AI valuation section: one
batched call reasoning across the whole watchlist at once -- a
discount/fair/overpriced read for each ETF group plus one for every
individual stock -- rather than one call per ticker. Deliberate,
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
from typing import Literal

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

MODEL = "gemini-3.8-flash"
MAX_ATTEMPTS = 4  # 1 initial call + 3 retries, per HttpRetryOptions.attempts

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

Then, for EVERY SINGLE ticker listed under the "individual" group below -- \
all of them, with no exceptions or omissions -- give a one-word verdict of \
exactly "discount", "fair", or "overpriced", plus a one-sentence \
justification citing the SPECIFIC numbers you were given: its P/E versus \
its sector-peer benchmark P/E (if given), its PEG, and its growth/margin/debt \
figures. A low P/E paired with shrinking revenue, negative EPS growth, or \
high debt is a value trap, not a discount -- call that out explicitly \
rather than defaulting to "discount" whenever P/E is low. The \
individual_tickers list in your response MUST have exactly one entry per \
ticker shown in the individual group -- never leave it empty and never \
skip a ticker.

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
    individual_tickers: list[TickerVerdict]


class TickerValuationError(Exception):
    """Raised for any failure to obtain a usable AI valuation."""


def _fmt(card: dict, key: str, suffix: str = "") -> str:
    value = card.get(key)
    return "n/a" if value is None else f"{value}{suffix}"


def _format_group_section(group_name: str, cards: list[dict]) -> str:
    lines = [f"### Group: {group_name}"]
    for c in cards:
        lines.append(
            f"- {c['symbol']}: price=${_fmt(c, 'price')}, "
            f"pct_off_52wk_high={_fmt(c, 'pct_off_high', '%')}, "
            f"pe_ratio={_fmt(c, 'pe_ratio')}"
        )
    return "\n".join(lines)


def _format_individual_section(cards: list[dict]) -> str:
    lines = ["### Group: individual (per-ticker detail)"]
    for c in cards:
        lines.append(
            f"- {c['symbol']}: price=${_fmt(c, 'price')}, "
            f"pct_off_52wk_high={_fmt(c, 'pct_off_high', '%')}, "
            f"pe_ratio={_fmt(c, 'pe_ratio')}, peg_ratio={_fmt(c, 'peg_ratio')}, "
            f"revenue_growth={_fmt(c, 'revenue_growth', '%')}, "
            f"eps_growth={_fmt(c, 'eps_growth', '%')}, roe={_fmt(c, 'roe', '%')}, "
            f"net_margin={_fmt(c, 'net_margin', '%')}, "
            f"debt_to_equity={_fmt(c, 'debt_to_equity')}, "
            f"dividend_yield={_fmt(c, 'dividend_yield', '%')}, "
            f"sector_pe_ratio={_fmt(c, 'sector_pe_ratio')} (benchmark: {_fmt(c, 'sector_symbol')})"
        )
    return "\n".join(lines)


def build_user_prompt(cards_by_group: dict[str, list[dict]]) -> str:
    """`cards_by_group`: `{group_name: [card, ...]}`, each card at least
    `{"symbol", "price", "pct_off_high", "pe_ratio"}`, plus (for
    "individual") the growth/quality/sector-benchmark fields
    `ticker_dashboard._build_card` also attaches. A symbol with no
    cached data yet is expected to already be filtered out by the
    caller (`ticker_dashboard._build_valuation_cards`), not included
    here as a placeholder.
    """
    sections = []
    for group_name, cards in cards_by_group.items():
        if group_name == "individual":
            sections.append(_format_individual_section(cards))
        else:
            sections.append(_format_group_section(group_name, cards))
    return "\n\n".join(sections)


def _group_individual_by_verdict(
    individual_cards: list[dict], ticker_verdicts: list[TickerVerdict]
) -> dict[str, list[dict]]:
    """Buckets `ticker_verdicts` under "discount"/"fair"/"overpriced"
    headings, in `individual_cards`' own order within each bucket --
    not whatever order the AI happened to return them in, so the
    rendered page doesn't reshuffle from one refresh to the next for
    reasons unrelated to an actual verdict change. A ticker the AI
    omitted despite the system prompt's instruction not to is logged
    and simply absent from every bucket, not treated as a fatal error.
    """
    verdict_by_symbol = {tv.symbol: tv for tv in ticker_verdicts}
    buckets: dict[str, list[dict]] = {"discount": [], "fair": [], "overpriced": []}
    for card in individual_cards:
        verdict = verdict_by_symbol.get(card["symbol"])
        if verdict is None:
            logger.warning("AI valuation omitted ticker symbol=%s", card["symbol"])
            continue
        buckets[verdict.verdict].append({"symbol": verdict.symbol, "reasoning": verdict.reasoning})
    return buckets


def interpret_ticker_valuation(cards_by_group: dict[str, list[dict]], client: genai.Client | None = None) -> dict:
    """Return {"overview": str, "groups": [{"group", "verdict",
    "reasoning"}, ...], "individual_by_verdict": {"discount": [...],
    "fair": [...], "overpriced": [...]}} -- `groups` sorted
    discount-first/overpriced-last regardless of the order Gemini
    returned them in, since "sort by discount level" is a rendering
    guarantee this function makes, not something worth trusting an LLM
    to do consistently call to call. Each `individual_by_verdict` entry
    is `{"symbol", "reasoning"}`.

    Raises TickerValuationError on any API failure (including a
    quota/rate-limit 429 -- the free tier's real failure mode in
    practice), missing credentials, an unusable response, or no data
    to reason about at all (every group empty).
    """
    if not any(cards_by_group.values()):
        raise TickerValuationError("no ticker data available to evaluate")

    prompt = build_user_prompt(cards_by_group)

    try:
        client = client or genai.Client(
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=MAX_ATTEMPTS)
            )
        )
        response = client.models.generate_content(
            model=MODEL,
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

    if not response.text:
        raise TickerValuationError("Gemini returned no text content")

    try:
        parsed = ValuationResponse.model_validate_json(response.text)
    except ValidationError as e:
        raise TickerValuationError(f"could not parse AI response: {e}") from e

    groups = sorted(
        [g.model_dump() for g in parsed.groups],
        key=lambda g: _VERDICT_RANK.get(g["verdict"], len(_VERDICT_RANK)),
    )

    return {
        "overview": parsed.overview,
        "groups": groups,
        "individual_by_verdict": _group_individual_by_verdict(
            cards_by_group.get("individual", []), parsed.individual_tickers
        ),
    }
