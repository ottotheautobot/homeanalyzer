"""Schematic floor plan generator.

Takes the synthesis brief, the full transcript, and all observations from a
completed tour and asks Sonnet to reconstruct the rooms in tour order plus
the doorway adjacencies between them. Output is a lo-fi node+edge graph —
NOT a scaled floor plan (no measurements, no wall geometry).

Cost: ~3-5k tokens in, ~1-2k out per tour, single Sonnet call.
"""

from functools import lru_cache
from typing import TypedDict

import anthropic

from app.config import settings

FLOORPLAN_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 4096
MODEL_VERSION = "sonnet-4-6.v1"

SYSTEM_PROMPT = """You reconstruct a schematic of a house from a tour recording's transcript and observations.

This is a lo-fi room map — NOT a scaled floor plan. You output:
1. The rooms visited, in the order the tour entered them.
2. Doorway adjacencies — which rooms connect to which.
3. Per-room features pulled from the observations (windows, fixtures, condition notes, etc).

Rules:
- A "room" is a distinct named space the tour walked through (kitchen, primary bedroom, garage, hallway). Don't invent rooms not mentioned. Merge near-duplicates (e.g., "kitchen" and "the kitchen area" are one room).
- Use the timestamps to order rooms by when the tour first entered them.
- Infer adjacencies primarily from the temporal sequence: if room A is exited at t=120 and room B is entered at t=121, they share a doorway. Also use explicit transcript clues ("through here is the bathroom", "off the kitchen is...").
- For features, use the observations — keep each feature short (3-7 words). Skip generic items.
- Be honest: if the data is thin (very short tour, few observations, rooms unclear), return what you can and lower confidence. Don't fabricate."""

TOOL_SCHEMA = {
    "name": "record_floor_plan",
    "description": "Record the schematic floor plan for the toured house.",
    "input_schema": {
        "type": "object",
        "properties": {
            "rooms": {
                "type": "array",
                "description": "Rooms visited, in tour order (first entered first).",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Stable id like 'r1', 'r2'. Used to reference in doors[].",
                        },
                        "label": {
                            "type": "string",
                            "description": "Human room name, lowercase: 'kitchen', 'primary bedroom', 'garage'.",
                        },
                        "entered_at": {
                            "type": ["number", "null"],
                            "description": "Approx seconds into tour the room was entered.",
                        },
                        "exited_at": {
                            "type": ["number", "null"],
                            "description": "Approx seconds into tour the room was exited.",
                        },
                        "features": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Short feature notes pulled from observations.",
                        },
                    },
                    "required": ["id", "label", "features"],
                },
            },
            "doors": {
                "type": "array",
                "description": "Doorway adjacencies between rooms. Undirected — list each pair once.",
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string", "description": "Room id."},
                        "to": {"type": "string", "description": "Room id."},
                        "via": {
                            "type": "string",
                            "enum": ["sequence", "transcript"],
                            "description": "Source of the adjacency inference.",
                        },
                    },
                    "required": ["from", "to", "via"],
                },
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "How confident the reconstruction is given input quality.",
            },
            "notes": {
                "type": ["string", "null"],
                "description": "Optional 1-sentence note about gaps or assumptions.",
            },
        },
        "required": ["rooms", "doors", "confidence"],
    },
}


class Room(TypedDict):
    id: str
    label: str
    entered_at: float | None
    exited_at: float | None
    features: list[str]


# "from" is a reserved keyword, so use functional TypedDict syntax.
Door = TypedDict("Door", {"from": str, "to": str, "via": str})


class FloorPlan(TypedDict):
    rooms: list[Room]
    doors: list[Door]
    confidence: str
    notes: str | None
    model_version: str


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _format_transcript(chunks: list[dict]) -> str:
    if not chunks:
        return "(empty)"
    lines = []
    for c in chunks:
        prefix = f"[{c['start_seconds']:.0f}s]"
        speaker = c.get("speaker")
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
        ts = o.get("recall_timestamp")
        ts_part = f"@{ts:.0f}s " if ts is not None else ""
        source = SOURCE_LABEL.get(o.get("source", "transcript"), "transcript")
        room = o.get("room")
        bits = [source, o["category"]]
        if room:
            bits.append(room)
        prefix = "[" + ", ".join(bits) + "]"
        lines.append(f"- {ts_part}{prefix} {o['content']}")
    return "\n".join(lines)


def generate_floor_plan(
    transcript_chunks: list[dict],
    observations: list[dict],
    synthesis_md: str | None,
) -> FloorPlan:
    """Generate the schematic floor plan via Sonnet 4.6."""
    user_message = (
        "Synthesis brief (for context):\n"
        + (synthesis_md or "(none)")
        + "\n\nObservations (with timestamps):\n"
        + _format_observations(observations)
        + "\n\nFull transcript:\n"
        + _format_transcript(transcript_chunks)
    )

    response = _client().messages.create(
        model=FLOORPLAN_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "record_floor_plan"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "record_floor_plan":
            data = block.input
            rooms: list[Room] = [
                Room(
                    id=r["id"],
                    label=r["label"],
                    entered_at=r.get("entered_at"),
                    exited_at=r.get("exited_at"),
                    features=r.get("features") or [],
                )
                for r in data.get("rooms", [])
            ]
            doors: list[Door] = [
                {"from": d["from"], "to": d["to"], "via": d["via"]}
                for d in data.get("doors", [])
            ]
            return FloorPlan(
                rooms=rooms,
                doors=doors,
                confidence=data.get("confidence", "low"),
                notes=data.get("notes"),
                model_version=MODEL_VERSION,
            )

    raise RuntimeError("Sonnet did not call record_floor_plan tool")
