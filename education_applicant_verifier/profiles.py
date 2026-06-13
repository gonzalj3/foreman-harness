"""Role Profiles — the versatility mechanism.

A RoleProfile bundles everything role-specific: the rubric, whether a credential
is required, the verifier (tool), pass bar, retry budget, and guardrail config.
The harness runs against a profile; swapping the profile retargets it (e.g.
teacher -> cafeteria worker) with no harness changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .types import CredentialVerifier


@dataclass
class RoleProfile:
    name: str
    rubric: list[str]
    required_credential: bool
    verifier: CredentialVerifier
    pass_score: int = 6
    max_attempts: int = 3
    guardrail_config: dict = field(default_factory=dict)


def teacher_profile(verifier: CredentialVerifier) -> RoleProfile:
    return RoleProfile(
        name="Texas Educator",
        rubric=["experience", "fit"],
        required_credential=True,
        verifier=verifier,
        pass_score=6,
        max_attempts=3,
    )


def teacher_profile_tea(mode: str = "auto", fixture_dir: str | None = None) -> RoleProfile:
    """Teacher profile backed by the real TEA VirtCert verifier."""
    from .verifier import TEACredentialVerifier

    return teacher_profile(TEACredentialVerifier(mode=mode, fixture_dir=fixture_dir))
