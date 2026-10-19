import pytest

from jakov.services.timezones import COMMON_ZONES, normalize_zone, zone_at, zone_from_location


@pytest.mark.parametrize(("lat", "lon", "zone"), [
    (44.8176, 20.4633, "Europe/Belgrade"),
    (40.7128, -74.0060, "America/New_York"),
    (35.6762, 139.6503, "Asia/Tokyo"),
])
def test_zone_from_coordinates(lat: float, lon: float, zone: str) -> None:
    assert zone_at(lat, lon) == zone


async def test_async_lookup() -> None:
    assert await zone_from_location(51.5072, -0.1276) == "Europe/London"


@pytest.mark.parametrize(("text", "zone"), [
    ("europe/berlin", "Europe/Berlin"),
    ("Europe/Berlin", "Europe/Berlin"),
    ("tokyo", "Asia/Tokyo"),
    ("New York", "America/New_York"),
    ("utc", "UTC"),
])
def test_normalize(text: str, zone: str) -> None:
    assert normalize_zone(text) == zone


@pytest.mark.parametrize("text", ["", "Atlantis", "Mars/Olympus"])
def test_normalize_unknown(text: str) -> None:
    assert normalize_zone(text) is None


def test_common_zones_are_valid() -> None:
    assert all(normalize_zone(z) == z for z in COMMON_ZONES)
