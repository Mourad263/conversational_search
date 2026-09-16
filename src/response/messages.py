"""Sprint 4 deterministic response wording. No LLM, no free-form text
generation, no template framework -- every function returns a fixed
string, optionally parameterized only by already-resolved, real values
(never an invented product fact). src/scenario/orchestrator.py composes
these into a turn's supplementary `message` field.

Sprint 6 Task 3A addition: `build_assistant_message()` is a SEPARATE,
always-populated conversational reply (the new `assistant_message` API
field) -- it does not replace or read `message`, which keeps its existing
meaning (a supplementary note, often null) unchanged. Bilingual (EN/AR),
selected by a single Arabic-character check on the CURRENT user message
(is_arabic()) -- no language-detection library, no LLM call. Every string
is a fixed template; nothing here ever inserts a product/brand/category
name, a price, or a count, so there is nothing here to hallucinate.
"""

from __future__ import annotations

from src.ingestion.text_normalize import is_arabic


def off_topic_refocus(customer_service_tone: bool = False) -> str:
    if customer_service_tone:
        return "No problem -- I can help you search for products. What are you looking for?"
    return "I can help you search for products in our catalog -- what are you looking for?"


def recommendation_needs_clarification() -> str:
    return "Tell me what product, category, or brand you're looking for and I can help."


def recommendation_relaxation_exhausted() -> str:
    return (
        "I've already widened the price range a few times. Try giving me a new budget "
        "or a different filter."
    )


def rapid_repeat_blocked() -> str:
    return "You've sent that same request a few times in a row -- let me know if you'd like something different."


def zero_result(likely_out_of_catalog: bool) -> str:
    # Deliberately never a categorical claim ("we don't carry that") -- the
    # deterministic likely_out_of_catalog signal is corroborating evidence,
    # not proof (Sprint 4 design pass).
    if likely_out_of_catalog:
        return "I couldn't find that in our current catalog."
    return "I couldn't find any matching products for that search."


def customer_service_acknowledgment() -> str:
    return "Sorry for the trouble -- here's what I found:"


def turn_cap_suggestion() -> str:
    return "This conversation has gotten long -- you can reset the search if you'd like to start fresh."


def recommendation_band_note() -> str:
    return "I widened the price range slightly to show you more matching options."


def understanding_failed() -> str:
    return "Something went wrong understanding that -- please try again."


def unresolved_exclusion_note(excluded: str) -> str:
    # Sprint 6 Finding B: an explicit free-from request with no matching
    # catalog category must never be silently ignored -- this is the
    # user-visible admission that it wasn't applied.
    return f"Note: I couldn't filter out \"{excluded}\" specifically, so these results may include it."


# ---------------------------------------------------------------------
# Task 3A: deterministic conversational response layer.
# ---------------------------------------------------------------------

GREETING_EN = "Hello! How can I help you?"
GREETING_AR = "أهلاً! أقدر أساعدك إزاي؟"


def greeting(arabic: bool = False) -> str:
    """Reusable initial greeting for a future UI/API integration -- not
    wired into any endpoint by this task."""
    return GREETING_AR if arabic else GREETING_EN


# (english, arabic) -- one or two clear phrases per state, no alternates,
# no randomness: deterministic output, easy to test.
_ASSISTANT_MESSAGES: dict[str, tuple[str, str]] = {
    "search_success": (
        "Sure, I found these products for you.",
        "أكيد، لقيت لك المنتجات دي.",
    ),
    "search_and_recommendations": (
        "Sure, I found these products for you, and I also found some options you may like.",
        "أكيد، لقيت لك المنتجات دي وكمان شوية اختيارات ممكن تعجبك.",
    ),
    "recommendation_success": (
        "Here are some other options you may like.",
        "دي شوية اختيارات تانية ممكن تعجبك.",
    ),
    "recommendation_none": (
        "You've already seen the available matching options.",
        "إنت شفت بالفعل الاختيارات المتاحة المطابقة لطلبك.",
    ),
    "zero_result": (
        "I couldn't find products matching those filters.",
        "ملقتش منتجات مطابقة للفلاتر دي.",
    ),
    "out_of_catalog": (
        "I couldn't find a matching product in the current catalog.",
        "ملقتش منتج مطابق في الكتالوج الحالي.",
    ),
    "off_topic": (
        "I can help you search for and explore products in the store.",
        "أقدر أساعدك تدور على المنتجات وتستكشف اختيارات من المتجر.",
    ),
    "reset": (
        "Sure, I've cleared your current search. What would you like to find?",
        "تمام، بدأت لك بحث جديد. تحب تدور على إيه؟",
    ),
    "add_filter": (
        "Sure, I've updated your search with that filter.",
        "تمام، ضفت الفلتر للبحث.",
    ),
    "modify_filter": (
        "Sure, I've updated your search.",
        "تمام، عدّلت البحث.",
    ),
    "remove_filter": (
        "Sure, I've removed that filter.",
        "تمام، شلت الفلتر.",
    ),
    "blocked": (
        "I can't process that request. Please try a normal product search.",
        "مش هقدر أنفذ الطلب ده. جرّب تسألني عن منتج بشكل عادي.",
    ),
    "error": (
        "Something went wrong understanding that -- please try again.",
        "حصل مشكلة في فهم طلبك -- جرّب تاني.",
    ),
    "recommendation_needs_clarification": (
        "Tell me what product, category, or brand you're looking for and I can help.",
        "قولي عايز منتج إيه أو أي فئة أو ماركة، وأنا هساعدك.",
    ),
}


# ---------------------------------------------------------------------
# Sprint 6: session-scoped conversational memory. No LLM call, no
# catalog/product lookup -- answers come only from data the session
# already holds (src/scenario/session_activity.py's unbounded `turns`
# log, and StateManager's own canonical, already-merged FilterSet for the
# "product" case). Read-only: calling this never mutates anything.
# ---------------------------------------------------------------------

_MEMORY_NOTHING_YET: dict[str, tuple[str, str]] = {
    "previous": (
        "I don't have anything from earlier in this conversation yet.",
        "لسه معنديش حاجة من قبل في المحادثة دي.",
    ),
    "first": (
        "I don't have anything from earlier in this conversation yet.",
        "لسه معنديش حاجة من قبل في المحادثة دي.",
    ),
    "product": (
        "You haven't mentioned a product, brand, or price yet.",
        "لسه معنديش منتج أو ماركة أو سعر قولت عليه.",
    ),
}


def _memory_price_phrase(price_min: float | None, price_max: float | None, arabic: bool) -> str | None:
    if price_min is not None and price_max is not None:
        return f"سعر بين {price_min:g} و {price_max:g}" if arabic else f"price between {price_min:g} and {price_max:g}"
    if price_max is not None:
        return f"سعر تحت {price_max:g}" if arabic else f"price under {price_max:g}"
    if price_min is not None:
        return f"سعر فوق {price_min:g}" if arabic else f"price over {price_min:g}"
    return None


def memory_recall_answer(
    user_message: str,
    kind: str,
    *,
    previous_message: str | None,
    first_message: str | None,
    category: str | None,
    brand: str | None,
    price_min: float | None,
    price_max: float | None,
) -> str:
    """Deterministic answer to a memory_recall Action (schema.py). `kind`
    is one of "previous"/"first"/"product" -- exactly the three values
    understand() may set. Language matches the CURRENT recall question,
    via the same is_arabic() check every other assistant_message uses;
    an honest "nothing yet" fallback when the requested information
    genuinely isn't there rather than a made-up answer."""
    arabic = is_arabic(user_message)

    if kind == "previous":
        if previous_message is None:
            return _MEMORY_NOTHING_YET["previous"][1 if arabic else 0]
        return f"قبل كده قولت: \"{previous_message}\"." if arabic else f'Earlier you said: "{previous_message}".'

    if kind == "first":
        if first_message is None:
            return _MEMORY_NOTHING_YET["first"][1 if arabic else 0]
        return (
            f"أول حاجة طلبتها في المحادثة دي كانت: \"{first_message}\"." if arabic
            else f'The first thing you asked for in this conversation was: "{first_message}".'
        )

    # kind == "product"
    parts = []
    if category is not None:
        parts.append(f"الفئة {category}" if arabic else f"category {category}")
    if brand is not None:
        parts.append(f"الماركة {brand}" if arabic else f"brand {brand}")
    price_phrase = _memory_price_phrase(price_min, price_max, arabic)
    if price_phrase is not None:
        parts.append(price_phrase)
    if not parts:
        return _MEMORY_NOTHING_YET["product"][1 if arabic else 0]
    joined = "، ".join(parts) if arabic else ", ".join(parts)
    return f"لحد دلوقتي قولت على {joined}." if arabic else f"So far you've mentioned {joined}."


def build_assistant_message(
    *,
    user_message: str,
    intent: str,
    recommendation_request: bool,
    recommendations_count: int,
    zero_result: bool,
    likely_out_of_catalog: bool,
    blocked: bool,
    needs_clarification: bool = False,
) -> str:
    """One deterministic, always-non-null conversational reply. Built only
    from already-known runtime signals -- no new LLM call, no product/
    brand/category/price/count ever inserted (see module docstring).

    Precedence (checked in this exact order -- states are mutually
    exclusive at each step, so only ONE branch below ever fires):
      1. blocked                          -- security wording wins outright
      2. intent == error                  -- understand() itself failed
      3. intent == off_topic              -- never discusses products/results
      4. intent == reset
      4. zero_result (out_of_catalog is the more specific sub-case)
      5. needs_clarification              -- recommendation asked with NO
         active search context at all (nothing to explore from) -- distinct
         from, and must not be confused with, "asked but nothing new" below
      6. recommendation_request           -- honesty rule: recommendations_
         count==0 NEVER produces "I found recommendations" wording, whether
         or not a fresh search also happened this turn
      7. plain per-intent search/filter success
    """
    arabic = is_arabic(user_message)

    if blocked:
        key = "blocked"
    elif intent == "error":
        key = "error"
    elif intent == "off_topic":
        key = "off_topic"
    elif intent == "reset":
        key = "reset"
    elif zero_result:
        key = "out_of_catalog" if likely_out_of_catalog else "zero_result"
    elif needs_clarification:
        key = "recommendation_needs_clarification"
    elif recommendation_request:
        if recommendations_count <= 0:
            key = "recommendation_none"
        elif intent == "no_op":
            key = "recommendation_success"
        else:
            key = "search_and_recommendations"
    elif intent in ("add_filter", "modify_filter", "remove_filter"):
        key = intent
    else:
        key = "search_success"

    en, ar = _ASSISTANT_MESSAGES[key]
    return ar if arabic else en
