from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.storage import Store
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import EvodnikDataUpdateCoordinator

PLATFORMS = ["sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = EvodnikDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_remove_entry(hass, entry):
    """Cleanup persistent storage for this specific config entry only."""
    try:
        index_store = Store(hass, 1, f"{DOMAIN}_index.json")
        idx = await index_store.async_load() or {}
        device_number = idx.pop(entry.entry_id, None)

        acc_store = Store(hass, 1, f"{DOMAIN}_accumulators.json")
        if device_number is not None:
            acc = await acc_store.async_load() or {}
            if device_number in acc:
                acc.pop(device_number, None)
                await acc_store.async_save(acc)
        # Save updated index (even if device_number wasn't found)
        await index_store.async_save(idx)
        _LOGGER.debug("Cleanup complete for entry %s (device_number=%s)", entry.entry_id, device_number)
    except Exception as err:
        _LOGGER.debug("Failed to cleanup storage for %s: %s", DOMAIN, err)
    try:
        store = Store(hass, 1, f"{DOMAIN}_accumulators.json")
        await store.async_remove()
        _LOGGER.debug("Removed storage for %s on entry removal", DOMAIN)
    except Exception as err:
        _LOGGER.debug("Failed to remove storage for %s: %s", DOMAIN, err)
