"""Credential verifiers (the tool). Swappable behind the CredentialVerifier protocol.

FakeCredentialVerifier mimics a TEA-style registry lookup with an in-memory
table, covering every status the harness must handle: valid, expired, not-found,
name-mismatch (fraud), and unavailable. It counts calls so tests can prove that
replay skips re-verification.

TEACredentialVerifier (real ECOS VirtCert) is a later drop-in behind the same
interface.
"""
from __future__ import annotations

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
