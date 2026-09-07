import math

from aiohttp import ClientSession

from .const import AVISOS_LINEAS_URL, AVISOS_URL, ESTIMACION_URL, PARADAS_URL


class VigoBusApi:
    def __init__(self, session: ClientSession):
        self.session = session

    async def get_paradas(self):
        async with self.session.get(PARADAS_URL, timeout=15) as resp:
            return await resp.json()

    async def get_estimacion(self, stop_id):
        url = ESTIMACION_URL.format(stop_id)

        async with self.session.get(url, timeout=15) as resp:
            return await resp.json()

    def _avisos_tipo_for_lang(self, lang):
        key = str(lang or "es").lower()
        if key.startswith("gl"):
            return "TRANSPORTE_AVISOS_GL"
        return "TRANSPORTE_AVISOS_ES"

    async def get_avisos(self, lang="es"):
        tipo = self._avisos_tipo_for_lang(lang)
        url = AVISOS_URL.format(tipo)
        async with self.session.get(url, timeout=15) as resp:
            return await resp.json()

    def _avisos_lineas_lang_code(self, lang):
        key = str(lang or "es").lower()
        if key.startswith("gl"):
            return 2
        if key.startswith("en"):
            return 3
        return 1

    async def get_avisos_lineas(self, lang="es"):
        url = AVISOS_LINEAS_URL.format(self._avisos_lineas_lang_code(lang))
        async with self.session.get(url, timeout=15) as resp:
            return await resp.json()

    def _extract_items(self, data):
        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in ("data", "items", "results", "avisos", "value"):
                value = data.get(key)
                if isinstance(value, list):
                    return value

        return []

    def _normalize_line(self, value):
        text = str(value or "").strip().upper().replace(" ", "")
        return text or None

    def _split_lines(self, value):
        if isinstance(value, (list, tuple, set)):
            raw = [str(item or "") for item in value]
        else:
            raw = str(value or "").replace(";", ",").replace("|", ",").replace("/", ",").split(",")

        result = []
        for item in raw:
            normalized = self._normalize_line(item)
            if normalized:
                result.append(normalized)

        return result

    async def get_line_alerts(self, lang="es", logger=None):
        avisos_data = await self.get_avisos(lang=lang)
        lineas_data = await self.get_avisos_lineas(lang=lang)

        avisos = self._extract_items(avisos_data)
        lineas = self._extract_items(lineas_data)

        details = {}
        for item in avisos:
            if not isinstance(item, dict):
                continue
            pub_id = str(item.get("id_publicacion") or item.get("id") or item.get("idpublicacion") or "").strip()
            if not pub_id:
                continue
            title = str(item.get("nombre") or item.get("titulo") or item.get("title") or item.get("descripcion") or "").strip()
            if title:
                details[pub_id] = title

        alerts_by_line = {}
        for item in lineas:
            if not isinstance(item, dict):
                continue

            pub_id = str(item.get("id") or item.get("id_publicacion") or item.get("idpublicacion") or "").strip()
            affected_lines = self._split_lines(item.get("lineas_afectadas") or item.get("lineas") or item.get("linea"))
            if not affected_lines:
                continue

            title = (
                details.get(pub_id)
                or str(item.get("nombre") or item.get("titulo") or item.get("title") or "").strip()
                or (f"Aviso {pub_id}" if pub_id else "Aviso de transporte")
            )

            alert = {
                "id_publicacion": pub_id or None,
                "title": title,
                "lineas": ", ".join(affected_lines),
                "inicio": item.get("fecha_inicio"),
                "fin": item.get("fecha_fin"),
            }

            for line in affected_lines:
                alerts_by_line.setdefault(line, []).append(alert)

        for line, values in alerts_by_line.items():
            seen = set()
            deduped = []
            for alert in values:
                signature = (
                    alert.get("id_publicacion"),
                    alert.get("title"),
                    alert.get("inicio"),
                    alert.get("fin"),
                )
                if signature in seen:
                    continue
                seen.add(signature)
                deduped.append(alert)
            alerts_by_line[line] = deduped

        if logger:
            logger.debug("VigoBus: %s line alerts loaded for lang=%s", len(alerts_by_line), lang)

        return alerts_by_line

    def _extract_stops(self, data):
        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in ("data", "paradas", "items", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return value

        return []

    def _to_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _normalize_stop(self, stop):
        if not isinstance(stop, dict):
            return None

        properties = stop.get("properties") if isinstance(stop.get("properties"), dict) else {}

        lat = self._to_float(
            stop.get("latitud")
            or stop.get("lat")
            or stop.get("latitude")
            or properties.get("latitud")
            or properties.get("lat")
            or properties.get("latitude")
        )
        lon = self._to_float(
            stop.get("longitud")
            or stop.get("lon")
            or stop.get("lng")
            or stop.get("longitude")
            or properties.get("longitud")
            or properties.get("lon")
            or properties.get("lng")
            or properties.get("longitude")
        )

        geometry = stop.get("geometry")
        if (lat is None or lon is None) and isinstance(geometry, dict):
            coordinates = geometry.get("coordinates")
            if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
                geo_lon = self._to_float(coordinates[0])
                geo_lat = self._to_float(coordinates[1])
                if geo_lat is not None and geo_lon is not None:
                    lat = geo_lat
                    lon = geo_lon

        nearest_id = (
            stop.get("id")
            or properties.get("id")
        )

        stop_id = (
            stop.get("stop_id")
            or stop.get("idparada")
            or stop.get("parada")
            or properties.get("stop_id")
            or properties.get("idparada")
            or properties.get("parada")
        )

        if lat is None or lon is None:
            return None

        normalized = dict(stop)
        if nearest_id is not None:
            normalized["id"] = str(nearest_id)
        if stop_id is not None:
            normalized["stop_id"] = str(stop_id)
        normalized["latitud"] = lat
        normalized["longitud"] = lon
        return normalized

    def haversine(self, lat1, lon1, lat2, lon2):
        R = 6371000

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)

        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1)
            * math.cos(phi2)
            * math.sin(dlambda / 2) ** 2
        )

        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    async def get_nearest_stop(self, home_lat, home_lon, logger=None):
        data = await self.get_paradas()
        stops = self._extract_stops(data)
        if logger:
            logger.debug(f"VigoBus: {len(stops)} paradas recibidas para nearest. Home: lat={home_lat}, lon={home_lon}")

        nearest = None
        nearest_distance = 999999
        for stop in stops:
            normalized = self._normalize_stop(stop)
            if not normalized:
                continue
            lat = normalized["latitud"]
            lon = normalized["longitud"]
            dist = self.haversine(home_lat, home_lon, lat, lon)
            if logger:
                logger.debug(
                    "VigoBus: parada id=%s stop_id=%s lat=%s lon=%s dist=%.1f",
                    normalized.get("id"),
                    normalized.get("stop_id"),
                    lat,
                    lon,
                    dist,
                )
            if dist < nearest_distance:
                nearest_distance = dist
                nearest = normalized
        if logger:
            if nearest:
                logger.info(
                    "VigoBus: nearest encontrada: id=%s stop_id=%s a %.1f m",
                    nearest.get("id"),
                    nearest.get("stop_id"),
                    nearest_distance,
                )
            else:
                logger.warning("VigoBus: No se encontró nearest para las coordenadas dadas")
        return nearest

    async def get_nearest_stops(self, lat, lon, margin_m=60, max_candidates=3, logger=None):
        """Return the closest stop plus any other stop within margin_m of it.

        Used for the device-location based nearest feature, where the closest
        stop alone can be ambiguous (e.g. two stops on opposite sidewalks).
        """
        data = await self.get_paradas()
        stops = self._extract_stops(data)

        scored = []
        for stop in stops:
            normalized = self._normalize_stop(stop)
            if not normalized:
                continue
            dist = self.haversine(lat, lon, normalized["latitud"], normalized["longitud"])
            normalized["_distance_m"] = dist
            scored.append(normalized)

        scored.sort(key=lambda item: item["_distance_m"])

        if not scored:
            if logger:
                logger.warning("VigoBus: No se encontraron paradas para calcular nearest del dispositivo")
            return []

        nearest_distance = scored[0]["_distance_m"]
        candidates = [
            item for item in scored
            if item["_distance_m"] <= nearest_distance + max(0, margin_m)
        ][: max(1, int(max_candidates))]

        if logger:
            logger.info(
                "VigoBus: %s paradas candidatas para el dispositivo (mas cercana a %.1f m)",
                len(candidates),
                nearest_distance,
            )

        return candidates

    async def get_nearest_stops_with_eta(
        self, lat, lon, margin_m=60, max_candidates=3, line=None, logger=None
    ):
        """Nearest candidate stops plus their upcoming buses, for a one-off lookup.

        Used by the stateless "nearest_stops" service: the caller (typically a
        dashboard card) supplies coordinates read live from the viewing
        device's own geolocation, so this is not tied to any stored location.
        When "line" is set, only buses for that line are kept.
        """
        candidates = await self.get_nearest_stops(
            lat, lon, margin_m=margin_m, max_candidates=max_candidates, logger=logger
        )
        line_filter = self._normalize_line(line) if line else None

        results = []
        for stop in candidates:
            # The estimacion endpoint expects the "id" (stop_vitrasa) value,
            # not the municipal "stop_id" — matches coordinator._extract_stop_id.
            stop_id = stop.get("id") or stop.get("stop_id")
            if not stop_id:
                continue

            try:
                estimacion = await self.get_estimacion(stop_id)
            except Exception as err:
                if logger:
                    logger.warning("VigoBus: fallo al pedir estimacion de %s: %s", stop_id, err)
                estimacion = {}

            estimaciones = (estimacion or {}).get("estimaciones", [])
            buses = []
            if isinstance(estimaciones, list):
                for item in estimaciones:
                    if not isinstance(item, dict):
                        continue
                    try:
                        minutos = int(item.get("minutos"))
                    except (TypeError, ValueError):
                        continue
                    if line_filter and self._normalize_line(item.get("linea")) != line_filter:
                        continue
                    buses.append(
                        {
                            "linea": item.get("linea"),
                            "ruta": item.get("ruta"),
                            "metros": item.get("metros"),
                            "minutos": minutos,
                        }
                    )
            buses.sort(key=lambda item: item["minutos"])

            results.append(
                {
                    "id": stop_id,
                    "name": stop.get("nombre") or stop.get("name") or stop_id,
                    "distance_m": round(stop.get("_distance_m", 0), 1),
                    "buses": buses,
                    "next_minutes": buses[0]["minutos"] if buses else None,
                }
            )

        return results
