<p align="center"><img src="https://raw.githubusercontent.com/MUbeira0/vigobus-integration/main/assets/logo.svg" alt="VigoBus Pro" width="480"></p>

<p align="center"><b>English</b> · <a href="#espanol">Español</a> · <a href="#galego">Galego</a><br><sub>Español y Galego están más abajo, en este mismo documento · Español e Galego están máis abaixo, neste mesmo documento</sub></p>

# VigoBus Pro

[![Latest release](https://img.shields.io/github/v/release/MUbeira0/vigobus-integration?sort=semver)](https://github.com/MUbeira0/vigobus-integration/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1.0%2B-blue.svg)](https://www.home-assistant.io/)
[![Marketplace](https://img.shields.io/badge/HA%20Marketplace-Integration-orange.svg)](https://www.home-assistant.io/integrations/marketplace/)

Home Assistant integration for the **urban buses of Vigo (Vitrasa)**: real-time arrivals, your nearest stop, extra stops, line alerts and a trip planner.


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

---

<a id="espanol"></a>
<details>
<summary><h2>🇪🇸 Español</h2></summary>

Integración de Home Assistant para los **autobuses urbanos de Vigo (Vitrasa)**: llegadas en tiempo real, tu parada más cercana, paradas extra, avisos de línea y planificador de viajes.


Tiene una tarjeta de dashboard complementaria: [lovelace-vigobus-card](https://github.com/MUbeira0/lovelace-vigobus-card).

## Qué ofrece

- **Llegadas en tiempo real** de cualquier parada de Vigo: línea, ruta, minutos, distancia del bus y si la estimación es en vivo (GPS) o de horario.
- **Parada más cercana** a tu casa, y **una por persona/móvil** que elijas (o de todos automáticamente).
- **Paradas extra**, cada una con filtro de línea opcional (por ejemplo solo la `C1`).
- **Avisos de línea** en castellano o gallego, con notificaciones opcionales.
- **Colores oficiales de línea** (campo `color` en cada bus) para que los dashboards coincidan con los autobuses reales.
- **Planificador de viajes** con transbordos, desde donde estás hasta una dirección o lugar (un colegio, un centro comercial, un hospital).
- Cada parada es un **dispositivo** de Home Assistant con sus 4 sensores agrupados.
- Fiabilidad: datos en caché, paradas actualizadas en paralelo, espera automática si los servidores de Vigo fallan y descarga de **diagnóstico** para reportar errores.

## Requisitos

- Home Assistant **2024.1.0 o superior** (las imágenes de marca se incluyen para 2026.3+).
- Acceso a internet a los servidores de datos abiertos de Vigo (`datos.vigo.org`).

## Instalación

Desde Home Assistant **2026.11**, HACS está integrado en Home Assistant como [Marketplace](https://www.home-assistant.io/integrations/marketplace/).

1. Abre el **Marketplace**, busca **VigoBus Pro** e instálalo.
2. Reinicia Home Assistant si te lo pide.

¿Ya lo tenías con HACS? No tienes que hacer nada: Home Assistant lo migra solo en el primer arranque de 2026.11 y sigue actualizándolo.

**Manual / Home Assistant anterior (con HACS):** añade `https://github.com/MUbeira0/vigobus-integration` como repositorio personalizado, categoría **Integración**, e instala **VigoBus Pro**.

## Configuración inicial

1. **Ajustes → Dispositivos y servicios → Añadir integración → VigoBus Pro.**
2. Elige cómo funciona la parada cercana de casa y el intervalo de actualización. El resto se puede cambiar después.
3. Añade más paradas desde **Configurar** (menú de la integración).

### Opciones de configuración

| Opción | Por defecto | Rango | Qué hace |
|---|---|---|---|
| Parada cercana automática | – | – | Crea los sensores de parada cercana según la ubicación de casa. |
| Nombre / filtro de línea de la parada cercana | vacío | – | Nombre personalizado y línea opcional (p. ej. `C1`). |
| Parada cercana para estos dispositivos | ninguno | – | Un conjunto de parada cercana por cada `person` / `device_tracker` que elijas. |
| Crear para todos los dispositivos | desactivado | – | Crea uno por cada dispositivo GPS automáticamente. |
| Intervalo de actualización | 30 s | 15–300 s | Cada cuánto se refrescan los sensores. |
| Distancia de recálculo | 120 m | 20–1000 m | Cuánto debe moverse un dispositivo para recalcular su parada cercana. |
| Avisos automáticos | desactivado | – | Avisa cuando un bus está a punto de llegar. |
| Umbral de aviso | 5 min | 1–60 | Avisa cuando el bus está a esta distancia en minutos. |
| Espera entre avisos | 20 min | 1–240 | Tiempo mínimo entre dos notificaciones. |
| Idioma de los avisos | `es` | `es` / `gl` | Idioma de los avisos de línea. |
| Máx. avisos por parada | 10 | 1–25 | Límite de avisos mostrados por parada. |
| Notificar cuando aparezca un aviso nuevo | desactivado | – | Lista opcional de servicios `notify` (p. ej. tu móvil), además del panel de notificaciones. |

**Configurar** tiene tres secciones (*Ubicación y parada cercana*, *Notificaciones*, *Avisos*) más **Añadir parada (buscar)**, **Añadir paradas (pegar lista)** y **Quitar parada**. La lista pegada es una línea con entradas separadas por ` | `, cada una `id,nombre,línea`, por ejemplo: `1234,Urzaiz,C1 | 5678,Colón`.

## Entidades

Cada parada (casa, extra o de dispositivo) es un dispositivo con cuatro sensores:

| Sensor | Estado |
|---|---|
| Parada principal | Minutos hasta el próximo bus (unidad `min`), con los detalles como atributos. |
| Línea | Línea del próximo bus. |
| Ruta | Ruta del próximo bus. |
| Próximos | Los siguientes buses de la parada. |

Los sensores por dispositivo tienen el atributo `is_device_nearest`, para que los dashboards los distingan. Puedes quitar el dispositivo de una parada desde la interfaz: si sigue configurada, vuelve en la siguiente recarga.

## Servicios

| Servicio | Qué hace |
|---|---|
| `vigobus.refresh` | Fuerza una actualización (`entry_id` opcional; por defecto todas). |
| `vigobus.nearest_stops` | Parada(s) más cercana(s) a `latitude` / `longitude` con sus buses y avisos. Opcional: `tie_margin_m` (60 por defecto), `max_candidates` (3), `line`, `lang`. |
| `vigobus.search_stops` | Busca paradas por nombre o id (`query`, `limit` opcional). |
| `vigobus.geocode` | Convierte una dirección o lugar en coordenadas (solo zona de Vigo) con OpenStreetMap Nominatim. |
| `vigobus.plan_trip` | Planifica un viaje en bus con transbordos usando el horario GTFS oficial de Vigo. |

Todos salvo `refresh` son **sin estado**: solo usan lo que les pasas y no guardan nada. Ejemplo:

```yaml
service: vigobus.plan_trip
data:
  origin_latitude: 42.2328
  origin_longitude: -8.7226
  destination_stop_id: "5557"
  depart_at: "18:00"      # vacío = ahora
  max_transfers: 2        # 0-2
  max_walk_m: 800         # 100-2000
  max_itineraries: 3      # 1-5
```

Origen y destino pueden ser coordenadas o un `stop_id` exacto (de `search_stops` / `nearest_stops`). El `ors_api_key` opcional hace que los tramos a pie del principio y del final sigan calles reales (clave gratuita en [openrouteservice.org](https://openrouteservice.org/dev), 2000 peticiones/día). Límites conocidos: solo el primer tramo en bus se contrasta con datos en vivo, y un viaje planificado justo pasada la medianoche puede perder un bus que empezó el día de servicio anterior.

## Privacidad

`vigobus.geocode` envía el texto que escribes al servicio público Nominatim de OpenStreetMap (aprox. 1 petición por segundo, en caché 1 hora). Los resultados deben atribuirse a *colaboradores de OpenStreetMap* donde se muestren. Nada más habla con terceros aparte de los datos abiertos de Vigo y, solo si lo configuras, OpenRouteService.

## Solución de problemas

- **No aparecen entidades tras instalar:** reinicia Home Assistant.
- **El icono o logo no se actualiza:** limpia la caché del navegador y recarga.
- **Los datos de una parada son incorrectos:** abre una incidencia con el id de la parada y la línea.
- **Reportar errores:** *Ajustes → Dispositivos y servicios → VigoBus Pro → Descargar diagnóstico*. El archivo oculta coordenadas y nombres de paradas personalizados.

## Desarrollo

```bash
pip install ruff pytest
ruff check custom_components/ tests/
pytest tests -q
```

El CI ejecuta Hassfest, validación HACS, lint y tests en cada push.

## Soporte

[Incidencias](https://github.com/MUbeira0/vigobus-integration/issues) · [Versiones](https://github.com/MUbeira0/vigobus-integration/releases)

</details>

<a id="galego"></a>
<details>
<summary><h2>🏴 Galego</h2></summary>

Integración de Home Assistant para os **autobuses urbanos de Vigo (Vitrasa)**: chegadas en tempo real, a túa parada máis próxima, paradas extra, avisos de liña e planificador de viaxes.


Ten unha tarxeta de dashboard complementaria: [lovelace-vigobus-card](https://github.com/MUbeira0/lovelace-vigobus-card).

## Que ofrece

- **Chegadas en tempo real** de calquera parada de Vigo: liña, ruta, minutos, distancia do bus e se a estimación é en vivo (GPS) ou de horario.
- **Parada máis próxima** á túa casa, e **unha por persoa/móbil** que elixas (ou de todos automaticamente).
- **Paradas extra**, cada unha con filtro de liña opcional (por exemplo só a `C1`).
- **Avisos de liña** en castelán ou galego, con notificacións opcionais.
- **Cores oficiais de liña** (campo `color` en cada bus) para que os dashboards coincidan cos autobuses reais.
- **Planificador de viaxes** con transbordos, desde onde estás ata un enderezo ou lugar (un colexio, un centro comercial, un hospital).
- Cada parada é un **dispositivo** de Home Assistant cos seus 4 sensores agrupados.
- Fiabilidade: datos en caché, paradas actualizadas en paralelo, espera automática se os servidores de Vigo fallan e descarga de **diagnóstico** para reportar erros.

## Requisitos

- Home Assistant **2024.1.0 ou superior** (as imaxes de marca inclúense para 2026.3+).
- Acceso a internet aos servidores de datos abertos de Vigo (`datos.vigo.org`).

## Instalación

Desde Home Assistant **2026.11**, HACS está integrado en Home Assistant como [Marketplace](https://www.home-assistant.io/integrations/marketplace/).

1. Abre o **Marketplace**, busca **VigoBus Pro** e instálao.
2. Reinicia Home Assistant se o pide.

Xa o tiñas con HACS? Non tes que facer nada: Home Assistant migrao só no primeiro arranque de 2026.11 e segue actualizándoo.

**Manual / Home Assistant anterior (con HACS):** engade `https://github.com/MUbeira0/vigobus-integration` como repositorio personalizado, categoría **Integración**, e instala **VigoBus Pro**.

## Configuración inicial

1. **Axustes → Dispositivos e servizos → Engadir integración → VigoBus Pro.**
2. Elixe como funciona a parada próxima da casa e o intervalo de actualización. O resto pódese cambiar despois.
3. Engade máis paradas desde **Configurar** (menú da integración).

### Opcións de configuración

| Opción | Por defecto | Rango | Que fai |
|---|---|---|---|
| Parada próxima automática | – | – | Crea os sensores de parada próxima segundo a localización da casa. |
| Nome / filtro de liña da parada próxima | baleiro | – | Nome personalizado e liña opcional (p. ex. `C1`). |
| Parada próxima para estes dispositivos | ningún | – | Un conxunto de parada próxima por cada `person` / `device_tracker` que elixas. |
| Crear para todos os dispositivos | desactivado | – | Crea un por cada dispositivo GPS automaticamente. |
| Intervalo de actualización | 30 s | 15–300 s | Cada canto se refrescan os sensores. |
| Distancia de recálculo | 120 m | 20–1000 m | Canto debe moverse un dispositivo para recalcular a súa parada próxima. |
| Avisos automáticos | desactivado | – | Avisa cando un bus está a piques de chegar. |
| Límite de aviso | 5 min | 1–60 | Avisa cando o bus está a esta distancia en minutos. |
| Espera entre avisos | 20 min | 1–240 | Tempo mínimo entre dúas notificacións. |
| Idioma dos avisos | `es` | `es` / `gl` | Idioma dos avisos de liña. |
| Máx. avisos por parada | 10 | 1–25 | Límite de avisos amosados por parada. |
| Notificar cando apareza un aviso novo | desactivado | – | Lista opcional de servizos `notify` (p. ex. o teu móbil), ademais do panel de notificacións. |

**Configurar** ten tres seccións (*Localización e parada próxima*, *Notificacións*, *Avisos*) máis **Engadir parada (buscar)**, **Engadir paradas (pegar lista)** e **Quitar parada**. A lista pegada é unha liña con entradas separadas por ` | `, cada unha `id,nome,liña`, por exemplo: `1234,Urzaiz,C1 | 5678,Colón`.

## Entidades

Cada parada (casa, extra ou de dispositivo) é un dispositivo con catro sensores:

| Sensor | Estado |
|---|---|
| Parada principal | Minutos ata o próximo bus (unidade `min`), cos detalles como atributos. |
| Liña | Liña do próximo bus. |
| Ruta | Ruta do próximo bus. |
| Próximos | Os seguintes buses da parada. |

Os sensores por dispositivo teñen o atributo `is_device_nearest`, para que os dashboards os distingan. Podes quitar o dispositivo dunha parada desde a interface: se segue configurada, volve na seguinte recarga.

## Servizos

| Servizo | Que fai |
|---|---|
| `vigobus.refresh` | Forza unha actualización (`entry_id` opcional; por defecto todas). |
| `vigobus.nearest_stops` | Parada(s) máis próxima(s) a `latitude` / `longitude` cos seus buses e avisos. Opcional: `tie_margin_m` (60 por defecto), `max_candidates` (3), `line`, `lang`. |
| `vigobus.search_stops` | Busca paradas por nome ou id (`query`, `limit` opcional). |
| `vigobus.geocode` | Converte un enderezo ou lugar en coordenadas (só zona de Vigo) con OpenStreetMap Nominatim. |
| `vigobus.plan_trip` | Planifica unha viaxe en bus con transbordos usando o horario GTFS oficial de Vigo. |

Todos agás `refresh` son **sen estado**: só usan o que lles pasas e non gardan nada. Exemplo:

```yaml
service: vigobus.plan_trip
data:
  origin_latitude: 42.2328
  origin_longitude: -8.7226
  destination_stop_id: "5557"
  depart_at: "18:00"      # baleiro = agora
  max_transfers: 2        # 0-2
  max_walk_m: 800         # 100-2000
  max_itineraries: 3      # 1-5
```

Orixe e destino poden ser coordenadas ou un `stop_id` exacto (de `search_stops` / `nearest_stops`). O `ors_api_key` opcional fai que os treitos a pé do principio e do final sigan rúas reais (clave gratuíta en [openrouteservice.org](https://openrouteservice.org/dev), 2000 peticións/día). Límites coñecidos: só o primeiro treito en bus se contrasta con datos en vivo, e unha viaxe planificada xusto pasada a medianoite pode perder un bus que comezou o día de servizo anterior.

## Privacidade

`vigobus.geocode` envía o texto que escribes ao servizo público Nominatim de OpenStreetMap (aprox. 1 petición por segundo, en caché 1 hora). Os resultados deben atribuírse a *colaboradores de OpenStreetMap* onde se amosen. Nada máis fala con terceiros fóra dos datos abertos de Vigo e, só se o configuras, OpenRouteService.

## Solución de problemas

- **Non aparecen entidades tras instalar:** reinicia Home Assistant.
- **A icona ou logo non se actualiza:** limpa a caché do navegador e recarga.
- **Os datos dunha parada son incorrectos:** abre unha incidencia co id da parada e a liña.
- **Reportar erros:** *Axustes → Dispositivos e servizos → VigoBus Pro → Descargar diagnóstico*. O arquivo agocha coordenadas e nomes de paradas personalizados.

## Desenvolvemento

```bash
pip install ruff pytest
ruff check custom_components/ tests/
pytest tests -q
```

O CI executa Hassfest, validación HACS, lint e tests en cada push.

## Soporte

[Incidencias](https://github.com/MUbeira0/vigobus-integration/issues) · [Versións](https://github.com/MUbeira0/vigobus-integration/releases)

</details>
