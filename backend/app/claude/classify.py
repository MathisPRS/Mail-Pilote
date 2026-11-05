"""Classification des mails par Claude (CLI headless, sans outils).

Les lots sont traités séquentiellement. Une ClaudeBadOutput (ou toute autre
ClaudeError) levée sur un lot se propage à l'appelant, qui décide quoi faire
(ex. laisser les mails du lot non classés) ; les lots déjà traités sont perdus
côté appelant, qui doit donc traiter lot par lot s'il veut les conserver.
"""
from dataclasses import dataclass
from datetime import date

from app.claude.prompts import SYSTEM_PROMPT, build_prompt
from app.claude.runner import run_claude

CATEGORIES = ["tt", "important", "action", "info", "news", "pub", "spam"]
PRIORITY_CATEGORIES = {"tt", "important", "action"}
HEADERS_BATCH, HEADERS_MODEL = 50, "haiku"
FULL_BATCH, FULL_MODEL = 10, "sonnet"
BODY_MAX_CHARS = 6000

_DATE = {"type": ["string", "null"], "pattern": r"^\d{4}-\d{2}-\d{2}$"}
RESULTS_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "priority": {"type": "boolean"},
                    "reason": {"type": "string", "maxLength": 140},
                    "summary": {"type": "string", "maxLength": 160},
                    "deadline": _DATE,
                    "tt_date": _DATE,
                    "needs_body": {"type": "boolean"},
                },
                "required": ["id", "category", "priority", "reason", "summary",
                             "deadline", "tt_date", "needs_body"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


@dataclass
class HeaderItem:
    message_id: int
    from_name: str
    from_addr: str
    subject: str
    preview: str


@dataclass
class FullItem(HeaderItem):
    body_text: str = ""


@dataclass
class Classification:
    message_id: int
    category: str
    priority: bool
    reason: str
    summary: str
    deadline: date | None
    tt_date: date | None
    needs_body: bool


def _parse_date(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


async def _run(items: list, size: int, model: str) -> list[Classification]:
    out: list[Classification] = []
    for i in range(0, len(items), size):
        batch = items[i : i + size]
        known = {it.message_id for it in batch}
        data = await run_claude(
            build_prompt(batch), system=SYSTEM_PROMPT, schema=RESULTS_SCHEMA, model=model
        )
        seen: set[int] = set()
        for r in data["results"]:
            mid = r["id"]
            if mid not in known or mid in seen:
                continue
            seen.add(mid)
            out.append(Classification(
                message_id=mid,
                category=r["category"],
                priority=r["category"] in PRIORITY_CATEGORIES,
                reason=r["reason"],
                summary=r["summary"],
                deadline=_parse_date(r["deadline"]),
                tt_date=_parse_date(r["tt_date"]),
                needs_body=r["needs_body"],
            ))
    return out


async def classify_headers(items: list[HeaderItem]) -> list[Classification]:
    return await _run(items, HEADERS_BATCH, HEADERS_MODEL)


async def classify_full(items: list[FullItem]) -> list[Classification]:
    cut = [
        FullItem(it.message_id, it.from_name, it.from_addr, it.subject, it.preview,
                 (it.body_text or "")[:BODY_MAX_CHARS])
        for it in items
    ]
    return await _run(cut, FULL_BATCH, FULL_MODEL)
