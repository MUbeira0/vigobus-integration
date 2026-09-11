import importlib
import time
import unittest
from unittest.mock import patch

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

geocoding = importlib.import_module("custom_components.vigobus.geocoding")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def json(self, content_type=None):
        return self._payload


class _FakeSession:
    def __init__(self, payload=None, raise_error=None):
        self._payload = payload if payload is not None else []
        self._raise_error = raise_error
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if self._raise_error is not None:
            raise self._raise_error
        return _FakeResponse(self._payload)


NOMINATIM_SAMPLE = [
    {
        "name": "Colexio Alameda",
        "display_name": "Colexio Alameda, Rúa Example, Vigo, Pontevedra, Galicia, 36201, España",
        "lat": "42.2320",
        "lon": "-8.7250",
    },
    {
        "name": "",
        "display_name": "Rúa da Coruña 26, Vigo, Pontevedra, Galicia, 36201, España",
        "lat": "42.2223",
        "lon": "-8.7341",
    },
]


class GeocodeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        geocoding._GEOCODE_CACHE.clear()
        geocoding._last_request_at = 0.0

    async def test_parses_named_and_address_only_results(self):
        session = _FakeSession(payload=NOMINATIM_SAMPLE)

        places = await geocoding.geocode(session, "colexio alameda")

        self.assertEqual(len(places), 2)
        self.assertEqual(places[0]["name"], "Colexio Alameda")
        self.assertEqual(places[0]["latitude"], 42.2320)
        self.assertEqual(places[0]["longitude"], -8.7250)
        # No "name" field (a pure address hit) falls back to the first
        # comma-separated segment of display_name as a short label.
        self.assertEqual(places[1]["name"], "Rúa da Coruña 26")

    async def test_empty_query_short_circuits_without_a_request(self):
        session = _FakeSession(payload=NOMINATIM_SAMPLE)

        places = await geocoding.geocode(session, "   ")

        self.assertEqual(places, [])
        self.assertEqual(session.calls, [])

    async def test_request_carries_the_required_user_agent_and_vigo_viewbox(self):
        session = _FakeSession(payload=[])

        await geocoding.geocode(session, "praza de america")

        call = session.calls[0]
        self.assertIn("User-Agent", call["headers"])
        self.assertIn("vigobus-integration", call["headers"]["User-Agent"])
        self.assertEqual(call["params"]["bounded"], "1")
        self.assertIn("viewbox", call["params"])

    async def test_second_call_within_ttl_is_served_from_cache(self):
        session = _FakeSession(payload=NOMINATIM_SAMPLE)

        first = await geocoding.geocode(session, "colexio alameda")
        second = await geocoding.geocode(session, "colexio alameda")

        self.assertEqual(first, second)
        self.assertEqual(len(session.calls), 1)

    async def test_upstream_failure_returns_an_empty_list_not_an_exception(self):
        session = _FakeSession(raise_error=RuntimeError("boom"))

        places = await geocoding.geocode(session, "colexio alameda")

        self.assertEqual(places, [])

    async def test_throttles_to_roughly_one_request_per_second(self):
        session = _FakeSession(payload=[])
        geocoding._last_request_at = time.monotonic()

        with patch("asyncio.sleep") as mock_sleep:
            async def _fake_sleep(_seconds):
                return None

            mock_sleep.side_effect = _fake_sleep
            await geocoding.geocode(session, "a different query than any cached one")

        self.assertTrue(mock_sleep.called)
        waited = mock_sleep.call_args.args[0]
        self.assertGreater(waited, 0)
        self.assertLessEqual(waited, geocoding.NOMINATIM_MIN_INTERVAL_SECONDS)


if __name__ == "__main__":
    unittest.main()
