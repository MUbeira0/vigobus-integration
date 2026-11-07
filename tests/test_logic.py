from custom_components.vigobus.logic import (
    compute_leave,
    estimaciones_for,
    live_counts,
    walk_minutes,
)
from custom_components.vigobus.voice import build_answer, find_stop


def _result(*buses):
    return {
        "stop_name": "Urzaiz",
        "data": {
            "estimaciones": [
                {"linea": line, "ruta": "CENTRO", "minutos": minutes, "metros": meters}
                for line, minutes, meters in buses
            ]
        },
    }


def test_estimaciones_are_sorted_and_filtered():
    result = _result(("C1", 9, 10), ("18A", 3, 20), ("C1", 4, -1))
    assert [b["minutos"] for b in estimaciones_for(result)] == [3, 4, 9]
    assert [b["minutos"] for b in estimaciones_for(result, "c1")] == [4, 9]


def test_estimaciones_ignores_garbage():
    result = {"data": {"estimaciones": [None, {"linea": "C1", "minutos": "x"}, {"linea": "C1", "minutos": 5}]}}
    assert [b["minutos"] for b in estimaciones_for(result)] == [5]
    assert estimaciones_for({}) == []
    assert estimaciones_for({"data": {"estimaciones": "nope"}}) == []


def test_live_counts():
    assert live_counts(_result(("C1", 3, 100), ("C1", 9, -1), ("C1", 12, None))) == (1, 3)
    assert live_counts({}) == (0, 0)


def test_walk_minutes_applies_detour_and_rounds_up():
    assert walk_minutes(0) == 0
    # 100 m * 1.3 / 1.25 m/s = 104 s -> 2 min
    assert walk_minutes(100) == 2
    assert walk_minutes(-5) is None
    assert walk_minutes("x") is None


def test_compute_leave_picks_first_catchable_bus():
    buses = estimaciones_for(_result(("C1", 3, 1), ("C1", 10, 1)))
    info = compute_leave(buses, walk_min=3, buffer_min=1)
    assert info["needed"] == 4
    assert info["leave_in"] == 6
    assert info["bus"]["minutos"] == 10
    assert info["missed"]["minutos"] == 3


def test_compute_leave_zero_means_leave_now():
    buses = estimaciones_for(_result(("C1", 4, 1)))
    assert compute_leave(buses, walk_min=3, buffer_min=1)["leave_in"] == 0


def test_compute_leave_when_every_bus_is_too_close():
    buses = estimaciones_for(_result(("C1", 1, 1), ("C1", 2, 1)))
    info = compute_leave(buses, walk_min=5, buffer_min=0)
    assert info["leave_in"] is None
    assert info["bus"] is None
    assert info["missed"]["minutos"] == 1


def test_compute_leave_without_data():
    assert compute_leave([], 3, 1) is None
    assert compute_leave(estimaciones_for(_result(("C1", 5, 1))), None, 1) is None


def test_voice_answer_in_three_languages():
    result = _result(("C1", 3, 1), ("18A", 1, 1), ("C1", 0, 1))
    assert build_answer(result, "k", "", "es") == "En Urzaiz, el C1 llega ahora mismo. Después, el 18A en 1 minuto."
    assert "chega" in build_answer(result, "k", "", "gl")
    assert build_answer(result, "k", "", "en").startswith("At Urzaiz, the C1 is arriving right now.")
    assert build_answer(_result(), "k", "", "es") == "No hay autobuses previstos en Urzaiz."
    assert "línea C1" in build_answer(_result(("18A", 2, 1)), "k", "C1", "es")


class _Coordinator:
    def __init__(self, data):
        self.data = data


class _Hass:
    def __init__(self, coordinators):
        self.data = {"vigobus": coordinators}


def test_find_stop_matches_by_name_ignoring_accents_and_defaults_to_home():
    home = _result(("C1", 5, 1))
    home["stop_name"] = "Casa"
    other = _result(("C1", 7, 1))
    other["stop_name"] = "Plaza de España"
    hass = _Hass({"entry": _Coordinator({"nearest": home, "Plaza de España": other})})

    assert find_stop(hass, "")[1] == "nearest"
    assert find_stop(hass, "plaza de espana")[1] == "Plaza de España"
    assert find_stop(hass, "plaza")[1] == "Plaza de España"
    assert find_stop(hass, "atlantida") is None


def test_clean_slots_forgives_small_model_mistakes():
    from custom_components.vigobus.voice import clean_slots

    assert clean_slots("Urzaiz", "") == ("Urzaiz", "")
    assert clean_slots("", "25") == ("", "25")
    assert clean_slots("", "el 25") == ("", "25")
    # stop name put in the line slot
    assert clean_slots("", "Urzaiz") == ("Urzaiz", "")
    assert clean_slots("Gran Vía", "Urzaiz") == ("Gran Vía", "")
    # line and stop packed together
    assert clean_slots("25 por casa", "") == ("", "25")
    assert clean_slots("el C1 en Urzaiz", "") == ("Urzaiz", "C1")
    assert clean_slots("18A a Gran Vía", "") == ("Gran Vía", "18A")
    # every way of saying home
    for word in ("casa", "Casa", "mi casa", "en casa", "aquí", "home", "mi parada"):
        assert clean_slots(word, "") == ("", ""), word
    assert clean_slots(None, None) == ("", "")
