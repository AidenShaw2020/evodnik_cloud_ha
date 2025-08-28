from __future__ import annotations

from typing import Any, Dict, Optional, Callable
from datetime import datetime, timezone
import re
import json
import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, CONF_DEVICE_NAME, CONF_DEVICE_ID,
    CONF_CONSUMPTION_UNIT, DEFAULT_CONSUMPTION_UNIT,
)
from .coordinator import EvodnikDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

REASON_MAP: Dict[int, str] = {
    0: "Voda je zavřená z důvodu aktivního režimu Trvale zavřená voda",
    1: "Byl překročen denní limit u 1. průtokoměru.",
    2: "Byl překročen limit u 1. průtokoměru.",
    3: "Byl vyhodnocen úkap u 1. průtokoměru.",
    5: "Limit průtoku u 1. průtokoměru je aktuálně nastavený na nulovou hodnotu. Vodu pustíte jeho změnou.",
    6: "Byl překročen denní limit u 2. průtokoměru.",
    7: "Byl překročen limit u 2. průtokoměru.",
    8: "Byl vyhodnocen úkap u 2. průtokoměru.",
    9: "Limit průtoku u 2. průtokoměru je aktuálně nastavený na nulovou hodnotu. Vodu pustíte jeho změnou.",
    10: "Voda je zavřená z důvodu aktivního odstavení z jednotky.",
    11: "Voda je zavřená z důvodu záplavy.",
}

REGIME_MAP: Dict[int, str] = {
    0: "Automatický",
    1: "Dovolená",
    2: "Simulační",
    3: "Vyšší spotřeba",
    4: "Trvale zavřená voda",
    5: "Trvale otevřená voda",
}

def parse_dotnet_date(s: Optional[str]) -> Optional[str]:
    if not s or not isinstance(s, str):
        return None
    m = re.search(r"/Date\((\d+)\)/", s)
    if not m:
        return None
    ms = int(m.group(1))
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.isoformat()

def _hdr(data: Dict[str, Any]) -> Dict[str, Any]:
    return (data or {}).get("headers", [{}])[0] if isinstance(data, dict) else {}

def _dashboard(data: Dict[str, Any]) -> Dict[str, Any]:
    return (data or {}).get("dashboard", {}) if isinstance(data, dict) else {}

def _item(data: Dict[str, Any], itype: int) -> Optional[Dict[str, Any]]:
    rep = _dashboard(data).get("ReportItems", [])
    if not isinstance(rep, list):
        return None
    for it in rep:
        if isinstance(it, dict) and it.get("ItemType") == itype:
            return it
    return None

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: EvodnikDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}

    headers = (data or {}).get("headers", [])
    hdr0 = headers[0] if headers else {}
    device_number = hdr0.get("DeviceNumber")
    device_name = entry.data.get(CONF_DEVICE_NAME) or hdr0.get("DeviceName") or f"Device {entry.data.get(CONF_DEVICE_ID)}"
    unit = entry.data.get(CONF_CONSUMPTION_UNIT, entry.options.get(CONF_CONSUMPTION_UNIT, DEFAULT_CONSUMPTION_UNIT))

    entities: list[SensorEntity] = []

    # Diagnostic RAW entity
    entities.append(RawDiagnosticSensor(coordinator, entry, device_number, device_name))

    # Virtual cumulative meter (never decreases) for Energy dashboard
    entities.append(TotalIncreasingWaterSensor(
        coordinator, entry, device_number, device_name,
        name="Celková spotřeba",
        liters_getter=lambda d: (d or {}).get("virtual_total_liters"),
        unit=unit,
    ))

    # Header entities
    entities.append(TextSensor(coordinator, entry, device_number, device_name, "Počet průtokoměrů",
        lambda d: _hdr(d).get("NumberFlowLoggers"), icon="mdi:counter", category=EntityCategory.DIAGNOSTIC))
    entities.append(TextSensor(coordinator, entry, device_number, device_name, "ID zařízení",
        lambda d: _hdr(d).get("DeviceId"), icon="mdi:identifier", category=EntityCategory.DIAGNOSTIC))
    entities.append(TextSensor(coordinator, entry, device_number, device_name, "Číslo zařízení",
        lambda d: _hdr(d).get("DeviceNumber"), icon="mdi:numeric", category=EntityCategory.DIAGNOSTIC))
    entities.append(TextSensor(coordinator, entry, device_number, device_name, "Typ",
        lambda d: _hdr(d).get("Version"), icon="mdi:chip", category=EntityCategory.DIAGNOSTIC))
    entities.append(TextSensor(coordinator, entry, device_number, device_name, "Verze",
        lambda d: _hdr(d).get("VersionNumber"), icon="mdi:tag-outline", category=EntityCategory.DIAGNOSTIC))
    entities.append(TextSensor(coordinator, entry, device_number, device_name, "Název",
        lambda d: _hdr(d).get("DeviceName"), icon="mdi:label", category=EntityCategory.DIAGNOSTIC))
    entities.append(TextSensor(coordinator, entry, device_number, device_name, "Umístění",
        lambda d: _hdr(d).get("DeviceAddress"), icon="mdi:home-map-marker", category=EntityCategory.DIAGNOSTIC))

    entities.append(TimestampSensor(coordinator, entry, device_number, device_name, "Datum a čas poslední registrace",
        lambda d: parse_dotnet_date((_hdr(d).get("Regime") or {}).get("LastDateTime") or (_hdr(d).get("WaterFlow") or {}).get("LastDateTime"))))

    entities.append(IconTextSensor(coordinator, entry, device_number, device_name, "Dostupnost",
        lambda d: "Online" if _hdr(d).get("Online") else "Offline",
        icon_getter=lambda state: "mdi:lan-connect" if state == "Online" else "mdi:lan-disconnect",
        category=EntityCategory.DIAGNOSTIC))

    def valve_state_getter(d: Dict[str, Any]) -> Optional[str]:
        water = (_hdr(d).get("WaterFlow") or {}) if isinstance(_hdr(d), dict) else {}
        wf = water.get("WaterFlow")
        reason = water.get("OnFlowReason")
        if wf is True:
            return "Voda je puštěná"
        return REASON_MAP.get(int(reason) if reason is not None else -1, "Voda je zavřená")

    entities.append(IconTextSensor(coordinator, entry, device_number, device_name, "Stav ventilu",
        valve_state_getter,
        icon_getter=lambda state: "mdi:valve-open" if state == "Voda je puštěná" else "mdi:valve-closed"))

    entities.append(TextSensor(coordinator, entry, device_number, device_name, "Aktuální režim",
        lambda d: REGIME_MAP.get(((_hdr(d).get("Regime") or {}).get("Regime")), None),
        icon="mdi:cog-sync"))

    # Report items
    for itype, labels in (
        (8, {
            "trend": "Trend dnešní spotřeby",
            "mean": "Denní průměrná spotřeba",
            "this": "Dnešní spotřeba",
            "this_price": "Částka za dnešní spotřebu",
            "last": "Včerejší spotřeba",
            "last_price": "Částka za včerejší spotřebu",
        }),
        (9, {
            "trend": "Trend týdenní spotřeby",
            "mean": "Týdenní průměrná spotřeba",
            "this": "Spotřeba tento týden",
            "this_price": "Částka za spotřebu tento týden",
            "last": "Spotřeba minulý týden",
            "last_price": "Částka za spotřebu minulý týden",
        }),
        (10, {
            "trend": "Trend měsíční spotřeby",
            "mean": "Měsíční průměrná spotřeba",
            "this": "Spotřeba tento měsíc",
            "this_price": "Částka za spotřebu tento měsíc",
            "last": "Spotřeba minulý měsíc",
            "last_price": "Částka za spotřebu minulý měsíc",
        }),
    ):
        def make_trend_getter(itype: int) -> Callable[[Dict[str, Any]], Optional[float]]:
            def _getter(d: Dict[str, Any]) -> Optional[float]:
                item = _item(d, itype) or {}
                try:
                    tv = float(item.get("ThisValueFlow1")) if item.get("ThisValueFlow1") is not None else None
                    lv = float(item.get("LastValueFlow1")) if item.get("LastValueFlow1") is not None else None
                    if tv is not None and lv is not None:
                        return tv - lv
                except Exception:
                    return None
                return None
            return _getter

        def make_num_getter(itype: int, key: str) -> Callable[[Dict[str, Any]], Any]:
            return lambda d: (_item(d, itype) or {}).get(key)

        def make_text_getter(itype: int, key: str) -> Callable[[Dict[str, Any]], Any]:
            return lambda d: (_item(d, itype) or {}).get(key)

        entities.append(IconNumberSensor(coordinator, entry, device_number, device_name, labels["trend"], make_trend_getter(itype), unit, icon="mdi:chart-line"))
        entities.append(IconNumberSensor(coordinator, entry, device_number, device_name, labels["mean"], make_num_getter(itype, "MeanFlow1"), unit, icon="mdi:water"))
        entities.append(IconNumberSensor(coordinator, entry, device_number, device_name, labels["this"], make_num_getter(itype, "ThisValueFlow1"), unit, icon="mdi:water"))
        entities.append(IconTextSensor(  coordinator, entry, device_number, device_name, labels["this_price"], make_text_getter(itype, "ThisPriceFlow"), icon_getter=lambda s: "mdi:cash"))
        entities.append(IconNumberSensor(coordinator, entry, device_number, device_name, labels["last"], make_num_getter(itype, "LastValueFlow1"), unit, icon="mdi:water"))
        entities.append(IconTextSensor(  coordinator, entry, device_number, device_name, labels["last_price"], make_text_getter(itype, "LastPriceFlow"), icon_getter=lambda s: "mdi:cash-clock"))

    async_add_entities(entities)

class BaseEvodnikEntity(CoordinatorEntity[EvodnikDataUpdateCoordinator], SensorEntity):
    def __init__(self, coordinator: EvodnikDataUpdateCoordinator, entry: ConfigEntry, device_number: Any, device_name: str, name: str, state_getter: Callable[[Dict[str, Any]], Any], unit: Optional[str] = None) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_number = device_number
        self._device_name = device_name
        self._friendly_name = name
        self._unit = unit
        self._state_getter = state_getter
        self._icon: Optional[str] = None
        self._icon_getter: Optional[Callable[[Any], str]] = None
        self._category: Optional[EntityCategory] = None
        
    def _convert_value(self, value):
        # API posílá objemy v litrech; pokud je v konfiguraci zvoleno m³, převedeme L -> m³.
        try:
            unit_norm = (self._unit or "").strip().lower()
            if isinstance(value, (int, float)) and unit_norm in ("m3", "m³", "m^3"):
                return value / 1000.0
        except Exception:
            pass
        return value


    @property
    def name(self) -> str:
        return self._friendly_name

    @property
    def device_info(self):
        hdrs = (self.coordinator.data or {}).get("headers", [])
        hdr = hdrs[0] if hdrs else {}
        return {
            "identifiers": {(DOMAIN, f"{self._device_number}")},
            "manufacturer": "eVodník",
            "name": f"eVodník {self._device_name}",
            "model": f'{hdr.get("Version","")}/{hdr.get("VersionNumber","")}',
        }

    @property
    def entity_category(self) -> Optional[EntityCategory]:
        # Prefer explicit per-entity category; fallback to HA's _attr_entity_category
        if getattr(self, "_category", None) is not None:
            return self._category
        return getattr(self, "_attr_entity_category", None)


    @property
    def extra_state_attributes(self):
        return {}

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._unit

    @property
    def icon(self) -> Optional[str]:
        if self._icon_getter is not None:
            try:
                return self._icon_getter(self.state)
            except Exception:
                return self._icon
        return self._icon

    @property
    def state(self):
        try:
            raw = self._state_getter(self.coordinator.data or {})
            return self._convert_value(raw)
        except Exception as e:
            _LOGGER.debug("State getter failed for %s: %s", self._friendly_name, e)
            return None

    @property
    def unique_id(self) -> str:
        import re as _re
        pattern = r"\W+"
        sanitized = _re.sub(pattern, "_", self._friendly_name.lower())
        return f"{self._entry.entry_id}_{self._device_number}_{sanitized}"

class TextSensor(BaseEvodnikEntity):
    def __init__(self, coordinator, entry, device_number, device_name, name, state_getter, icon: Optional[str] = None, category: Optional[EntityCategory] = None):
        super().__init__(coordinator, entry, device_number, device_name, name, state_getter, None)
        self._icon = icon
        self._category = category

class IconTextSensor(TextSensor):
    def __init__(self, coordinator, entry, device_number, device_name, name, state_getter, icon_getter: Optional[Callable[[Any], str]] = None, category: Optional[EntityCategory] = None):
        super().__init__(coordinator, entry, device_number, device_name, name, state_getter, None)
        self._icon_getter = icon_getter
        self._category = category

class IconNumberSensor(BaseEvodnikEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.WATER

    def __init__(self, coordinator, entry, device_number, device_name, name, state_getter, unit, icon: Optional[str] = None):
        super().__init__(coordinator, entry, device_number, device_name, name, state_getter, unit)
        self._icon = icon

class TimestampSensor(BaseEvodnikEntity):
    _attr_device_class = "timestamp"

    def __init__(self, coordinator, entry, device_number, device_name, name, state_getter):
        super().__init__(coordinator, entry, device_number, device_name, name, state_getter, None)
        self._icon = "mdi:clock-time-four-outline"
        self._category = EntityCategory.DIAGNOSTIC

class RawDiagnosticSensor(BaseEvodnikEntity):
    """Diagnostic entity that exposes full JSON payloads as attributes."""
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:code-json"

    def __init__(self, coordinator, entry, device_number, device_name):
        super().__init__(
            coordinator, entry, device_number, device_name,
            name="RAW data",
            state_getter=lambda d: "RAW",
            unit=None
        )

    @property
    def extra_state_attributes(self):
        d = self.coordinator.data or {}
        headers = d.get("headers", [])
        dashboard = d.get("dashboard", {})
        try:
            headers_txt = json.dumps(headers, ensure_ascii=False)
        except Exception:
            headers_txt = str(headers)
        try:
            dashboard_txt = json.dumps(dashboard, ensure_ascii=False)
        except Exception:
            dashboard_txt = str(dashboard)
        return {
            "raw_device_headers_text": headers_txt,
            "raw_device_dashboard_text": dashboard_txt,
        }


class TotalIncreasingWaterSensor(BaseEvodnikEntity):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.WATER

    def __init__(self, coordinator, entry, device_number, device_name, name, liters_getter, unit):
        super().__init__(coordinator, entry, device_number, device_name, name, liters_getter, unit)

    @property
    def state(self):
        try:
            raw_liters = self._state_getter(self.coordinator.data or {})
            # Conversion uses BaseEvodnikEntity._convert_value (expects liters input)
            return self._convert_value(raw_liters)
        except Exception as e:
            _LOGGER.debug("State getter failed for %s: %s", self._friendly_name, e)
            return None
