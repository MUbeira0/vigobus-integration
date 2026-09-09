import importlib
import unittest

import conftest  # noqa: F401  (installs Home Assistant stubs on import)

sensor_mod = importlib.import_module("custom_components.vigobus.sensor")


class _FakeStates:
    def get(self, entity_id):
        return None


class _FakeHass:
    states = _FakeStates()


class _FakeCoordinator:
    def __init__(self, data, line_colors=None):
        self.data = data
        self.hass = _FakeHass()
        self._line_colors = line_colors or {}


class DeviceNearestFlagTests(unittest.TestCase):
    def _sensor(self, stop_key):
        coordinator = _FakeCoordinator({})
        return sensor_mod.VigoBusSensor(coordinator, stop_key, entry_id="entry1")

    def test_home_nearest_is_not_device_nearest(self):
        sensor = self._sensor("nearest")
        self.assertFalse(sensor.extra_state_attributes["is_device_nearest"])

    def test_per_device_nearest_is_flagged(self):
        sensor = self._sensor("nearest_person_miguel")
        self.assertTrue(sensor.extra_state_attributes["is_device_nearest"])

    def test_extra_stop_is_not_device_nearest(self):
        sensor = self._sensor("Casa Jesus")
        self.assertFalse(sensor.extra_state_attributes["is_device_nearest"])

    def test_device_model_differs_from_regular_stop(self):
        regular = self._sensor("nearest")
        device = self._sensor("nearest_person_miguel")
        self.assertEqual(regular._attr_device_info["model"], "Parada")
        self.assertEqual(device._attr_device_info["model"], "Parada por dispositivo")


class EstimacionesTests(unittest.TestCase):
    def _data_for(self, key, estimaciones):
        return {key: {"data": {"estimaciones": estimaciones}, "stop_name": "Test"}}

    def test_line_filter_keeps_only_matching_line(self):
        estimaciones = [
            {"linea": "C1", "ruta": "Centro", "minutos": "5", "metros": 300},
            {"linea": "9B", "ruta": "Coia", "minutos": "8", "metros": -1},
        ]
        coordinator = _FakeCoordinator(self._data_for("nearest", estimaciones))
        sensor = sensor_mod.VigoBusSensor(
            coordinator, "nearest", entry_id="entry1", line_filter="c 1"
        )

        result = sensor._get_estimaciones()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["linea"], "C1")

    def test_estimaciones_sorted_by_minutes_and_include_color(self):
        estimaciones = [
            {"linea": "9B", "ruta": "Coia", "minutos": "8", "metros": -1},
            {"linea": "C1", "ruta": "Centro", "minutos": "3", "metros": 300},
        ]
        coordinator = _FakeCoordinator(
            self._data_for("nearest", estimaciones), line_colors={"C1": "#ED4713"}
        )
        sensor = sensor_mod.VigoBusSensor(coordinator, "nearest", entry_id="entry1")

        result = sensor._get_estimaciones()

        self.assertEqual([item["linea"] for item in result], ["C1", "9B"])
        self.assertEqual(result[0]["color"], "#ED4713")
        self.assertIsNone(result[1]["color"])

    def test_invalid_minutes_entries_are_skipped(self):
        estimaciones = [
            {"linea": "C1", "ruta": "Centro", "minutos": "n/a", "metros": 300},
            {"linea": "9B", "ruta": "Coia", "minutos": "8", "metros": -1},
        ]
        coordinator = _FakeCoordinator(self._data_for("nearest", estimaciones))
        sensor = sensor_mod.VigoBusSensor(coordinator, "nearest", entry_id="entry1")

        result = sensor._get_estimaciones()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["linea"], "9B")

    def test_state_is_minutes_of_first_bus(self):
        estimaciones = [{"linea": "C1", "ruta": "Centro", "minutos": "5", "metros": 300}]
        coordinator = _FakeCoordinator(self._data_for("nearest", estimaciones))
        sensor = sensor_mod.VigoBusSensor(coordinator, "nearest", entry_id="entry1")

        self.assertEqual(sensor.state, 5)

    def test_available_is_false_without_data(self):
        coordinator = _FakeCoordinator({})
        sensor = sensor_mod.VigoBusSensor(coordinator, "nearest", entry_id="entry1")

        self.assertFalse(sensor.available)


class UpcomingSensorTests(unittest.TestCase):
    def test_upcoming_state_lists_up_to_three_buses(self):
        estimaciones = [
            {"linea": "C1", "ruta": "Centro", "minutos": "3", "metros": 300},
            {"linea": "9B", "ruta": "Coia", "minutos": "8", "metros": -1},
            {"linea": "27", "ruta": "Teis", "minutos": "12", "metros": 50},
            {"linea": "N1", "ruta": "Noite", "minutos": "20", "metros": -1},
        ]
        coordinator = _FakeCoordinator(
            {"nearest": {"data": {"estimaciones": estimaciones}, "stop_name": "Test"}}
        )
        sensor = sensor_mod.VigoBusUpcomingSensor(coordinator, "nearest", entry_id="entry1")

        self.assertEqual(sensor.state, "C1 3m | 9B 8m | 27 12m")


if __name__ == "__main__":
    unittest.main()
