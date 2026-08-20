"""
Switch platform for Aigostar — fan key beep and kettle switches.

TSL properties:
  buzzerSwitch      bool  rw  0=silent 1=beep on key press  (fan)
  HeatingSwitch     bool  rw  boiling on/off                (kettle)
  heatpreservation  bool  rw  keep warm on/off              (kettle)
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
from .const import (
    DOMAIN,
    PROP_FAN_BUZZER,
    PROP_KETTLE_KEEP_WARM,
    PROP_KETTLE_SWITCH,
    SCAN_INTERVAL_SECONDS,
)
from .helpers import is_fan_device, is_kettle_device, register_for_token_refresh

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
        is_fan = is_fan_device(dev)
        is_kettle = is_kettle_device(dev)
        if not is_fan and not is_kettle:
            continue
        iot_id = dev.get("iotId", "")
        nick = (dev.get("nickName") or dev.get("deviceName") or iot_id[:12]).strip()
        client = AlibabaIoTClient(
            iot_id=iot_id,
            iot_token=entry_data["iot_token"],
            app_key=entry_data["app_key"],
            app_secret=entry_data["app_secret"],
        )
        if is_fan:
            entities.append(AigostarFanBuzzer(client, iot_id, nick))
        else:
            online = dev.get("status", 0) == 1
            entities.append(AigostarKettleSwitch(client, iot_id, nick, online, dev))
            entities.append(AigostarKettleKeepWarmSwitch(client, iot_id, nick, online, dev))

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


class AigostarKettleSwitch(SwitchEntity):
    """Aigostar kettle boiling switch."""

    _attr_has_entity_name = True
    _attr_name = "Boiling"
    _attr_icon = "mdi:kettle-steam"

    def __init__(
        self, client: AlibabaIoTClient, iot_id: str, name: str,
        online: bool, raw_device: dict,
    ) -> None:
        self._client = client
        self._attr_unique_id = f"{iot_id}_heat_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=name,
            manufacturer="Aigostar",
            model=raw_device.get("productName", "Electric Kettle"),
        )
        self._is_on = False
        self._available = online

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
            self._is_on = bool(props.get(PROP_KETTLE_SWITCH))
            self._available = True
        except Exception as exc:
            _LOGGER.warning("Aigostar kettle switch update failed: %s", exc)
            self._available = False

    def turn_on(self, **kwargs: Any) -> None:
        try:
            self._client.set_properties_sync({PROP_KETTLE_SWITCH: 1})
            self._is_on = True
            self.schedule_update_ha_state()
        except Exception as exc:
            _LOGGER.error("Aigostar kettle [%s] turn_on failed: %s", self._attr_unique_id, exc)

    def turn_off(self, **kwargs: Any) -> None:
        try:
            self._client.set_properties_sync({PROP_KETTLE_SWITCH: 0})
            self._is_on = False
            self.schedule_update_ha_state()
        except Exception as exc:
            _LOGGER.error("Aigostar kettle [%s] turn_off failed: %s", self._attr_unique_id, exc)


class AigostarKettleKeepWarmSwitch(SwitchEntity):
    """Aigostar kettle keep-warm switch."""

    _attr_has_entity_name = True
    _attr_name = "Keep Warm"
    _attr_icon = "mdi:thermometer-plus"

    def __init__(
        self, client: AlibabaIoTClient, iot_id: str, name: str,
        online: bool, raw_device: dict,
    ) -> None:
        self._client = client
        self._attr_unique_id = f"{iot_id}_keepwarm_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=name,
            manufacturer="Aigostar",
            model=raw_device.get("productName", "Electric Kettle"),
        )
        self._is_on = False
        self._available = online

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
            self._is_on = bool(props.get(PROP_KETTLE_KEEP_WARM))
            self._available = True
        except Exception as exc:
            _LOGGER.warning("Aigostar keep-warm switch update failed: %s", exc)
            self._available = False

    def turn_on(self, **kwargs: Any) -> None:
        try:
            self._client.set_properties_sync({PROP_KETTLE_KEEP_WARM: 1})
            self._is_on = True
            self.schedule_update_ha_state()
        except Exception as exc:
            _LOGGER.error("Aigostar kettle [%s] keep_warm on failed: %s", self._attr_unique_id, exc)

    def turn_off(self, **kwargs: Any) -> None:
        try:
            self._client.set_properties_sync({PROP_KETTLE_KEEP_WARM: 0})
            self._is_on = False
            self.schedule_update_ha_state()
        except Exception as exc:
            _LOGGER.error("Aigostar kettle [%s] keep_warm off failed: %s", self._attr_unique_id, exc)
