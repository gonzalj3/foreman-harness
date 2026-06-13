"""Credential verifiers (the tool). Swappable behind the CredentialVerifier protocol.

FakeCredentialVerifier mimics a TEA-style registry lookup with an in-memory
table, covering every status the harness must handle: valid, expired, not-found,
name-mismatch (fraud), and unavailable. It counts calls so tests can prove that
replay skips re-verification.

TEACredentialVerifier (real ECOS VirtCert) is a later drop-in behind the same
interface.
"""
from __future__ import annotations

import html as _html
import http.cookiejar
import os
import re
import urllib.parse
import urllib.request
from typing import Optional

from .types import CredentialResult, CredStatus


DEFAULT_TABLE: dict[str, dict] = {
    "TX-100": {"status": "valid", "holder": "Maria Alvarez", "type": "Standard Teaching", "expires": "2027-08-01"},
    "TX-200": {"status": "valid", "holder": "James Chen", "type": "Standard Teaching", "expires": "2026-12-01"},
    "TX-300": {"status": "expired", "holder": "Robert Diaz", "type": "Paraprofessional", "expires": "2024-05-01"},
    "TX-500": {"status": "unavailable"},
    # certs not present in the table resolve to NOT_FOUND
}


class FakeCredentialVerifier:
    name = "fake-tea-verifier-v1"

    def __init__(self, table: Optional[dict] = None) -> None:
        self.calls = 0
        self.table = DEFAULT_TABLE if table is None else table

    def verify(self, cert_id: Optional[str], applicant_name: str) -> CredentialResult:
        self.calls += 1
        if not cert_id:
            return CredentialResult(cert_id, CredStatus.NOT_FOUND)

        record = self.table.get(cert_id)
        if record is None:
            return CredentialResult(cert_id, CredStatus.NOT_FOUND)

        status = record["status"]
        if status == "unavailable":
            return CredentialResult(cert_id, CredStatus.UNAVAILABLE)
        if status == "expired":
            return CredentialResult(
                cert_id, CredStatus.EXPIRED,
                holder_name=record.get("holder"), cert_type=record.get("type"),
                expires=record.get("expires"),
            )

        # status == "valid": the cert is real — does the holder match the applicant?
        holder = record.get("holder")
        if holder and applicant_name and holder.strip().lower() != applicant_name.strip().lower():
            return CredentialResult(
                cert_id, CredStatus.MISMATCH,
                holder_name=holder, cert_type=record.get("type"), expires=record.get("expires"),
            )
        return CredentialResult(
            cert_id, CredStatus.VALID,
            holder_name=holder, cert_type=record.get("type"), expires=record.get("expires"),
        )


class TEACredentialVerifier:
    """Real verifier against the Texas Education Agency ECOS VirtCert public lookup.

    The lookup is a plain HTML POST (LastName/FirstName/MiddleName) — no API, no
    viewstate — so this runs with stdlib only (works on serverless). Same
    CredentialVerifier interface as the fake, so it drops into the harness with no
    other changes.

    mode:
      "auto"    — try the live lookup, fall back to a saved fixture on failure
      "live"    — live only
      "fixture" — read saved HTML fixtures only (offline, deterministic for tests/demo)
    """

    name = "tea-virtcert-verifier-v1"
    URL = "https://tealprod.tea.state.tx.us/ECOS-External/EcosOnline/VirtCert"
    UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120 Safari/537.36")

    def __init__(self, mode: str = "auto", fixture_dir: Optional[str] = None, timeout: int = 12) -> None:
        self.mode = mode
        self.fixture_dir = fixture_dir
        self.timeout = timeout
        self.calls = 0
        self._cache: dict[str, CredentialResult] = {}

    # --- name handling ---

    @staticmethod
    def _split_name(applicant_name: str) -> tuple[str, str]:
        parts = [p for p in applicant_name.strip().split() if p]
        if not parts:
            return "", ""
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], parts[-1]  # (first, last)

    def _fixture_path(self, first: str, last: str) -> Optional[str]:
        if not self.fixture_dir:
            return None
        return os.path.join(self.fixture_dir, f"{last.lower()}_{first.lower()}.html")

    def _read_fixture(self, first: str, last: str) -> Optional[str]:
        path = self._fixture_path(first, last)
        if path and os.path.exists(path):
            with open(path, encoding="utf-8", errors="ignore") as f:
                return f.read()
        return None

    def _fetch_live(self, first: str, last: str) -> str:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        opener.addheaders = [("User-Agent", self.UA)]
        opener.open(self.URL, timeout=self.timeout).read()  # prime session cookies
        data = urllib.parse.urlencode(
            {"LastName": last, "FirstName": first, "MiddleName": "", "btnSearch": "Search"}
        ).encode()
        resp = opener.open(self.URL, data=data, timeout=self.timeout)
        return resp.read().decode("utf-8", errors="ignore")

    # --- interface ---

    def verify(self, cert_id: Optional[str], applicant_name: str) -> CredentialResult:
        self.calls += 1
        key = applicant_name.strip().lower()
        if key in self._cache:
            return self._cache[key]

        first, last = self._split_name(applicant_name)
        html_text: Optional[str] = None

        if self.mode == "fixture":
            html_text = self._read_fixture(first, last)
        else:
            if self.mode in ("auto", "live"):
                try:
                    html_text = self._fetch_live(first, last)
                except Exception:
                    html_text = None
            if html_text is None and self.mode == "auto":
                html_text = self._read_fixture(first, last)

        if html_text is None:
            result = CredentialResult(cert_id, CredStatus.UNAVAILABLE)
        else:
            result = self._parse(html_text, cert_id)

        self._cache[key] = result
        return result

    @staticmethod
    def _parse(html_text: str, cert_id: Optional[str]) -> CredentialResult:
        # subject areas + grade bands come from the certificate table cells (parsed
        # from raw HTML before tags are stripped).
        areas: list[str] = []
        for cell in re.findall(r'<td class="style25"[^>]*>([^<]+)</td>', html_text):
            a = _html.unescape(cell).strip()
            if (not a or re.match(r"\d{2}/\d{2}/\d{4}", a) or a in ("Valid", "Expired")
                    or a.startswith("Grades") or a == "Classroom Teacher"):
                continue
            if a not in areas:
                areas.append(a)
        grade_bands = sorted(set(re.findall(r"Grades \(([^)]+)\)", html_text)))

        text = _html.unescape(re.sub(r"<[^>]+>", " ", html_text))
        text = re.sub(r"\s+", " ", text).strip()

        if "Did Not Locate Any Educators" in text or "Did Not Locate" in text:
            return CredentialResult(cert_id, CredStatus.NOT_FOUND)

        m = re.search(r"This certifies that\s+(.+?)\s+has fulfilled", text)
        holder = m.group(1).strip() if m else None

        dates = re.findall(r"\d{2}/\d{2}/\d{4}", text)
        expires = max(dates, key=lambda d: (d[6:10], d[0:2], d[3:5])) if dates else None
        cert_type = "Standard - Classroom Teacher" if "Classroom Teacher" in text else None

        if re.search(r"\bValid\b", text):
            status = CredStatus.VALID
        elif re.search(r"\b(Expired|Inactive)\b", text):
            status = CredStatus.EXPIRED
        elif holder is not None:
            status = CredStatus.VALID
        else:
            status = CredStatus.NOT_FOUND

        return CredentialResult(cert_id, status, holder_name=holder, cert_type=cert_type,
                                expires=expires, certifications=areas, grade_bands=grade_bands)
