"""Sonnet-powered cross-house comparison."""

from functools import lru_cache

import anthropic

from app.config import settings

COMPARE_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 4096

SYSTEM_PROMPT = """You help a buyer compare houses they've toured.

You'll receive:
- Per-house briefs (post-tour synthesis markdown) plus key facts (address,
  price, beds/baths, score)
- Per-house observation rows captured during the tour (layout, condition,
  hazard, positive, concern, agent_said, partner_said)
- A natural-language query from the buyer

Write a markdown answer that:
- Directly addresses the query
- Cites specific houses by address (or by short label) for every claim
- Uses observations and brief content as evidence — not vibes
- Is honest about thin data: if a house was barely toured, say so before
  drawing strong conclusions about it
- Stays concise. The buyer is making a decision, not reading prose.

Don't restate the query. Don't preamble. Lead with the answer."""


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def compare_houses(houses: list[dict], observations_by_house: dict[str, list[dict]], query: str) -> str:
    """Run a Sonnet comparison pass and return markdown."""
    sections = []
    for h in houses:
        score = h.get("overall_score")
        meta_bits = []
        if h.get("list_price") is not None:
            meta_bits.append(f"${int(h['list_price']):,}")
        if h.get("beds") is not None:
            meta_bits.append(f"{h['beds']} bd")
        if h.get("baths") is not None:
            meta_bits.append(f"{h['baths']} ba")
        if h.get("sqft") is not None:
            meta_bits.append(f"{int(h['sqft']):,} sqft")
        meta = " · ".join(meta_bits) if meta_bits else "(no listing data)"
        score_text = f"Score: {score:.1f}" if score is not None else "Score: —"

        synth = (h.get("synthesis_md") or "(no synthesis brief on this house)").strip()
        obs = observations_by_house.get(h["id"], [])
        obs_lines = [
            f"- [{o['category']}{'/' + o['severity'] if o.get('severity') else ''}{'/' + o['room'] if o.get('room') else ''}] {o['content']}"
            for o in obs
        ]
        obs_block = "\n".join(obs_lines) if obs_lines else "(no observations)"

        sections.append(
            f"## {h['address']}\n{meta} | {score_text}\n\n### Brief\n{synth}\n\n### Observations\n{obs_block}"
        )

    user_message = "## Houses\n\n" + "\n\n---\n\n".join(sections) + f"\n\n---\n\n## Buyer query\n{query}"

    resp = _client().messages.create(
        model=COMPARE_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    out = ""
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            out += block.text
    return out.strip()
