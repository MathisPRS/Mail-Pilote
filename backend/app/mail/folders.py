import re
import unicodedata

_SPECIAL_USE = {
    "\\inbox": "inbox",
    "\\drafts": "drafts",
    "\\sent": "sent",
    "\\junk": "junk",
    "\\archive": "archive",
    "\\all": "archive",
    "\\trash": "trash",
}

_NAMES = {
    "inbox": ["inbox"],
    "drafts": ["drafts", "draft", "brouillons"],
    "sent": ["sent", "sent items", "sent messages", "envoyes", "elements envoyes", "messages envoyes"],
    "junk": ["junk", "spam", "indesirables", "courrier indesirable", "bulk mail"],
    "trash": ["trash", "corbeille", "deleted", "deleted items", "deleted messages", "elements supprimes"],
    "archive": ["archive", "archives", "all mail", "tous les messages"],
}
_BY_NAME = {name: role for role, names in _NAMES.items() for name in names}


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def detect_role(path: str, flags: list[str]) -> str | None:
    lowered = [f.lower() for f in flags]
    if "\\noselect" in lowered:
        return None
    for f in lowered:
        if f in _SPECIAL_USE:
            return _SPECIAL_USE[f]
    last = re.split(r"[/.]", path)[-1]
    return _BY_NAME.get(_normalize(last), "custom")
