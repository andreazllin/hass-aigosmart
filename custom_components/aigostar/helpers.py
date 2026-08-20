"""Shared helpers for the Aigostar entity platforms."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


def register_for_token_refresh(hass: HomeAssistant, entry: ConfigEntry, entities: list) -> None:
    """Append entities to the shared list used by the token refresh loop."""
    store = hass.data.setdefault(f"{DOMAIN}_entities", {})
    store.setdefault(entry.entry_id, []).extend(entities)


def is_fan_device(dev: dict) -> bool:
    """Return True when the account device is a fan.

    Also used by light.py so fans do not get a bogus light entity.
    """
    category = (dev.get("categoryKey") or "").strip().lower()
    product = (dev.get("productName") or "").strip().lower()
    return category == "fan" or product.startswith("fan")


def is_kettle_device(dev: dict) -> bool:
    """Return True when the account device is a kettle.

    Also used by light.py so kettles do not get a bogus light entity.
    """
    category = (dev.get("categoryKey") or "").strip().lower()
    product = (dev.get("productName") or "").strip().lower()
    return category == "kettle" or "kettle" in product or "bouilloire" in product
