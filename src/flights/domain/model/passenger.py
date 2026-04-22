"""PassengerDetails (scaffold)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

__SCAFFOLD__ = True


@dataclass(frozen=True, slots=True)
class PassengerDetails:
    full_name: str
    date_of_birth: date | None = None
    passport_number: str | None = None
