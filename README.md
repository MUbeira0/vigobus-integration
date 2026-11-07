<p align="center"><img src="https://raw.githubusercontent.com/MUbeira0/vigobus-integration/main/assets/logo.svg" alt="VigoBus Pro" width="480"></p>

<p align="center">
  <b>English</b> ·
  <a href="https://github.com/MUbeira0/vigobus-integration/blob/main/README.es.md">Español</a> ·
  <a href="https://github.com/MUbeira0/vigobus-integration/blob/main/README.gl.md">Galego</a>
</p>

# VigoBus Pro

Home Assistant integration for the **urban buses of Vigo (Vitrasa)**: real-time arrivals, your nearest stop, extra stops, line alerts and a trip planner.

[![Latest release](https://img.shields.io/github/v/release/MUbeira0/vigobus-integration?sort=semver)](https://github.com/MUbeira0/vigobus-integration/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1.0%2B-blue.svg)](https://www.home-assistant.io/)
[![Marketplace](https://img.shields.io/badge/HA%20Marketplace-Integration-orange.svg)](https://www.home-assistant.io/integrations/marketplace/)

It has a companion dashboard card: [lovelace-vigobus-card](https://github.com/MUbeira0/lovelace-vigobus-card).

## What you get

- **Real-time arrivals** for any Vigo stop: line, route, minutes, distance of the bus, and whether the estimate is live (GPS) or timetable.
- **Nearest stop** to your home, plus **one per person/phone** you choose (or all of them automatically).
- **Extra stops**, each with an optional line filter (e.g. only line `C1`).
- **Line alerts** in Spanish or Galician, with optional notifications.
- **Official line colours** (`color` field on every bus) so dashboards can match the real buses.
- **Trip planner** with transfers, from where you are to an address or place (a school, a mall, a hospital).
- Every stop is a Home Assistant **device** with its 4 sensors grouped together.
- Reliability: data is cached, stops refresh concurrently, it backs off if the Vigo servers are down, and it has a **diagnostics** download for bug reports.

## Requirements

- Home Assistant **2024.1.0 or newer** (brand images are bundled for 2026.3+).
- Internet access to the Vigo open-data servers (`datos.vigo.org`).

## Installation

Since Home Assistant **2026.11**, HACS is built into Home Assistant as the [Marketplace](https://www.home-assistant.io/integrations/marketplace/).

1. Open the **Marketplace**, search for **VigoBus Pro** and install it.
2. Restart Home Assistant if it asks you to.

Already installed with HACS? Nothing to do: Home Assistant migrates it automatically on the first start of 2026.11 and keeps updating it.

**Manual / older Home Assistant (with HACS):** add `https://github.com/MUbeira0/vigobus-integration` as a custom repository, category **Integration**, then install **VigoBus Pro**.

## Setup

1. **Settings → Devices & services → Add integration → VigoBus Pro.**
2. Choose how the home nearest stop works and the update interval. Everything else can be changed later.
3. Add more stops from **Configure** (menu of the integration).

### Setup and Configure options

| Option | Default | Range | What it does |
|---|---|---|---|
| Auto nearest stop | – | – | Creates the nearest-stop sensors from your home location. |
| Nearest stop name / line filter | empty | – | Custom name and optional line (e.g. `C1`). |
| Nearest stop for these devices | none | – | One nearest-stop set for each `person` / `device_tracker` you pick. |
| Auto-create for every device | off | – | Creates one for every GPS device automatically. |
| Update interval | 30 s | 15–300 s | How often sensors refresh. |
| Nearest recalc distance | 120 m | 20–1000 m | How far a device must move before its nearest stop is recomputed. |
| Automatic alerts | off | – | Notify when a bus is about to arrive. |
| Alert threshold | 5 min | 1–60 | Notify when the bus is this close. |
| Alert cooldown | 20 min | 1–240 | Minimum time between two notifications. |
| Alerts language | `es` | `es` / `gl` | Language of the line alerts. |
| Max alerts per stop | 10 | 1–25 | Limit of alerts shown per stop. |
| Notify when a new alert appears | off | – | Optional list of `notify` services (e.g. your phone) in addition to the Home Assistant notification panel. |

**Configure** has three sections (*Location & nearest stop*, *Notifications*, *Alerts*) plus **Add stop (search)**, **Add stops (paste list)** and **Remove stop**. The pasted list is one line with entries separated by ` | `, each one `id,name,line`, for example: `1234,Urzaiz,C1 | 5678,Colón`.

## Entities

Each stop (home, extra or per-device) is a device with four sensors:

| Sensor | State |
|---|---|
| Main stop | Minutes until the next bus (unit `min`), with the details as attributes. |
| Line | Line of the next bus. |
| Route | Route of the next bus. |
| Upcoming | The next buses of the stop. |

Per-device sensors have the attribute `is_device_nearest`, so dashboards can tell them apart. Removing a stop's device from the UI is fine: if it is still configured, it comes back on the next reload.

## Services

| Service | What it does |
|---|---|
| `vigobus.refresh` | Forces a refresh (optional `entry_id`; by default all entries). |
| `vigobus.nearest_stops` | Closest stop(s) to given `latitude` / `longitude` with their buses and alerts. Optional: `tie_margin_m` (default 60), `max_candidates` (3), `line`, `lang`. |
| `vigobus.search_stops` | Finds stops by name or id (`query`, optional `limit`). |
| `vigobus.geocode` | Turns an address or place into coordinates (Vigo area only) using OpenStreetMap Nominatim. |
| `vigobus.plan_trip` | Plans a bus trip with transfers using Vigo's official GTFS schedule. |

All services except `refresh` are **stateless**: they only use what you pass in and store nothing. Example:

```yaml
service: vigobus.plan_trip
data:
  origin_latitude: 42.2328
  origin_longitude: -8.7226
  destination_stop_id: "5557"
  depart_at: "18:00"      # empty = now
  max_transfers: 2        # 0-2
  max_walk_m: 800         # 100-2000
  max_itineraries: 3      # 1-5
```

Origin and destination can be coordinates or an exact `stop_id` (from `search_stops` / `nearest_stops`). Optional `ors_api_key` makes the first and last walking legs follow real streets (free key at [openrouteservice.org](https://openrouteservice.org/dev), 2000 requests/day). Known limits: only the first bus leg is checked against live data, and a trip planned just after midnight may miss a bus that started the previous service day.

## Privacy

`vigobus.geocode` sends the text you type to OpenStreetMap's public Nominatim service (about 1 request per second, cached for 1 hour). Results must be credited to *OpenStreetMap contributors* wherever they are shown. Nothing else talks to third parties apart from Vigo's open data and, only if you set it, OpenRouteService.

## Troubleshooting

- **No entities after installing:** restart Home Assistant.
- **Icon or logo not updating:** clear the browser cache and reload.
- **A stop's data is wrong:** open an issue with the stop id and line.
- **Bug reports:** *Settings → Devices & services → VigoBus Pro → Download diagnostics*. The file hides coordinates and custom stop names.

## Development

```bash
pip install ruff pytest
ruff check custom_components/ tests/
pytest tests -q
```

CI runs Hassfest, HACS validation, lint and tests on every push.

## Support

[Issues](https://github.com/MUbeira0/vigobus-integration/issues) · [Releases](https://github.com/MUbeira0/vigobus-integration/releases)
