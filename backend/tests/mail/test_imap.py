from fakes import FakeMailSession

from app.mail.imap import (
    MailAuthError, MailConnectError, MailError, decode_header_value, parse_address,
    extract_preview, has_attachments_from_structure,
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
