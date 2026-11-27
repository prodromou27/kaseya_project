"""The safe fingerprint of a 2xx answer: title, named headers and cookie names only - never the body or values."""

from __future__ import annotations

from apps.integrations.vsa.answer import describe, fingerprint


class _Resp:
    def __init__(self, headers, content=b""):
        self.headers = headers
        self.content = content


def test_identifies_a_waf_block_page_without_keeping_the_body():
    resp = _Resp(
        {
            "Content-Type": "text/html",
            "Server": "BigIP",
            "Set-Cookie": "TS01abc123=secretvalue; path=/, other=xyz",
            "X-Powered-By": "should-be-ignored-not-in-allowlist" and "ignored",
        },
        content=b"<html><head><title>Request Rejected</title></head><body>The requested URL was rejected. "
        b"Support ID: 12345. secretcustomerdata</body></html>",
    )
    fp = fingerprint(resp)
    assert fp["title"] == "Request Rejected"
    assert fp["headers"]["Server"] == "BigIP"
    assert fp["cookie_names"] == ["TS01abc123", "other"]  # names only
    text = describe(fp)
    assert 'page title "Request Rejected"' in text
    assert "Server: BigIP" in text
    assert "TS01abc123" in text
    # The body, the cookie value and the support-page text never appear.
    assert "secretvalue" not in text
    assert "secretcustomerdata" not in str(fp)
    assert "Support ID" not in str(fp)


def test_empty_for_a_plain_answer_and_none():
    assert fingerprint(_Resp({"Content-Type": "application/json"}, b"{}")) == {
        "title": "",
        "headers": {},
        "cookie_names": [],
    }
    assert describe(None) == ""
    assert describe({"title": "", "headers": {}, "cookie_names": []}) == ""
