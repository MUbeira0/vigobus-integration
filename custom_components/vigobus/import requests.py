import json
import math
from urllib.request import urlopen

home_lat = 42.2265
home_lon = -8.6453

URL = "https://datos.vigo.org/data/transporte/paradas.json"


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def get_value(stop, keys):
    for key in keys:
        value = stop.get(key)
        if value is not None and value != "":
            return value
    return None


with urlopen(URL, timeout=30) as response:
    data = json.load(response)

if isinstance(data, dict):
    stops = (
        data.get("data")
        or data.get("paradas")
        or data.get("items")
        or data.get("results")
        or []
    )
else:
    stops = data

nearest = None
nearest_dist = float("inf")

for stop in stops:
    if not isinstance(stop, dict):
        continue

    lat = get_value(stop, ["latitud", "lat", "latitude"])
    lon = get_value(stop, ["longitud", "lon", "lng", "longitude"])

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        continue

    dist = haversine(home_lat, home_lon, lat, lon)

    if dist < nearest_dist:
        nearest_dist = dist
        nearest = stop

print("PARADA MÁS CERCANA:")
print(json.dumps(nearest, ensure_ascii=False, indent=2))
print(f"\nDISTANCIA: {nearest_dist:.2f} m")