from __future__ import annotations

from enum import Enum


class VerificationLevel(str, Enum):
    VERIFIED_PRIMARY = "VERIFIED_PRIMARY"
    VERIFIED_SECONDARY = "VERIFIED_SECONDARY"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"

