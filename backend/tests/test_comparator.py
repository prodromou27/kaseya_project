"""P1-07 comparator edge cases (TESTING.md SOFT-01..04). Pure unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.software.comparator import (
    AliasRule,
    ExceptionInfo,
    ProductInfo,
    Reason,
    RevisionInfo,
    classify,
    compare_versions,
    parse_dotted,
)

NOW = datetime(2026, 11, 12, tzinfo=UTC)
CHROME, CHROME_BETA, FF, FF_ESR, ZIP_X64 = "chrome", "chrome-beta", "firefox", "firefox-esr", "7zip-x64"

PRODUCTS = {
    CHROME: ProductInfo(CHROME, "any"),
    CHROME_BETA: ProductInfo(CHROME_BETA, "any"),
    FF: ProductInfo(FF, "any"),
    FF_ESR: ProductInfo(FF_ESR, "any"),
    ZIP_X64: ProductInfo(ZIP_X64, "x64"),
}
ALIASES = [
    AliasRule(CHROME, "Google Chrome", "Google LLC", "exact"),
    AliasRule(CHROME_BETA, "Google Chrome Beta", "", "exact"),
    AliasRule(FF, "Mozilla Firefox (", "", "prefix"),
    AliasRule(FF_ESR, "Mozilla Firefox ESR", "", "prefix"),
    AliasRule(ZIP_X64, "7-Zip", "", "prefix"),
]
REVISIONS = [
    RevisionInfo("r-chrome-old", CHROME, "130.0.6723.117", "dotted_numeric", NOW - timedelta(days=30)),
    RevisionInfo("r-chrome", CHROME, "131.0.6778.86", "dotted_numeric", NOW - timedelta(days=1)),
    RevisionInfo("r-chrome-future", CHROME, "132.0.1.1", "dotted_numeric", NOW + timedelta(days=5)),
    RevisionInfo("r-beta", CHROME_BETA, "132.0.6834.15", "dotted_numeric", NOW - timedelta(days=1)),
    RevisionInfo("r-ff", FF, "132.0.2", "dotted_numeric", NOW - timedelta(days=1)),
    RevisionInfo("r-esr", FF_ESR, "128.4.0", "dotted_numeric", NOW - timedelta(days=1)),
    RevisionInfo("r-zip", ZIP_X64, "24.08", "dotted_numeric", NOW - timedelta(days=1)),
]


def run(
    name: str,
    version: str,
    publisher: str = "",
    *,
    aliases=ALIASES,
    revisions=REVISIONS,
    exceptions=(),
    asset_id: str = "asset-1",
):
    return classify(
        name=name,
        publisher=publisher,
        version=version,
        asset_id=asset_id,
        aliases=aliases,
        products=PRODUCTS,
        revisions=revisions,
        exceptions=list(exceptions),
        at=NOW,
    )


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("10.0.19045.3803", "10.0.19045.3803", 0),
        ("10.0.19045.3803", "10.0.19045.4046", -1),
        ("10.0.22621.1", "10.0.19045.9999", 1),  # numeric, not lexicographic
        ("131.0.6778.9", "131.0.6778.86", -1),
        ("1.2", "1.2.0.0", 0),
        ("1.10", "1.9", 1),
        ("v8.7.1", "8.7.1", 0),
        ("24.08", "24.8", 0),  # leading zeros are numeric
    ],
)
def test_four_part_and_numeric_comparison(a, b, expected):
    """SOFT-01."""
    assert compare_versions(a, b) == expected


@pytest.mark.parametrize(
    "bad", ["", "1.2.3 (64-bit)", "unknown build", "1..2", "1.2.3.4.5.6.7", "1.2-beta", "abc", "133.0b5", "1.0.0-rc1"]
)
def test_unparseable_versions(bad):
    assert parse_dotted(bad) is None


def test_states_current_outdated_newer():
    assert run("Google Chrome", "131.0.6778.86", "Google LLC").state == "current"
    r = run("Google Chrome", "130.0.6723.117", "Google LLC")
    assert (r.state, r.reason_code, r.revision_id) == ("outdated", Reason.LOWER, "r-chrome")
    assert run("Google Chrome", "131.0.6778.100", "Google LLC").state == "newer"


def test_future_effective_revision_not_applied():
    assert run("Google Chrome", "131.0.6778.86", "Google LLC").revision_id == "r-chrome"


def test_channels_never_cross_compared():
    """SOFT-02: Chrome stable vs beta, Firefox release vs ESR."""
    beta = run("Google Chrome Beta", "132.0.6834.15")
    assert (beta.state, beta.product_id) == ("current", CHROME_BETA)
    esr = run("Mozilla Firefox ESR (x64 en-US)", "128.4.0")
    assert (esr.state, esr.product_id) == ("current", FF_ESR)  # would be "outdated" if compared to release 132
    rel = run("Mozilla Firefox (x64 en-US)", "131.0.3")
    assert (rel.state, rel.product_id) == ("outdated", FF)


def test_architecture_specific_reference_is_unknown():
    """SOFT-02: VSA does not report architecture, so x64-only references are not applied."""
    r = run("7-Zip 24.08 (x64)", "23.01")
    assert (r.state, r.reason_code) == ("unknown", Reason.ARCH_UNVERIFIABLE)


def test_publisher_must_match_when_specified():
    r = run("Google Chrome", "131.0.6778.86", "Evil Corp")
    assert (r.state, r.reason_code) == ("unsupported", Reason.NO_ALIAS)


def test_ambiguous_alias_is_unknown():
    aliases = [*ALIASES, AliasRule(FF_ESR, "Mozilla Firefox", "", "prefix")]
    r = run("Mozilla Firefox (x64 en-US)", "132.0.2", aliases=aliases)
    assert (r.state, r.reason_code) == ("unknown", Reason.AMBIGUOUS_ALIAS)


@pytest.mark.parametrize(
    ("name", "version", "reason"),
    [
        ("Google Chrome", "", Reason.MISSING_VERSION),
        ("Google Chrome", "unknown build", Reason.UNPARSEABLE_VERSION),
        ("Mozilla Firefox (x64 en-US)", "133.0b5", Reason.PRERELEASE_VERSION),
    ],
)
def test_missing_or_unparseable_version_is_unknown(name, version, reason):
    """SOFT-03."""
    r = run(name, version, "Google LLC" if "Chrome" in name else "")
    assert (r.state, r.reason_code) == ("unknown", reason)


def test_uncatalogued_product_is_unsupported():
    assert run("Contoso Line-of-Business Agent", "4.2").state == "unsupported"


def test_catalogued_product_without_revision_is_unknown():
    r = run("Google Chrome", "131.0.6778.86", "Google LLC", revisions=[])
    assert (r.state, r.reason_code) == ("unknown", Reason.NO_REVISION)


def test_two_revisions_effective_at_same_instant_are_ambiguous():
    same = NOW - timedelta(days=1)
    revs = [
        RevisionInfo("x", CHROME, "1.0", "dotted_numeric", same),
        RevisionInfo("y", CHROME, "2.0", "dotted_numeric", same),
    ]
    assert run("Google Chrome", "1.0", "Google LLC", revisions=revs).reason_code == Reason.AMBIGUOUS_REVISION


def test_unsupported_scheme_and_bad_reference_are_unknown():
    revs = [RevisionInfo("x", CHROME, "2024-R3", "calendar", NOW)]
    assert run("Google Chrome", "1.0", "Google LLC", revisions=revs).reason_code == Reason.UNSUPPORTED_SCHEME
    revs = [RevisionInfo("x", CHROME, "latest", "dotted_numeric", NOW)]
    assert run("Google Chrome", "1.0", "Google LLC", revisions=revs).reason_code == Reason.UNPARSEABLE_REFERENCE


def test_exceptions_exclude_by_product_or_asset():
    """SOFT-04 (raw observation unchanged is asserted in the service tests)."""
    customer_wide = ExceptionInfo("e1", CHROME, None)
    r = run("Google Chrome", "100.0", "Google LLC", exceptions=[customer_wide])
    assert (r.state, r.exception_id) == ("excluded", "e1")
    asset_only = ExceptionInfo("e2", CHROME, "asset-9")
    assert run("Google Chrome", "100.0", "Google LLC", exceptions=[asset_only]).state == "outdated"
    assert run("Google Chrome", "100.0", "Google LLC", exceptions=[asset_only], asset_id="asset-9").state == "excluded"


def test_matching_is_case_and_whitespace_insensitive():
    assert run("  google chrome ", "131.0.6778.86", "GOOGLE LLC").state == "current"
