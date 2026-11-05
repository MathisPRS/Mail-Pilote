import pytest
from fakes import FakeMailSession

from app.mail.imap import (
    MailAuthError, MailConnectError, MailError, decode_header_value, parse_address,
    extract_preview, find_text_part, has_attachments_from_structure,
)


def test_decodes_rfc2047_subject():
    assert decode_header_value("=?utf-8?q?R=C3=A9union?=") == "Réunion"


def test_decode_invalid_charset_does_not_raise():
    out = decode_header_value("=?x-unknown-charset?q?caf=E9?= suite")
    assert isinstance(out, str) and "suite" in out


def test_decode_plain_and_empty():
    assert decode_header_value("Hello") == "Hello"
    assert decode_header_value("") == ""
    assert decode_header_value(None) == ""


def test_decode_bytes_with_bad_utf8():
    assert isinstance(decode_header_value(b"caf\xe9"), str)


def test_parse_address():
    assert parse_address("=?utf-8?q?Jos=C3=A9?= <Jose@Example.com>") == ("José", "jose@example.com")
    assert parse_address("bob@example.com") == ("", "bob@example.com")
    assert parse_address("") == ("", "")


def test_extract_preview_text_and_truncation():
    assert extract_preview(b"Hello   world\r\n\r\nline2", "utf-8") == "Hello world line2"
    assert len(extract_preview(b"a " * 500, "utf-8")) == 200


def test_extract_preview_html_and_bad_charset():
    assert extract_preview(b"<p>Hi <b>there</b></p><style>x{}</style>", "utf-8", is_html=True) == "Hi there"
    assert isinstance(extract_preview(b"caf\xe9", "nope"), str)


def test_exceptions_hierarchy():
    assert issubclass(MailAuthError, MailError) and issubclass(MailConnectError, MailError)


def test_has_attachments_from_structure():
    plain = (b"text", b"plain", (b"charset", b"utf-8"), None, None, b"7bit", 10, 1)
    pdf = (b"application", b"pdf", (b"name", b"a.pdf"), None, None, b"base64", 100)
    assert not has_attachments_from_structure(plain)
    assert has_attachments_from_structure([plain, pdf, b"mixed"])


def test_fake_session_contract():
    s = FakeMailSession(folders={"INBOX": [], "[Gmail]/Corbeille": ["\\Trash"]}, uidvalidity=9)
    uid = s.add_message("INBOX", subject="Réunion", preview="x" * 300)
    assert s.select("INBOX") == 9
    headers = s.fetch_headers("INBOX", 0)
    assert [h.uid for h in headers] == [uid]
    assert headers[0].seen is False and len(headers[0].preview) == 200
    assert s.messages["INBOX"][uid]["seen"] is False
    assert s.fetch_headers("INBOX", uid) == []
    s.set_seen("INBOX", uid, True)
    assert s.fetch_headers("INBOX", 0)[0].seen is True
    new_uid = s.move("INBOX", uid, "[Gmail]/Corbeille")
    assert s.fetch_headers("INBOX", 0) == []
    assert s.fetch_headers("[Gmail]/Corbeille", 0)[0].uid == new_uid
    assert s.moves == [("INBOX", uid, "[Gmail]/Corbeille", new_uid)]


# ---- realistic imapclient-shaped BODYSTRUCTURE ----
_TXT = (b"text", b"plain", (b"charset", b"utf-8"), None, None, b"7bit", 10, 1, None, None, None, None)
_HTM = (b"text", b"html", (b"charset", b"utf-8"), None, None, b"7bit", 20, 1, None, None, None, None)
_PDF = (b"application", b"pdf", (b"name", b"a.pdf"), None, None, b"base64", 100, None,
        (b"attachment", (b"filename", b"a.pdf")), None, None)


def test_alternative_with_boundary_params_has_no_attachment():
    struct = (_TXT, _HTM, b"alternative", (b"boundary", b"xyz"), None, None)
    assert has_attachments_from_structure(struct) is False
    assert find_text_part(struct) == ("1", False, "utf-8", "7bit")


def test_mixed_with_pdf_attachment():
    struct = (_TXT, _PDF, b"mixed", (b"boundary", b"xyz"), (b"inline", None), None)
    assert has_attachments_from_structure(struct) is True
    assert find_text_part(struct)[0] == "1"


def test_nested_alternative_in_mixed_part_numbers():
    alt = (_TXT, _HTM, b"alternative", (b"boundary", b"b"), None, None)
    struct = (alt, _PDF, b"mixed", (b"boundary", b"a"), None, None)
    assert find_text_part(struct)[0] == "1.1"


# ---- real session move(): never a permanent delete ----
from unittest.mock import MagicMock

from app.mail.imap import ImapClientSession


def _client(caps):
    c = MagicMock()
    c.select_folder.return_value = {b"UIDVALIDITY": 1}
    c.has_capability.side_effect = lambda n: n in caps
    return c


def test_move_with_move_capability_uses_move_only():
    c = _client({"MOVE"})
    c.move.return_value = b"Move completed"
    ImapClientSession(c).move("INBOX", 5, "Trash")
    c.move.assert_called_once_with([5], "Trash")
    c.uid_expunge.assert_not_called()
    c.expunge.assert_not_called()
    c.copy.assert_not_called()


def test_move_uidplus_fallback_expunges_only_that_uid():
    c = _client({"UIDPLUS"})
    order = MagicMock()
    c.copy.side_effect = lambda *a: (order.copy(), b"[COPYUID 7 5 42] Copy completed")[1]
    c.add_flags.side_effect = lambda *a: order.flag()
    c.uid_expunge.side_effect = lambda *a: order.expunge()
    new = ImapClientSession(c).move("INBOX", 5, "Trash")
    assert new == 42
    c.copy.assert_called_once_with([5], "Trash")
    c.add_flags.assert_called_once_with([5], [b"\\Deleted"])
    c.uid_expunge.assert_called_once_with([5])
    c.expunge.assert_not_called()
    assert [x[0] for x in order.method_calls] == ["copy", "flag", "expunge"]


def test_move_without_move_or_uidplus_refuses():
    c = _client(set())
    with pytest.raises(MailError):
        ImapClientSession(c).move("INBOX", 5, "Trash")
    for m in (c.copy, c.add_flags, c.uid_expunge, c.expunge, c.move):
        m.assert_not_called()
