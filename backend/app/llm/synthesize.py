from functools import lru_cache
from typing import TypedDict

import anthropic

from app.config import settings

SYNTHESIS_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 8192

SYSTEM_PROMPT = """You write the post-tour brief for a house the buyer just toured.

Inputs you'll receive in the user message:
- House facts (address, sale-or-rent price, sqft, beds, baths)
- Observations captured during the tour, each tagged with source:
    [transcript] = extracted from what was said during the tour
    [video] = extracted from visual frames of the tour recording
    [manual] = added by the user
  Use both sources together — visual observations often catch what the
  audio missed (visible damage no one mentioned, fixture quality, etc.)
  and audio observations capture context the visuals lack (price history,
  agent statements, partner reactions).
- The full audio transcript with timestamps

If the same issue is flagged by both video and audio (e.g., agent says
"there's a water stain" and video also flagged it), treat as ONE issue
backed by both sources — don't double-count in your scoring.

Honor the price kind: if the price is monthly rent, frame the brief
around rental considerations (lease terms, neighborhood, landlord),
not buying decisions (resale value, comps, offer strategy).

Output: a markdown brief that helps the buyer compare houses later. Be concise and concrete — no filler. Optimize for speed of reading and recall.

Required sections, in this order:
1. **Executive summary** — 2–4 sentences. The shape of this house and how it likely fits the buyer.
2. **Top concerns** — bulleted list. Anything that should give the buyer pause. Order by severity (critical first). Cite the observation or quote when possible.
3. **Deal-breakers** — bulleted list. Issues severe enough to disqualify this house, if any. Empty list is fine.
4. **Highlights** — bulleted list. Genuinely positive features.
5. **Open questions** — bulleted list. Things the buyer should ask before making an offer.

Score the house 0–10:
- 0–3: do not pursue
- 4–6: real concerns; pursue only if other options are worse
- 7–8: solid contender
- 9–10: excellent; move fast

Be honest. If the data is thin (short tour, few observations), say so in the executive summary and weight the score toward the middle."""

TOOL_SCHEMA = {
    "name": "record_synthesis",
    "description": "Record the post-tour synthesis brief and overall score.",
    "input_schema": {
        "type": "object",
        "properties": {
            "synthesis_md": {
                "type": "string",
                "description": "Full markdown brief with the five required sections.",
            },
            "overall_score": {
                "type": "number",
                "minimum": 0,
                "maximum": 10,
                "description": "Score from 0 to 10. Use one decimal place if needed.",
            },
        },
        "required": ["synthesis_md", "overall_score"],
    },
}


class SynthesisResult(TypedDict):
    synthesis_md: str
    overall_score: float


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _format_transcript(chunks: list[dict]) -> str:
    if not chunks:
        return "(empty)"
    lines = []
    for c in chunks:
        speaker = c.get("speaker")
        prefix = f"[{c['start_seconds']:.0f}s]"
        if speaker:
            prefix += f" {speaker}:"
        lines.append(f"{prefix} {c['text']}")
    return "\n".join(lines)


SOURCE_LABEL = {
    "transcript": "transcript",
    "photo_analysis": "video",
    "manual": "manual",
}


def _format_observations(observations: list[dict]) -> str:
    if not observations:
        return "(no observations captured)"
    lines = []
    for o in observations:
        source = SOURCE_LABEL.get(o.get("source", "transcript"), "transcript")
        room = o.get("room")
        sev = o.get("severity")
        bits = [source, o["category"]]
        if room:
            bits.append(room)
        if sev:
            bits.append(sev)
        prefix = "[" + ", ".join(bits) + "]"
        lines.append(f"- {prefix} {o['content']}")
    return "\n".join(lines)


def synthesize_house(
    house_summary: dict,
    transcript_chunks: list[dict],
    observations: list[dict],
) -> SynthesisResult:
    """Generate the end-of-tour synthesis brief for one house via Sonnet 4.6."""
    address = house_summary.get("address", "(unknown address)")
    list_price = house_summary.get("list_price")
    price_kind = house_summary.get("price_kind") or "sale"
    sqft = house_summary.get("sqft")
    beds = house_summary.get("beds")
    baths = house_summary.get("baths")

    facts = [f"Address: {address}"]
    if list_price is not None:
        if price_kind == "rent":
            facts.append(f"Monthly rent: ${list_price:,.0f}/mo")
        else:
            facts.append(f"Sale price: ${list_price:,.0f}")
    if sqft:
        facts.append(f"Sqft: {sqft}")
    if beds is not None:
        facts.append(f"Beds: {beds}")
    if baths is not None:
        facts.append(f"Baths: {baths}")

    user_message = (
        "House facts:\n"
        + "\n".join(facts)
        + "\n\nObservations captured during tour:\n"
        + _format_observations(observations)
        + "\n\nFull transcript:\n"
        + _format_transcript(transcript_chunks)
    )

    response = _client().messages.create(
        model=SYNTHESIS_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "record_synthesis"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_synthesis":
            data = block.input
            return SynthesisResult(
                synthesis_md=data["synthesis_md"],
                overall_score=float(data["overall_score"]),
            )

    raise RuntimeError("Sonnet did not call record_synthesis tool")
