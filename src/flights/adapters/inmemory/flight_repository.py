"""InMemoryFlightRepository.

Thread-safe in-memory store. Linear-scan search is acceptable at this scale
(ADR-008 defers indexing until load profile demands it).
"""

from __future__ import annotations

import threading

from flights.domain.model.flight import Flight
from flights.domain.model.ids import FlightId


class InMemoryFlightRepository:
    def __init__(self) -> None:
        self._flights: dict[FlightId, Flight] = {}
        self._lock = threading.RLock()

    def get(self, flight_id: FlightId) -> Flight | None:
        with self._lock:
            return self._flights.get(flight_id)

    def search(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        airline: str | None = None,
    ) -> list[Flight]:
        with self._lock:
            return [
                flight
                for flight in self._flights.values()
                if flight.origin == origin
                and flight.destination == destination
                and flight.departure_at.date().isoformat() == departure_date
                and (airline is None or flight.airline == airline)
            ]

    def add(self, flight: Flight) -> None:
        with self._lock:
            self._flights[flight.id] = flight
