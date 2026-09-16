# Feature Specification: Conversational Search Baseline

**Feature Branch**: `001-conversational-search-baseline`

**Created**: 2026-09-06

**Status**: Draft

**Input**: User description: "Create the baseline specification for Project 6 — Conversational Search. The goal is to demonstrate that conversational search can reduce search friction compared with traditional keyword search. The system should allow users to search using natural language, specify multiple requirements at once, add/modify/remove filters across turns, reset search, maintain context, ask for clarification when ambiguous, search in English and Arabic with equivalent requests mapping to the same canonical intent/filter representation, and return only products from the available corpus. Evaluation must compare conversational search against a keyword-search baseline on the same corpus and queries, using Search Success Rate, Zero-Result Rate, Follow-Up Success Rate, and Search Conversion Rate (where transaction data exists). Not an e-commerce site, payment system, inventory system, recommendation engine, or general-purpose chatbot."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Natural-Language Search With Multiple Requirements (Priority: P1)

A shopper describes what they want in one natural-language message that bundles several
requirements at once (e.g., "I need chocolate under 30 EGP" or "عايز شوكولاتة تحت ٣٠ جنيه",
or "detergent from Persil under 150 EGP"), and the system returns matching products from the
catalog without requiring the shopper to issue separate queries per requirement.

**Why this priority**: This is the core value proposition of conversational search over
keyword search — collapsing several constraints into one natural request. Without this,
there is no baseline capability to compare against keyword search at all.

**Independent Test**: Can be fully tested by submitting a single natural-language message
containing 2+ distinct requirements (e.g., category, price ceiling, brand) and verifying the
returned products satisfy all stated requirements and come from the product corpus.

**Acceptance Scenarios**:

1. **Given** an empty session, **When** the shopper sends a single message naming a product
   category, a price limit, and a brand, **Then** the system returns only corpus products
   that satisfy all three stated requirements.
2. **Given** an empty session, **When** the shopper sends a message with only a vague
   category and no other detail, **Then** the system still returns corpus products matching
   that category (no requirement to over-ask when the request is not ambiguous, merely
   broad).
3. **Given** an empty session, **When** the shopper's message requirements match zero corpus
   products, **Then** the system reports no results and does not substitute unrelated or
   invented products.

---

### User Story 2 - Multi-Turn Filter Refinement (Priority: P1)

A shopper narrows or changes their search across several follow-up messages instead of
restating the entire request each time: adding a new constraint, changing an existing one,
removing one, or resetting the search entirely.

**Why this priority**: Multi-turn refinement is the second pillar of the project's value
proposition and the main behavior keyword search cannot replicate. It must work reliably for
the comparison against the baseline to be meaningful.

**Independent Test**: Can be fully tested by running a fixed sequence of follow-up messages
against an established search context and verifying the resulting filter set and results
after each turn, independent of any other story.

**Acceptance Scenarios**:

1. **Given** an active search with one or more filters already applied, **When** the shopper
   adds a new requirement in a follow-up message (e.g., "only from Nestle"), **Then** the new
   filter is applied on top of the existing ones and results reflect all of them together.
2. **Given** an active search with a filter already applied (e.g., price under 80 EGP), **When**
   the shopper changes that same filter in a follow-up (e.g., "actually under 50 EGP"),
   **Then** the old value is replaced, not added alongside the new one, and results reflect
   only the updated value.
3. **Given** an active search with multiple filters applied, **When** the shopper asks to
   remove one specific filter, **Then** that filter is dropped and the remaining filters
   still apply unchanged.
4. **Given** an active search with filters applied, **When** the shopper asks to reset the
   search, **Then** all filters and prior context are cleared and the next message is
   treated as the start of a new search.
5. **Given** an active search with results already shown, **When** the shopper refers back to
   those results or filters implicitly (e.g., "show me cheaper ones," "the same but from a
   different brand"), **Then** the system resolves the reference using the current session
   context rather than treating it as an unrelated new search.

---

### User Story 3 - Bilingual Search With Canonical Equivalence (Priority: P1)

A shopper searches in either English or Arabic, including switching languages between
turns, and equivalent requests in either language are understood as the same underlying
search intent.

**Why this priority**: Bilingual support is an explicit, non-negotiable project requirement
(see project constitution, Principle II). Without demonstrable EN/AR equivalence, the
system cannot claim to serve both languages as first-class.

**Independent Test**: Can be fully tested by submitting matched pairs of English and Arabic
messages that express the same requirements and verifying they produce the same resolved
filters and the same result set from the corpus.

**Acceptance Scenarios**:

1. **Given** an empty session, **When** the shopper sends an English message and, in a
   separate session, sends the Arabic equivalent expressing the same requirements, **Then**
   both sessions resolve to the same canonical filter representation and the same result
   set.
2. **Given** an active English-language session with filters already applied, **When** the
   shopper sends a follow-up message in Arabic, **Then** the system correctly applies the
   follow-up to the existing context regardless of the language switch.

---

### User Story 4 - Clarification of Ambiguous Requests (Priority: P2)

When a shopper's message is genuinely ambiguous — it could reasonably be interpreted in
materially different ways that would change the result set — the system asks a targeted
clarifying question instead of guessing.

**Why this priority**: Guessing on ambiguous input silently produces wrong results and
undermines trust in the comparison against keyword search (which does not "guess" either;
it simply returns literal matches). This is secondary to core search and refinement but
required for a fair, trustworthy baseline.

**Independent Test**: Can be fully tested by submitting a small set of intentionally
ambiguous messages (in English and Arabic) and verifying the system asks a clarifying
question rather than returning a guessed result set.

**Acceptance Scenarios**:

1. **Given** an empty session, **When** the shopper sends a message that could map to two or
   more materially different product categories or filter values, **Then** the system asks
   a clarifying question naming the specific ambiguity instead of picking one interpretation
   silently.
2. **Given** the system has asked a clarifying question, **When** the shopper responds with
   the missing information, **Then** the system proceeds using that answer without asking
   the same question again.

---

### User Story 5 - Baseline Comparison Evaluation (Priority: P2)

An evaluator runs the same set of evaluation queries and multi-turn task sequences, in both
languages, against the conversational search system and the traditional keyword-search
baseline over the same product corpus, and receives a side-by-side report of the defined
metrics.

**Why this priority**: This is the mechanism that actually validates (or falsifies) the
project's central hypothesis that conversational search reduces search friction. It depends
on the other stories being implemented but is what turns this prototype into evidence.

**Independent Test**: Can be fully tested by executing the shared evaluation query set
against both systems and confirming a report is produced containing all four defined
metrics, computed identically for both systems from the same inputs.

**Acceptance Scenarios**:

1. **Given** a shared set of evaluation queries and the same product corpus, **When** the
   evaluation is run, **Then** both the conversational system and the keyword-search
   baseline are evaluated on every query in the set and results are recorded per query per
   system.
2. **Given** a multi-turn evaluation task, **When** it is run against the keyword-search
   baseline (which has no conversational context), **Then** the baseline's inability to
   carry context across turns is recorded as a measured outcome rather than silently
   skipped or excused.
3. **Given** completed evaluation runs for both systems, **When** the report is generated,
   **Then** it states Search Success Rate, Zero-Result Rate, and Follow-Up Success Rate for
   each system, and states Search Conversion Rate only where real transaction/interaction
   data exists — otherwise it is explicitly labeled as an unmeasured hypothesis, not a
   number.

---

### Edge Cases

- What happens when a follow-up asks to remove a filter that was never set (e.g., "remove
  the brand filter" with no brand filter active)? The system must not error silently or
  fabricate a filter to remove; it should state that no such filter is active.
- What happens when a reset command is immediately followed by a message that implicitly
  references prior context (e.g., "the cheaper one")? Post-reset, such references must be
  treated as unresolvable/new, not linked to the cleared session.
- What happens when a single message mixes English and Arabic (e.g., an Arabic sentence with
  an English brand name)? The system must still extract the intended filters rather than
  failing outright.
- What happens when a correctly interpreted request matches zero corpus products? The system
  must report zero results rather than loosening filters silently or returning near matches
  unlabeled as such.
- What happens when two sequential messages state contradictory values for the same filter
  (e.g., "under $50" then "under $200")? The later statement must be treated as a
  modification of that same filter, not an additional, conflicting constraint.
- What happens when the shopper's message is broad but not ambiguous (e.g., just a category
  name)? The system must not over-ask for clarification when a reasonable, non-guessed
  result set can already be returned.
- What happens when a product belongs to more than one category in the corpus (a product can
  legitimately sit in several at once, e.g., a juice tagged both "Beverages" and "Ramadan
  Offers")? A category filter must match the product if it belongs to any of its linked
  categories, not just a single assumed category.
- What happens when the same real-world category is represented by more than one
  near-duplicate entry in the corpus (e.g., "Meat" and "Meat & Poultry" as separate records)?
  These must resolve to one canonical filter value at search time so results are not silently
  missing products filed under the "other" spelling.
- What happens when the shopper asks for brand, which exists in the corpus only as an
  unnormalized free-text value (not a clean validated enum, and inconsistently spelled or
  mixed-language across records)? The system must not fabricate or guess a brand value for a
  product where none is present; it should fall back to a best-effort, normalized text match
  and, where that yields nothing usable, say so rather than silently dropping the request.
  Attributes the corpus does not meaningfully capture at all for this catalog (e.g., color,
  or a shopper-facing "size" distinct from package weight) are not treated as supported
  filters.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept a single natural-language message expressing multiple
  distinct product requirements (e.g., category, price, brand) and resolve all of them
  as filters for one search.
- **FR-002**: The system MUST allow a follow-up message to add a new filter to an active
  search without requiring the shopper to restate previously stated requirements.
- **FR-003**: The system MUST allow a follow-up message to modify the value of a filter
  already active in the session, replacing the old value rather than retaining both.
- **FR-004**: The system MUST allow a follow-up message to remove a specifically named active
  filter while leaving all other active filters unchanged.
- **FR-005**: The system MUST support an explicit reset action that clears all active filters
  and conversation context for the session, after which subsequent messages are treated as a
  new search with no residual state.
- **FR-006**: The system MUST maintain filter and result context across turns within a
  session so that follow-up messages can be interpreted relative to the current state
  (active filters and last result set) without the shopper repeating prior information.
- **FR-007**: The system MUST detect when a message is ambiguous — i.e., admits two or more
  materially different interpretations that would change the result set — and respond with a
  clarifying question instead of selecting an interpretation without confirmation.
- **FR-008**: The system MUST NOT ask a clarifying question for messages that are merely
  broad but not ambiguous (i.e., where a reasonable, non-guessed result set already exists).
- **FR-009**: The system MUST accept natural-language search messages in both English and
  Arabic, including a follow-up in one language after an initial message in the other within
  the same session.
- **FR-010**: The system MUST map requests that express the same requirements in English and
  in Arabic to the same canonical search intent/filter representation, independent of the
  input language.
- **FR-011**: The system MUST only return products that exist in the defined product corpus
  and MUST NOT generate, describe, or imply the existence of products absent from that
  corpus.
- **FR-012**: When resolved filters match zero products in the corpus, the system MUST report
  that no results were found rather than silently loosening filters or substituting
  unrelated products.
- **FR-013**: The system MUST record, for every search response produced in a session, the
  resolved filters/intent that produced it, so that any result set can be traced back to the
  interpretation that generated it.
- **FR-014**: A traditional keyword-search baseline MUST be operable over the same product
  corpus, accepting literal keyword-style queries, for use as the comparison point.
- **FR-015**: The evaluation process MUST run an identical set of evaluation queries and
  multi-turn task sequences, in both English and Arabic, against both the conversational
  system and the keyword-search baseline, using the same product corpus for both.
- **FR-016**: The evaluation process MUST compute and report, per system, at minimum: Search
  Success Rate, Zero-Result Rate, and Follow-Up Success Rate, using the same definition and
  the same evaluation query set for both systems.
- **FR-017**: The evaluation process MUST compute and report Search Conversion Rate only when
  real transaction/interaction data is available for a given evaluation query; when it is
  not available, the report MUST label that metric explicitly as an unmeasured hypothesis
  rather than presenting a fabricated or estimated figure as a result.
- **FR-018**: The system MUST NOT provide functionality for payment processing, inventory
  management, personalized product recommendations beyond direct search results, or
  general-purpose conversation unrelated to product search.
- **FR-019**: When the source corpus represents the same real-world category as more than one
  distinct category record (e.g., near-duplicate or differently-spelled category entries),
  the system MUST treat a category filter as matching a product under any of those
  equivalent records, so results are not incomplete due to which specific record a product
  happens to be filed under.
- **FR-020**: The system MUST NOT reject or silently ignore a search or filter request solely
  because the requested attribute (e.g., brand) is not present as a clean, validated enum
  for some or all matching products; it MUST fall back to the best available match (e.g., a
  normalized text match against the attribute's raw value or the product name) and state
  when an attribute could not be reliably applied, rather than fabricating a value.

### Key Entities

- **Product**: A single item in the product corpus, with attributes that filters are matched
  against. Category and price are structured and reliably present for the large majority of
  products. Brand is present as a semi-structured, free-text value for the large majority of
  products, but its raw spellings are too fragmented and inconsistent (including mixed
  English/Arabic renderings of the same brand) to treat as a clean, validated enum the way
  category is; it is matched on a best-effort, normalized-text basis rather than an exact
  enum. Color and a shopper-facing "size" facet are not meaningfully present in this corpus
  and are not supported filters. Products are read-only for this feature — no creation,
  editing, or inventory tracking.
- **Product Corpus**: The fixed, shared collection of products available to both the
  conversational system and the keyword-search baseline for a given evaluation run.
- **Search Session**: A single continuous conversation between one shopper and the
  conversational system, holding the accumulated active filters, the last result set, and
  the language(s) used, from session start until an explicit reset or session end.
- **Filter**: A single resolved search constraint (an attribute, a comparison, and a value)
  that is part of the active search state within a session.
- **Canonical Search Intent**: The language-independent, normalized representation of a
  shopper's current requirements (the active set of filters) used to query the corpus and
  used to compare English and Arabic requests for equivalence.
- **Evaluation Query/Task**: A predefined single-turn query or multi-turn sequence, available
  in English and Arabic, used identically against both systems during evaluation.
- **Evaluation Result**: The recorded, per-query, per-system outcome data (success/failure,
  zero-result flag, follow-up outcome, conversion data if available) used to compute the
  reported metrics.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of queries in the shared evaluation set produce a recorded, comparable
  outcome for both the conversational system and the keyword-search baseline, run on the
  same product corpus.
- **SC-002**: In at least 95% of multi-turn evaluation sequences, the conversational system's
  filters after each follow-up exactly match the expected accumulated filter set (no lost,
  duplicated, or stale constraints from earlier turns).
- **SC-003**: Zero instances, across the full evaluation set, of the conversational system or
  the keyword-search baseline returning a product not present in the product corpus.
- **SC-004**: For a set of matched English/Arabic query pairs expressing the same
  requirements, at least 90% resolve to the same canonical search intent/filter
  representation.
- **SC-005**: In at least 95% of messages flagged as ambiguous in the evaluation set, the
  system asks a clarifying question rather than returning a guessed result set.
- **SC-006**: The evaluation report presents Search Success Rate, Zero-Result Rate, and
  Follow-Up Success Rate for the conversational system and the keyword-search baseline
  side by side, computed from the same query set and corpus, and presents Search Conversion
  Rate the same way wherever real transaction data exists — yielding a clear, falsifiable
  conclusion about whether conversational search reduces search friction relative to
  keyword search.

## Assumptions

- The product corpus is a fixed, finite dataset shared identically by both the
  conversational system and the keyword-search baseline during evaluation; it is not sourced
  from a live or third-party inventory feed. It is a real supermarket product catalog
  (provided by the instructor) rather than a synthetic or hand-curated dataset, and it
  carries the imperfections of real production data: a meaningful share of products are
  uncategorized or have a non-descriptive identifier, and the category list itself contains
  near-duplicate and non-product ("test") entries that must be cleaned/canonicalized before
  use as a filter enum, rather than assumed clean.
- Category and price are the two attributes treated as reliable, structured filters for this
  feature. Brand is present in the source data as a free-text value for the large majority of
  products (stored per-product, not as a separate lookup table), but its raw values are too
  fragmented across spellings and languages to canonicalize into a clean validated enum
  within this project's scope; where brand is used, it is as a best-effort, normalized text
  match, not a validated enum, and this feature does not depend on brand's availability for
  every product to meet its success criteria. Color and a shopper-facing "size" facet are not
  usable filters for this catalog: color values are essentially absent across the corpus, and
  the closest available field describes package weight/quantity rather than a filterable
  facet, so neither is treated as a supported filter attribute.
- The evaluation query/task set (English and Arabic, single-turn and multi-turn) is prepared
  and agreed upon as a shared, versioned set before evaluation runs, so both systems are
  measured on identical inputs.
- The canonical search intent/filter representation is primarily an internal, inspectable
  representation used for query resolution, evaluation, and debugging; it is not required to
  be shown verbatim to end users.
- A "session" is a single continuous conversation; the system is not required to persist
  filters or context across separate sessions, devices, or users.
- Search Conversion Rate depends on transaction/interaction data that may not exist for this
  prototype; where it is absent, the evaluation treats it as a downstream business
  hypothesis to be validated later, not as a number to be invented now.
- "Search friction" is operationalized for this baseline via the four defined metrics
  (Search Success Rate, Zero-Result Rate, Follow-Up Success Rate, Search Conversion Rate);
  subjective user-satisfaction surveys are out of scope for this specification.
- Out of scope for this feature, per project scope: a full e-commerce storefront, payment
  processing, inventory management, a general-purpose recommendation engine, and
  general-purpose chatbot capabilities unrelated to product search.
