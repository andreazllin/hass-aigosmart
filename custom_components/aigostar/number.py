"""
Number platform for Aigostar fans — auto-off timer.

TSL property:
  appointmentClosingTime  int  rw  0-24 h (0 = timer off)
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .alibaba_api import AlibabaIoTClient
from .const import DOMAIN, PROP_FAN_TIMER, SCAN_INTERVAL_SECONDS
from .helpers import is_fan_device, register_for_token_refresh

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECONDS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for dev in entry_data["devices"]:
        if not is_fan_device(dev):
            continue
        iot_id = dev.get("iotId", "")
        nick = (dev.get("nickName") or dev.get("deviceName") or iot_id[:12]).strip()
        client = AlibabaIoTClient(
            iot_id=iot_id,
            iot_token=entry_data["iot_token"],
            app_key=entry_data["app_key"],
            app_secret=entry_data["app_secret"],
        )
        entities.append(AigostarFanTimer(client, iot_id, nick))

    register_for_token_refresh(hass, entry, entities)
    async_add_entities(entities, update_before_add=True)


class AigostarFanTimer(NumberEntity):
    """Auto-off timer for an Aigostar fan."""

    _attr_has_entity_name = True
    _attr_translation_key = "auto_off_timer"
    _attr_name = "Auto-off timer"
    _attr_native_min_value = 0
    _attr_native_max_value = 24
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "h"
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:timer-outline"

    def __init__(self, client: AlibabaIoTClient, iot_id: str, name: str) -> None:
        self._client = client
        self._attr_unique_id = f"{iot_id}_timer"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, iot_id)}, name=name)
        self._value = 0
        self._available = True

    def update_token(self, new_token: str) -> None:
        self._client.iot_token = new_token

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def available(self) -> bool:
        return self._available

    def update(self) -> None:
        try:
            props = self._client.get_properties_sync()
            if PROP_FAN_TIMER in props:
                self._value = int(props[PROP_FAN_TIMER])
            self._available = True
        except Exception as exc:
            _LOGGER.warning("Aigostar timer update failed: %s", exc)
            self._available = False

    def set_native_value(self, value: float) -> None:
        self._client.set_properties_sync({PROP_FAN_TIMER: int(value)})
        self._value = int(value)
        self.schedule_update_ha_state()
