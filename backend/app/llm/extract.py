from functools import lru_cache
from typing import TypedDict

import anthropic

from app.config import settings

EXTRACTION_MODEL = "claude-haiku-4-5-20251001"
RECENT_OBS_LIMIT = 30
MAX_OUTPUT_TOKENS = 2048

SYSTEM_PROMPT = """You extract observations about houses from real estate tour transcripts.

A buyer is touring a home with their agent. Your job: find specific, factual observations from what was said and call the `record_observations` tool with them.

What counts as an observation:
- Layout: room counts, sizes, flow ("kitchen opens to living room")
- Condition: age of appliances, wear, recent updates
- Hazards: water damage, mold, electrical issues, structural concerns
- Positive features: natural light, views, finishes, storage
- Concerns: HOA fees, location issues, layout flaws, deferred maintenance
- Agent statements: things the agent says as fact about the property (price history, days on market, prior offers)

What does NOT count:
- Small talk, greetings, scheduling
- Questions without answers
- Speculation not grounded in the transcript

For each observation, set:
- room: the room being discussed if clear ("kitchen", "primary bath", "garage"). Use the provided room hint as a strong prior — but override if the transcript clearly indicates a different room. Use null if no room is implied.
- category: one of layout | condition | hazard | positive | concern | agent_said | partner_said.
  Use agent_said when the source is clearly the agent stating a property fact.
  Use partner_said only when the speaker is explicitly identified as the buyer's partner. Speakers are not always identified in this phase — when in doubt, classify by topic (layout/condition/hazard/etc.) instead.
- content: a faithful, near-verbatim quote or tight paraphrase from the transcript.
- severity: info | warn | critical for hazards and concerns; null otherwise.
  critical: safety risk, legal exposure, or deal-breaker (mold, structural, major code issue)
  warn: significant issue (aging system, deferred maintenance, expensive fix)
  info: noted but minor

Already-captured observations are listed in the user message — do not duplicate them.

Return zero observations if the transcript chunk contains nothing notable. Empty results are valid and expected — most utterances are not observations."""

TOOL_SCHEMA = {
    "name": "record_observations",
    "description": "Record structured observations extracted from the transcript chunk.",
    "input_schema": {
        "type": "object",
        "properties": {
            "observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "room": {
                            "type": ["string", "null"],
                            "description": "Room being discussed, or null if not implied.",
                        },
                        "category": {
                            "type": "string",
                            "enum": [
                                "layout",
                                "condition",
                                "hazard",
                                "positive",
                                "concern",
                                "agent_said",
                                "partner_said",
                            ],
                        },
                        "content": {
                            "type": "string",
                            "description": "Near-verbatim quote or tight paraphrase from the transcript.",
                        },
                        "severity": {
                            "type": ["string", "null"],
                            "enum": [None, "info", "warn", "critical"],
                            "description": "Severity for hazards/concerns; null otherwise.",
                        },
                    },
                    "required": ["room", "category", "content", "severity"],
                },
            }
        },
        "required": ["observations"],
    },
}


class ObservationCandidate(TypedDict):
    room: str | None
    category: str
    content: str
    severity: str | None


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _format_recent_obs(observations: list[dict]) -> str:
    if not observations:
        return "(none yet)"
    lines = []
    for o in observations[-RECENT_OBS_LIMIT:]:
        room = o.get("room")
        prefix = f"[{o['category']}, {room}]" if room else f"[{o['category']}]"
        lines.append(f"- {prefix} {o['content']}")
    return "\n".join(lines)


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


def extract_observations(
    transcript_chunks: list[dict],
    recent_observations: list[dict],
    room_hint: str | None,
) -> list[ObservationCandidate]:
    """Extract observations from a transcript window via Haiku 4.5 + tool use.

    Prompt caching marker is set on system + tool blocks per spec. Note: Haiku 4.5
    requires a 4096-token prefix to actually cache; until the prefix grows with
    few-shot examples, cache reads will be 0.
    """
    user_message = (
        "Already captured (do not duplicate):\n"
        f"{_format_recent_obs(recent_observations)}\n\n"
        f"Current room hint: {room_hint or '(unknown)'}\n\n"
        "Transcript chunk:\n"
        f"{_format_transcript(transcript_chunks)}"
    )

    response = _client().messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[{**TOOL_SCHEMA, "cache_control": {"type": "ephemeral"}}],
        tool_choice={"type": "tool", "name": "record_observations"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_observations":
            return list(block.input.get("observations", []))
    return []
