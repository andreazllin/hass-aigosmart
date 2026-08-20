"""
Switch platform for Aigostar fans — key beep.

TSL property:
  buzzerSwitch  bool  rw  0=silent 1=beep on key press
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .alibaba_api import AlibabaIoTClient
from .const import DOMAIN, PROP_FAN_BUZZER, SCAN_INTERVAL_SECONDS
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
        entities.append(AigostarFanBuzzer(client, iot_id, nick))

    register_for_token_refresh(hass, entry, entities)
    async_add_entities(entities, update_before_add=True)


class AigostarFanBuzzer(SwitchEntity):
    """Key beep for an Aigostar fan."""

    _attr_has_entity_name = True
    _attr_name = "Key beep"
    _attr_icon = "mdi:volume-high"

    def __init__(self, client: AlibabaIoTClient, iot_id: str, name: str) -> None:
        self._client = client
        self._attr_unique_id = f"{iot_id}_buzzer"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, iot_id)}, name=name)
        self._is_on = True
        self._available = True

    def update_token(self, new_token: str) -> None:
        self._client.iot_token = new_token

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def available(self) -> bool:
        return self._available

    def update(self) -> None:
        try:
            props = self._client.get_properties_sync()
            if PROP_FAN_BUZZER in props:
                self._is_on = bool(int(props[PROP_FAN_BUZZER]))
            self._available = True
        except Exception as exc:
            _LOGGER.warning("Aigostar buzzer update failed: %s", exc)
            self._available = False

    def turn_on(self, **kwargs: Any) -> None:
        self._client.set_properties_sync({PROP_FAN_BUZZER: 1})
        self._is_on = True
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs: Any) -> None:
        self._client.set_properties_sync({PROP_FAN_BUZZER: 0})
        self._is_on = False
        self.schedule_update_ha_state()
