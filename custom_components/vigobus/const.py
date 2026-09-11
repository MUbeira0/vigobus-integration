DOMAIN = "vigobus"
SERVICE_REFRESH = "refresh"
SERVICE_NEAREST_STOPS = "nearest_stops"

PARADAS_URL = "https://datos.vigo.org/data/transporte/paradas.json"

ESTIMACION_URL = (
    "https://datos.vigo.org/vci_api_app/api2.jsp"
    "?tipo=TRANSPORTE-ESTIMACION-PARADA&id={}"
)
AVISOS_URL = "https://datos.vigo.org/vci_api_app/api2.jsp?tipo={}"
AVISOS_LINEAS_URL = "https://datos.vigo.org/vci_api_app/api2.jsp?tipo=WEBPUB_AVISOS_TRANSPORTE&lang={}"
LINE_COLORS_URL = "https://datos.vigo.org/data/transporte/lineas.geojson"

SCAN_INTERVAL = 30
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 15
MAX_SCAN_INTERVAL = 300

# Automatic per-device nearest sensors.
# When True, the integration discovers person/GPS device_tracker entities and
# creates a nearest-stop sensor set for each one, without listing them by hand.
DEFAULT_AUTO_NEAREST_DEVICES = False

DEFAULT_NEAREST_RECALC_DISTANCE_M = 120
MIN_NEAREST_RECALC_DISTANCE_M = 20
MAX_NEAREST_RECALC_DISTANCE_M = 1000

DEFAULT_NOTIFY_ENABLED = False
DEFAULT_NOTIFY_MINUTES = 5
MIN_NOTIFY_MINUTES = 1
MAX_NOTIFY_MINUTES = 60

DEFAULT_NOTIFY_COOLDOWN_MIN = 20
MIN_NOTIFY_COOLDOWN_MIN = 1
MAX_NOTIFY_COOLDOWN_MIN = 240

DEFAULT_ALERTS_LANG = "es"
DEFAULT_ALERTS_MAX_PER_STOP = 10
MIN_ALERTS_MAX_PER_STOP = 1
MAX_ALERTS_MAX_PER_STOP = 25

DEFAULT_NOTIFY_NEW_ALERTS_ENABLED = False

# Defaults for the stateless "nearest_stops" service (SERVICE_NEAREST_STOPS):
# a one-off lookup keyed on coordinates the caller supplies (typically the
# viewing device's own live geolocation), not stored anywhere.
DEFAULT_DEVICE_NEAREST_TIE_MARGIN_M = 60
MIN_DEVICE_NEAREST_TIE_MARGIN_M = 0
MAX_DEVICE_NEAREST_TIE_MARGIN_M = 500

DEFAULT_DEVICE_NEAREST_MAX_CANDIDATES = 3
MIN_DEVICE_NEAREST_MAX_CANDIDATES = 1
MAX_DEVICE_NEAREST_MAX_CANDIDATES = 5

SERVICE_PLAN_TRIP = "plan_trip"
SERVICE_SEARCH_STOPS = "search_stops"

GTFS_URL = "https://datos.vigo.org/data/transporte/gtfs_vigo.zip"

# This feed is "calendar_dates-only" (every service day exists solely as an
# exception_type==1 row on a rolling horizon the publisher regenerates), so a
# shorter TTL than the 24h used for line colors is safer — an instance that
# builds the index late at night shouldn't hold a feed whose newest rows
# stop covering "today" for a whole day.
GTFS_CACHE_TTL_SECONDS = 12 * 60 * 60

WALK_SPEED_MPS = 1.25  # ~4.5 km/h, a common default for walking-directions estimates

DEFAULT_TRIP_MAX_WALK_M = 800
MIN_TRIP_MAX_WALK_M = 100
MAX_TRIP_MAX_WALK_M = 2000

DEFAULT_TRIP_MAX_TRANSFERS = 2
MIN_TRIP_MAX_TRANSFERS = 0
MAX_TRIP_MAX_TRANSFERS = 2

DEFAULT_TRIP_MAX_ITINERARIES = 3
MIN_TRIP_MAX_ITINERARIES = 1
MAX_TRIP_MAX_ITINERARIES = 5

# Stops within this radius are treated as one instantly-transferable cluster
# (e.g. opposite-direction platforms at the same corner share no single GTFS
# stop_id, but a rider can just walk across).
TRIP_TRANSFER_CLUSTER_RADIUS_M = 40
TRIP_TRANSFER_MIN_SECONDS = 90

DEFAULT_STOP_SEARCH_LIMIT = 8
MIN_STOP_SEARCH_LIMIT = 1
MAX_STOP_SEARCH_LIMIT = 25

# get_estimacion() only ever knows "the next few buses at one stop right
# now" — cross-checking a planned leg's live arrival only makes sense when
# its scheduled departure is still within that near-term horizon.
LIVE_CHECK_HORIZON_SECONDS = 45 * 60

SERVICE_GEOCODE = "geocode"

# OpenStreetMap's public Nominatim instance — free, no API key, used so the
# trip planner can search a real address or named place (a school, a mall)
# instead of only an exact bus stop. Their usage policy requires a real,
# identifying User-Agent and caps requests at ~1/second; both are honored in
# geocoding.py. Results must be attributed to OpenStreetMap contributors
# wherever they're shown (the card does this in its search UI).
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = (
    "vigobus-integration Home Assistant custom component "
    "(https://github.com/MUbeira0/vigobus-integration)"
)
NOMINATIM_MIN_INTERVAL_SECONDS = 1.0

# Roughly Vitrasa's whole service area (Vigo plus the outlying parishes its
# lines actually reach) — hard-bounds geocoding results to this box so
# "colegio X" can't match a same-named place in another city, and so a
# result the bus network could never reach isn't offered in the first place.
GEOCODE_VIEWBOX = "-8.85,42.32,-8.60,42.10"

GEOCODE_CACHE_TTL_SECONDS = 60 * 60

DEFAULT_GEOCODE_LIMIT = 5
MIN_GEOCODE_LIMIT = 1
MAX_GEOCODE_LIMIT = 10
