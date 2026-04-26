"""Per-bot in-process state for live tours.

Tracks the current room hint set by "Next Room" so the streaming extractor
can pick it up between transcript chunks. Locked decision (per brief):
in-process state, no Redis. Fragile across restarts — accepted for MVP.
"""

from dataclasses import dataclass, field
import asyncio
import time


@dataclass
class BotState:
    bot_id: str
    house_id: str
    current_room: str | None = None
    last_extraction_at: float = field(default_factory=time.monotonic)
    extraction_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_bots: dict[str, BotState] = {}


def get_or_create(bot_id: str, house_id: str) -> BotState:
    s = _bots.get(bot_id)
    if s is None:
        s = BotState(bot_id=bot_id, house_id=house_id)
        _bots[bot_id] = s
    return s


def get(bot_id: str) -> BotState | None:
    return _bots.get(bot_id)


def drop(bot_id: str) -> None:
    _bots.pop(bot_id, None)


def set_room(bot_id: str, room: str | None) -> bool:
    s = _bots.get(bot_id)
    if s is None:
        return False
    s.current_room = room
    return True
