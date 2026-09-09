import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

api_mod = importlib.import_module("custom_components.vigobus.api")


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
    """Duck-typed stand-in for aiohttp.ClientSession: no real network calls."""

    def __init__(self, responses):
        # responses: {url_prefix: payload_or_callable}
        self._responses = responses
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        for prefix, payload in self._responses.items():
            if url.startswith(prefix):
                return _FakeResponse(payload() if callable(payload) else payload)
        raise AssertionError(f"Unexpected URL requested: {url}")


def _reset_caches():
    api_mod._LINE_COLOR_CACHE["data"] = {}
    api_mod._LINE_COLOR_CACHE["expires_at"] = 0.0
    api_mod._PARADAS_CACHE["data"] = None
    api_mod._PARADAS_CACHE["expires_at"] = 0.0
    api_mod._ALERTS_CACHE.clear()


class ApiCachingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_caches()

    async def test_get_paradas_is_cached_across_calls(self):
        session = _FakeSession({api_mod.PARADAS_URL: [{"id": "1"}]})
        api = api_mod.VigoBusApi(session)

        first = await api.get_paradas()
        second = await api.get_paradas()

        self.assertEqual(first, second)
        self.assertEqual(session.calls, [api_mod.PARADAS_URL])

    async def test_get_paradas_force_refresh_bypasses_cache(self):
        session = _FakeSession({api_mod.PARADAS_URL: [{"id": "1"}]})
        api = api_mod.VigoBusApi(session)

        await api.get_paradas()
        await api.get_paradas(force_refresh=True)

        self.assertEqual(len(session.calls), 2)

    async def test_get_line_colors_parses_geojson_features(self):
        geojson = {
            "features": [
                {"properties": {"linea": "C1", "color": "#ED4713"}},
                {"properties": {"linea": "n 1", "color": "#CCC7C7"}},
                {"properties": {"linea": "", "color": "#FFFFFF"}},
                {"properties": {"linea": "9B", "color": ""}},
            ]
        }
        session = _FakeSession({api_mod.LINE_COLORS_URL: geojson})
        api = api_mod.VigoBusApi(session)

        colors = await api.get_line_colors()

        self.assertEqual(colors, {"C1": "#ED4713", "N1": "#CCC7C7"})

    async def test_get_line_colors_keeps_previous_map_on_fetch_failure(self):
        session = _FakeSession({api_mod.LINE_COLORS_URL: {"features": [
            {"properties": {"linea": "C1", "color": "#ED4713"}}
        ]}})
        api = api_mod.VigoBusApi(session)
        first = await api.get_line_colors()

        # Force the cache to look expired, then make the next fetch fail.
        api_mod._LINE_COLOR_CACHE["expires_at"] = 0.0

        class _BoomSession(_FakeSession):
            def get(self, url, timeout=None):
                raise RuntimeError("network down")

        api_broken = api_mod.VigoBusApi(_BoomSession({}))
        second = await api_broken.get_line_colors()

        self.assertEqual(first, second)

    async def test_get_avisos_is_cached_per_lang(self):
        session = _FakeSession({
            api_mod.AVISOS_URL.format("TRANSPORTE_AVISOS_ES"): {"data": []},
            api_mod.AVISOS_URL.format("TRANSPORTE_AVISOS_GL"): {"data": []},
        })
        api = api_mod.VigoBusApi(session)

        await api.get_avisos(lang="es")
        await api.get_avisos(lang="es")
        await api.get_avisos(lang="gl")

        self.assertEqual(
            session.calls,
            [
                api_mod.AVISOS_URL.format("TRANSPORTE_AVISOS_ES"),
                api_mod.AVISOS_URL.format("TRANSPORTE_AVISOS_GL"),
            ],
        )


class NearestStopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_caches()

    async def test_get_nearest_stop_picks_closest(self):
        stops = [
            {"id": "far", "latitud": 43.0, "longitud": -9.0},
            {"id": "near", "latitud": 42.0001, "longitud": -8.0001},
        ]
        session = _FakeSession({api_mod.PARADAS_URL: stops})
        api = api_mod.VigoBusApi(session)

        nearest = await api.get_nearest_stop(42.0, -8.0)

        self.assertEqual(nearest["id"], "near")

    async def test_get_nearest_stops_with_eta_uses_id_not_stop_id(self):
        # Regression test: the estimacion endpoint expects the "id"
        # (stop_vitrasa) value, not the municipal "stop_id" — using the
        # wrong one previously returned the wrong stop's arrivals entirely.
        stops = [
            {"id": "vitrasa-1", "stop_id": "municipal-1", "nombre": "Stop A", "latitud": 42.0, "longitud": -8.0}
        ]
        session = _FakeSession({
            api_mod.PARADAS_URL: stops,
            api_mod.LINE_COLORS_URL: {"features": []},
            api_mod.ESTIMACION_URL.format("vitrasa-1"): {
                "estimaciones": [{"linea": "C1", "ruta": "Centro", "minutos": "5", "metros": 300}]
            },
            api_mod.ESTIMACION_URL.format("municipal-1"): {
                "estimaciones": [{"linea": "WRONG", "ruta": "Wrong", "minutos": "99", "metros": -1}]
            },
        })
        api = api_mod.VigoBusApi(session)

        results = await api.get_nearest_stops_with_eta(42.0, -8.0)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["buses"][0]["linea"], "C1")

    async def test_get_nearest_stops_with_eta_filters_by_line(self):
        stops = [
            {"id": "s1", "nombre": "Stop A", "latitud": 42.0, "longitud": -8.0}
        ]
        session = _FakeSession({
            api_mod.PARADAS_URL: stops,
            api_mod.LINE_COLORS_URL: {"features": []},
            api_mod.ESTIMACION_URL.format("s1"): {
                "estimaciones": [
                    {"linea": "C1", "ruta": "Centro", "minutos": "5", "metros": 300},
                    {"linea": "9B", "ruta": "Coia", "minutos": "8", "metros": 100},
                ]
            },
        })
        api = api_mod.VigoBusApi(session)

        results = await api.get_nearest_stops_with_eta(42.0, -8.0, line="9b")

        self.assertEqual(len(results[0]["buses"]), 1)
        self.assertEqual(results[0]["buses"][0]["linea"], "9B")


class LineAlertsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_caches()

    async def test_get_line_alerts_dedupes_identical_signatures(self):
        avisos_payload = {"data": [{"id_publicacion": "p1", "nombre": "Corte de via"}]}
        lineas_payload = {
            "data": [
                {"id": "p1", "lineas_afectadas": "C1,9B", "fecha_inicio": "2026-01-01", "fecha_fin": "2026-01-02"},
                {"id": "p1", "lineas_afectadas": "C1", "fecha_inicio": "2026-01-01", "fecha_fin": "2026-01-02"},
            ]
        }
        session = _FakeSession({
            api_mod.AVISOS_URL.format("TRANSPORTE_AVISOS_ES"): avisos_payload,
            api_mod.AVISOS_LINEAS_URL.format(1): lineas_payload,
        })
        api = api_mod.VigoBusApi(session)

        alerts = await api.get_line_alerts(lang="es")

        self.assertEqual(len(alerts["C1"]), 1)
        self.assertEqual(alerts["C1"][0]["title"], "Corte de via")
        self.assertEqual(len(alerts["9B"]), 1)


if __name__ == "__main__":
    unittest.main()
