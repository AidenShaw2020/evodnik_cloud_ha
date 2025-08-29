from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL_MIN,
    CONF_USERNAME, CONF_PASSWORD, CONF_DEVICE_ID, CONF_SCAN_INTERVAL_MIN,
)
from .api import EvodnikClient

_LOGGER = logging.getLogger(__name__)


class EvodnikDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Coordinator fetching data and maintaining a cumulative total using delta logic."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.client = EvodnikClient()

        # Persistent store for accumulators (per DeviceNumber)
        self.store: Store = Store(hass, 1, f"{DOMAIN}_accumulators.json")
        self.index_store: Store = Store(hass, 1, f"{DOMAIN}_index.json")
        self._index: Optional[Dict[str, Any]] = None
        self._acc_data: Optional[Dict[str, Any]] = None  # lazy-loaded

        scan_min = entry.options.get(CONF_SCAN_INTERVAL_MIN, DEFAULT_SCAN_INTERVAL_MIN)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(minutes=scan_min),
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        username = self.entry.data[CONF_USERNAME]
        password = self.entry.data[CONF_PASSWORD]
        device_id = int(self.entry.data[CONF_DEVICE_ID])
        try:
            data: Dict[str, Any] = await self.hass.async_add_executor_job(
                self.client.fetch_all, username, password, device_id
            )
        except Exception as err:
            raise UpdateFailed(str(err)) from err

        # Compute cumulative total using DELTA between consecutive readings of today's counter.
        # grand_total is stored in 'daily_offset_liters' for backward compatibility.
        try:
            if self._acc_data is None:
                self._acc_data = await self.store.async_load() or {}

            headers = data.get("headers", [])
            hdr0 = headers[0] if headers else {}
            device_number = str(hdr0.get("DeviceNumber") or "unknown")

            # Update index (entry_id -> device_number) for cleanup on entry removal
            if self._index is None:
                self._index = await self.index_store.async_load() or {}
            if self._index.get(self.entry.entry_id) != device_number:
                self._index[self.entry.entry_id] = device_number
                await self.index_store.async_save(self._index)

            rep = (data.get("dashboard", {}) or {}).get("ReportItems", []) or []
            day_item = next((it for it in rep if isinstance(it, dict) and it.get("ItemType") == 8), {})

            today_liters = float(day_item.get("ThisValueFlow1") or 0.0)

            # Load per-device accumulators
            dev = dict(self._acc_data.get(device_number) or {})
            grand_total = float(dev.get("daily_offset_liters", 0.0))  # reuse key for compatibility
            last_today = float(dev.get("last_today_liters", today_liters))

            # Delta increment
            inc = today_liters - last_today
            if inc < 0:
                # rollover at midnight/reset -> add what has flown so far today
                inc = today_liters
            if inc > 0:
                grand_total += inc

            # Persist
            dev["last_today_liters"] = today_liters
            dev["daily_offset_liters"] = grand_total
            # Keep legacy keys if present; they are no longer used by the delta logic

            self._acc_data[device_number] = dev
            await self.store.async_save(self._acc_data)

            # Expose cumulative total directly (already includes today's amount)
            data["virtual_total_liters"] = grand_total
        except Exception as err:
            _LOGGER.debug("Delta total computation failed: %s", err)

        return data
