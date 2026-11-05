import pytest

from app.mail.folders import detect_role


@pytest.mark.parametrize(
    "path,flags,expected",
    [
        ("INBOX", [], "inbox"),
        ("[Gmail]/Corbeille", [], "trash"),
        ("[Gmail]/Trash", ["\\Trash"], "trash"),
        ("Éléments supprimés", [], "trash"),
        ("Deleted Messages", [], "trash"),
        ("INBOX.Trash", [], "trash"),
        ("[Gmail]/Tous les messages", ["\\All"], "archive"),
        ("Courrier indésirable", [], "junk"),
        ("Brouillons", [], "drafts"),
        ("Sent Messages", [], "sent"),
        ("Factures", [], "custom"),
        ("[Gmail]", ["\\Noselect"], None),
    ],
)
def test_detect_role(path, flags, expected):
    assert detect_role(path, flags) == expected


def test_special_use_flag_wins_over_name():
    assert detect_role("Factures", ["\\Sent"]) == "sent"


def test_noselect_case_insensitive():
    assert detect_role("INBOX", ["\\NoSelect"]) is None
