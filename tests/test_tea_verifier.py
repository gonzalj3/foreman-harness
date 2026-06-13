"""Integration tests for the real TEA VirtCert verifier, using saved HTML fixtures
(offline + deterministic). The live path is exercised separately/manually so the
suite never depends on a government website being up.
"""
import os

from education_applicant_verifier.types import CredStatus
from education_applicant_verifier.verifier import TEACredentialVerifier

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "tea")


def verifier():
    return TEACredentialVerifier(mode="fixture", fixture_dir=FIX)


def test_real_educator_parses_as_valid():
    r = verifier().verify(None, "Adrian Edmonds")
    assert r.status == CredStatus.VALID
    assert r.holder_name and "Edmonds" in r.holder_name
    assert r.expires  # an expiration date was parsed
    assert r.cert_type and "Classroom Teacher" in r.cert_type


def test_certified_subject_areas_are_parsed():
    r = verifier().verify(None, "Adrian Edmonds")
    # the verifier captures the certified subjects/grades, not just "valid"
    assert "Mathematics" in r.certifications
    assert "Generalist" in r.certifications
    # Adrian is NOT science-certified -> a science role should not match
    assert not any("Science" in c and "Second Language" not in c for c in r.certifications)
    assert r.grade_bands  # e.g. 4-8, 7-12


def test_unknown_educator_parses_as_not_found():
    r = verifier().verify(None, "Nobody Zzqxbogusname")
    assert r.status == CredStatus.NOT_FOUND


def test_caches_by_name():
    v = verifier()
    v.verify(None, "Adrian Edmonds")
    v.verify(None, "Adrian Edmonds")
    assert v.calls == 2  # both calls counted, second served from cache (no re-read)


def test_name_split():
    assert TEACredentialVerifier._split_name("Adrian Edmonds") == ("Adrian", "Edmonds")
    assert TEACredentialVerifier._split_name("Adrian E Edmonds") == ("Adrian", "Edmonds")
