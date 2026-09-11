import importlib
import unittest

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

routing = importlib.import_module("custom_components.vigobus.routing")


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def json(self, content_type=None):
        return self._payload


class _FakeSession:
    def __init__(self, payload=None, status=200, raise_error=None):
        self._payload = payload if payload is not None else {}
        self._status = status
        self._raise_error = raise_error
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self._raise_error is not None:
            raise self._raise_error
        return _FakeResponse(self._payload, status=self._status)


ORS_GEOJSON_SAMPLE = {
    "features": [
        {
            "geometry": {
                "coordinates": [
                    [-8.7200, 42.2300],
                    [-8.7210, 42.2305],
                    [-8.7220, 42.2310],
                ]
            }
        }
    ]
}


class GetWalkingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_api_key_makes_no_request(self):
        session = _FakeSession(payload=ORS_GEOJSON_SAMPLE)

        result = await routing.get_walking_route(session, None, 42.23, -8.72, 42.231, -8.722)

        self.assertIsNone(result)
        self.assertEqual(session.calls, [])

    async def test_parses_geojson_coordinates_into_lat_lon_pairs(self):
        session = _FakeSession(payload=ORS_GEOJSON_SAMPLE)

        result = await routing.get_walking_route(session, "fake-key", 42.23, -8.72, 42.231, -8.722)

        self.assertEqual(result, [[42.2300, -8.7200], [42.2305, -8.7210], [42.2310, -8.7220]])

    async def test_sends_the_api_key_and_from_to_coordinates(self):
        session = _FakeSession(payload=ORS_GEOJSON_SAMPLE)

        await routing.get_walking_route(session, "fake-key", 42.23, -8.72, 42.231, -8.722)

        call = session.calls[0]
        self.assertEqual(call["headers"]["Authorization"], "fake-key")
        self.assertEqual(call["json"]["coordinates"], [[-8.72, 42.23], [-8.722, 42.231]])

    async def test_non_200_status_returns_none(self):
        session = _FakeSession(payload=ORS_GEOJSON_SAMPLE, status=403)

        result = await routing.get_walking_route(session, "bad-key", 42.23, -8.72, 42.231, -8.722)

        self.assertIsNone(result)

    async def test_request_failure_returns_none_not_an_exception(self):
        session = _FakeSession(raise_error=RuntimeError("boom"))

        result = await routing.get_walking_route(session, "fake-key", 42.23, -8.72, 42.231, -8.722)

        self.assertIsNone(result)

    async def test_malformed_response_returns_none(self):
        session = _FakeSession(payload={"features": []})

        result = await routing.get_walking_route(session, "fake-key", 42.23, -8.72, 42.231, -8.722)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
