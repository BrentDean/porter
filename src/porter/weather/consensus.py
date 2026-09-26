from __future__ import annotations

from dataclasses import dataclass, replace
from math import atan2, cos, degrees, radians, sin, sqrt
from statistics import median

from porter.weather.composite import WeatherAgreement
from porter.weather.current import CurrentConditions, CurrentWeatherComparison


@dataclass(frozen=True, slots=True)
class CurrentSourceEvidence:
    source: str
    family: str
    kind: str
    temperature_f: float | None
    humidity_percent: float | None
    apparent_temperature_f: float | None
    wind_speed_mph: float | None
    wind_direction_degrees: float | None
    condition: str | None
    observed_at: str | None
    station_id: str | None
    distance_miles: float | None
    age_minutes: float | None
    accepted: bool
    base_weight: float
    distance_factor: float
    freshness_factor: float
    weight: float
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CurrentWeatherEstimate:
    temperature_f: float
    humidity_percent: float | None
    apparent_temperature_f: float | None
    wind_speed_mph: float | None
    wind_direction_degrees: float | None
    condition: str | None
    confidence: WeatherAgreement
    raw_temperature_spread_f: float | None
    accepted_temperature_spread_f: float | None
    evidence: tuple[CurrentSourceEvidence, ...]

    @property
    def accepted_source_count(self) -> int:
        return sum(item.accepted for item in self.evidence)

    @property
    def rejected_source_count(self) -> int:
        return sum(not item.accepted for item in self.evidence)

    @property
    def accepted_family_count(self) -> int:
        return len({item.family for item in self.evidence if item.accepted})


class CurrentConsensusEngine:
    """Produce Porter's current-condition estimate from normalized source evidence."""

    _BASE_WEIGHTS = {
        "nws-observation": 1.0,
        "synoptic-local-observation": 0.90,
        "open-meteo-current": 0.65,
        "open-meteo-hrrr-current": 0.80,
        "open-meteo-nbm-current": 0.75,
        "open-meteo-ecmwf-current": 0.65,
    }
    _FAMILY_CAPS = {
        "nws-observation": 1.0,
        "local-observation": 0.95,
        "open-meteo-best-match": 0.65,
        "noaa-model": 0.90,
        "ecmwf-model": 0.65,
    }
    _SOURCE_FAMILIES = {
        "nws-observation": "nws-observation",
        "synoptic-local-observation": "local-observation",
        "open-meteo-current": "open-meteo-best-match",
        "open-meteo-hrrr-current": "noaa-model",
        "open-meteo-nbm-current": "noaa-model",
        "open-meteo-ecmwf-current": "ecmwf-model",
    }
    _DEFAULT_WEIGHT = 0.8
    _CLUSTER_WIDTH_F = 3.0
    _MIN_ISOLATION_GAP_F = 4.0
    _DISTANCE_SCALE_MILES = 10.0

    def estimate(self, comparison: CurrentWeatherComparison) -> CurrentWeatherEstimate:
        temperature_sources = tuple(
            item for item in comparison.conditions if item.temperature_f is not None
        )
        if not temperature_sources:
            raise RuntimeError("current weather sources are missing temperature")

        rejected_sources = self._temperature_outliers(temperature_sources)
        raw_evidence = tuple(
            self._evidence(
                item,
                self._evidence_key(item) in rejected_sources,
            )
            for item in comparison.conditions
        )
        evidence = self._cap_family_influence(raw_evidence)
        accepted = tuple(item for item in evidence if item.accepted)
        accepted_temperature = tuple(
            item for item in accepted if item.temperature_f is not None
        )
        if not accepted_temperature:
            raise RuntimeError("current weather consensus rejected every temperature source")

        accepted_spread = self._spread(
            item.temperature_f for item in accepted_temperature
        )
        accepted_family_count = len({item.family for item in accepted_temperature})
        temperature_f = self._weighted_average(
            accepted_temperature,
            "temperature_f",
        )
        humidity_percent = self._weighted_optional_average(
            accepted,
            "humidity_percent",
        )
        wind_speed_mph = self._weighted_optional_average(
            accepted,
            "wind_speed_mph",
        )

        return CurrentWeatherEstimate(
            temperature_f=temperature_f,
            humidity_percent=humidity_percent,
            apparent_temperature_f=self._apparent_temperature(
                temperature_f=temperature_f,
                humidity_percent=humidity_percent,
                wind_speed_mph=wind_speed_mph,
            ),
            wind_speed_mph=wind_speed_mph,
            wind_direction_degrees=self._weighted_direction(accepted),
            condition=self._preferred_condition(accepted),
            confidence=self._confidence(
                family_count=accepted_family_count,
                spread_f=accepted_spread,
            ),
            raw_temperature_spread_f=comparison.temperature_spread_f,
            accepted_temperature_spread_f=accepted_spread,
            evidence=evidence,
        )

    @classmethod
    def _temperature_outliers(
        cls,
        conditions: tuple[CurrentConditions, ...],
    ) -> frozenset[tuple[str, str | None]]:
        """Reject isolated stations first, then isolated independent source families.

        Several stations from one provider are useful corroborating observations, but
        they must not masquerade as several independent source families. Cross-source
        rejection therefore requires at least three distinct families.
        """
        rejected: set[tuple[str, str | None]] = set()
        grouped: dict[str, list[CurrentConditions]] = {}
        for item in conditions:
            grouped.setdefault(cls._source_family(item), []).append(item)

        for family_conditions in grouped.values():
            station_values = tuple(
                (
                    cls._evidence_key(item),
                    float(item.temperature_f),
                )
                for item in family_conditions
                if item.temperature_f is not None
            )
            rejected.update(cls._isolated_keys(station_values))

        remaining = tuple(
            item
            for item in conditions
            if cls._evidence_key(item) not in rejected
            and item.temperature_f is not None
        )
        remaining_by_family: dict[str, list[float]] = {}
        for item in remaining:
            remaining_by_family.setdefault(cls._source_family(item), []).append(
                float(item.temperature_f)
            )

        family_values = tuple(
            (family, float(median(values)))
            for family, values in remaining_by_family.items()
        )
        rejected_families = cls._isolated_keys(family_values)
        if rejected_families:
            rejected.update(
                cls._evidence_key(item)
                for item in remaining
                if cls._source_family(item) in rejected_families
            )

        return frozenset(rejected)

    @classmethod
    def _isolated_keys(
        cls,
        values: tuple[tuple[object, float], ...],
    ) -> frozenset[object]:
        if len(values) < 3:
            return frozenset()

        ordered = tuple(sorted(values, key=lambda item: item[1]))
        candidates: list[tuple[tuple[object, float], ...]] = []
        for start in range(len(ordered)):
            for end in range(start + 1, len(ordered)):
                if ordered[end][1] - ordered[start][1] <= cls._CLUSTER_WIDTH_F:
                    candidates.append(ordered[start : end + 1])

        if not candidates:
            return frozenset()

        largest_size = max(len(candidate) for candidate in candidates)
        minimum_cluster_size = max(2, (len(values) // 2) + 1)
        if largest_size < minimum_cluster_size:
            return frozenset()

        largest = tuple(
            candidate for candidate in candidates if len(candidate) == largest_size
        )
        if len(largest) != 1:
            return frozenset()

        cluster = largest[0]
        cluster_keys = {item[0] for item in cluster}
        cluster_low = min(item[1] for item in cluster)
        cluster_high = max(item[1] for item in cluster)

        rejected: set[object] = set()
        for key, value in values:
            if key in cluster_keys:
                continue
            gap = min(abs(value - cluster_low), abs(value - cluster_high))
            if gap >= cls._MIN_ISOLATION_GAP_F:
                rejected.add(key)
        return frozenset(rejected)

    @classmethod
    def _evidence(
        cls,
        item: CurrentConditions,
        rejected: bool,
    ) -> CurrentSourceEvidence:
        family = cls._source_family(item)
        base_weight = cls._BASE_WEIGHTS.get(item.source, cls._DEFAULT_WEIGHT)
        distance_factor = cls._distance_factor(item)
        freshness_factor = cls._freshness_factor(item)
        effective_weight = base_weight * distance_factor * freshness_factor

        return CurrentSourceEvidence(
            source=item.source,
            family=family,
            kind=cls._source_kind(item),
            temperature_f=item.temperature_f,
            humidity_percent=item.humidity_percent,
            apparent_temperature_f=item.apparent_temperature_f,
            wind_speed_mph=item.wind_speed_mph,
            wind_direction_degrees=item.wind_direction_degrees,
            condition=item.condition,
            observed_at=item.observed_at,
            station_id=item.station_id,
            distance_miles=item.distance_miles,
            age_minutes=item.age_minutes,
            accepted=not rejected,
            base_weight=base_weight,
            distance_factor=distance_factor,
            freshness_factor=freshness_factor,
            weight=effective_weight,
            rejection_reason="temperature outlier" if rejected else None,
        )

    @classmethod
    def _cap_family_influence(
        cls,
        evidence: tuple[CurrentSourceEvidence, ...],
    ) -> tuple[CurrentSourceEvidence, ...]:
        totals: dict[str, float] = {}
        for item in evidence:
            if item.accepted:
                totals[item.family] = totals.get(item.family, 0.0) + item.weight

        capped: list[CurrentSourceEvidence] = []
        for item in evidence:
            family_total = totals.get(item.family, 0.0)
            family_cap = cls._FAMILY_CAPS.get(item.family, cls._DEFAULT_WEIGHT)
            if item.accepted and family_total > family_cap and family_total > 0:
                capped.append(
                    replace(item, weight=item.weight * (family_cap / family_total))
                )
            else:
                capped.append(item)
        return tuple(capped)

    @classmethod
    def _source_family(cls, item: CurrentConditions) -> str:
        return cls._SOURCE_FAMILIES.get(item.source, item.source)

    @classmethod
    def _source_kind(cls, item: CurrentConditions) -> str:
        family = cls._source_family(item)
        if family in {"nws-observation", "local-observation"}:
            return "observation"
        if family in {"noaa-model", "ecmwf-model", "open-meteo-best-match"}:
            return "model"
        return "source"

    @classmethod
    def _distance_factor(cls, item: CurrentConditions) -> float:
        if cls._source_kind(item) != "observation" or item.distance_miles is None:
            return 1.0
        distance = max(0.0, item.distance_miles)
        return 1.0 / (1.0 + distance / cls._DISTANCE_SCALE_MILES)

    @classmethod
    def _freshness_factor(cls, item: CurrentConditions) -> float:
        if cls._source_kind(item) != "observation" or item.age_minutes is None:
            return 1.0
        age = max(0.0, item.age_minutes)
        if age <= 15:
            return 1.0
        if age <= 30:
            return 0.9
        if age <= 60:
            return 0.75
        if age <= 120:
            return 0.5
        return 0.25

    @staticmethod
    def _evidence_key(item: CurrentConditions) -> tuple[str, str | None]:
        return item.source, item.station_id

    @staticmethod
    def _weighted_average(
        evidence: tuple[CurrentSourceEvidence, ...],
        attribute: str,
    ) -> float:
        weighted_sum = 0.0
        total_weight = 0.0
        for item in evidence:
            value = getattr(item, attribute)
            if not isinstance(value, int | float):
                continue
            weighted_sum += float(value) * item.weight
            total_weight += item.weight
        if total_weight == 0:
            raise RuntimeError(f"current weather consensus is missing {attribute}")
        return weighted_sum / total_weight

    @classmethod
    def _weighted_optional_average(
        cls,
        evidence: tuple[CurrentSourceEvidence, ...],
        attribute: str,
    ) -> float | None:
        available = tuple(
            item
            for item in evidence
            if isinstance(getattr(item, attribute), int | float)
        )
        if not available:
            return None
        return cls._weighted_average(available, attribute)

    @staticmethod
    def _weighted_direction(
        evidence: tuple[CurrentSourceEvidence, ...],
    ) -> float | None:
        x = 0.0
        y = 0.0
        total_weight = 0.0
        for item in evidence:
            value = item.wind_direction_degrees
            if value is None:
                continue
            angle = radians(value)
            x += cos(angle) * item.weight
            y += sin(angle) * item.weight
            total_weight += item.weight
        if total_weight == 0:
            return None
        direction = degrees(atan2(y / total_weight, x / total_weight))
        return direction % 360

    @staticmethod
    def _preferred_condition(
        evidence: tuple[CurrentSourceEvidence, ...],
    ) -> str | None:
        available = [item for item in evidence if item.condition]
        if not available:
            return None
        return max(available, key=lambda item: item.weight).condition

    @staticmethod
    def _spread(values: object) -> float | None:
        available = [
            float(value)
            for value in values
            if isinstance(value, int | float)
        ]
        if len(available) < 2:
            return None
        return max(available) - min(available)

    @staticmethod
    def _apparent_temperature(
        *,
        temperature_f: float,
        humidity_percent: float | None,
        wind_speed_mph: float | None,
    ) -> float:
        if humidity_percent is not None:
            humidity = min(100.0, max(0.0, humidity_percent))
            simple = 0.5 * (
                temperature_f
                + 61.0
                + ((temperature_f - 68.0) * 1.2)
                + (humidity * 0.094)
            )
            simple = (simple + temperature_f) / 2.0
            if simple >= 80.0:
                heat_index = (
                    -42.379
                    + 2.04901523 * temperature_f
                    + 10.14333127 * humidity
                    - 0.22475541 * temperature_f * humidity
                    - 0.00683783 * temperature_f**2
                    - 0.05481717 * humidity**2
                    + 0.00122874 * temperature_f**2 * humidity
                    + 0.00085282 * temperature_f * humidity**2
                    - 0.00000199 * temperature_f**2 * humidity**2
                )
                if humidity < 13 and 80 <= temperature_f <= 112:
                    heat_index -= ((13 - humidity) / 4) * sqrt(
                        (17 - abs(temperature_f - 95)) / 17
                    )
                elif humidity > 85 and 80 <= temperature_f <= 87:
                    heat_index += ((humidity - 85) / 10) * (
                        (87 - temperature_f) / 5
                    )
                return heat_index

        if (
            wind_speed_mph is not None
            and temperature_f <= 50
            and wind_speed_mph > 3
        ):
            wind_factor = wind_speed_mph**0.16
            return (
                35.74
                + 0.6215 * temperature_f
                - 35.75 * wind_factor
                + 0.4275 * temperature_f * wind_factor
            )
        return temperature_f

    @staticmethod
    def _confidence(
        *,
        family_count: int,
        spread_f: float | None,
    ) -> WeatherAgreement:
        if family_count < 2 or spread_f is None:
            return WeatherAgreement.LOW
        if spread_f <= 2:
            return WeatherAgreement.HIGH
        if spread_f <= 5:
            return WeatherAgreement.MODERATE
        return WeatherAgreement.LOW
