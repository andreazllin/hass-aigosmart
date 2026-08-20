"""
Water Heater platform for Aigostar — smart kettle support.

TSL properties:
  HeatingSwitch       bool  0/1
  temperature         int   current temperature (°C)
  Target_temperature  int   target temperature (°C)
  heatpreservation    bool  keep warm (switch platform)
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.water_heater import (
    STATE_ELECTRIC,
    STATE_OFF,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .alibaba_api import AlibabaIoTClient
from .helpers import is_kettle_device, register_for_token_refresh
from .const import (
    DOMAIN,
    PROP_KETTLE_SWITCH,
    PROP_KETTLE_TARGET,
    PROP_KETTLE_TEMP,
    SCAN_INTERVAL_SECONDS,
)

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
        if not is_kettle_device(dev):
            continue

        iot_id = dev.get("iotId", "")
        nick = dev.get("nickName") or dev.get("deviceName") or iot_id[:12]
        status = dev.get("status", 0)

        client = AlibabaIoTClient(
            iot_id=iot_id,
            iot_token=entry_data["iot_token"],
            app_key=entry_data["app_key"],
            app_secret=entry_data["app_secret"],
        )
        entities.append(AigostarKettle(client, iot_id, nick, online=(status == 1), raw_device=dev))

    register_for_token_refresh(hass, entry, entities)
    _LOGGER.info("Aigostar: creating %d kettle entities", len(entities))
    async_add_entities(entities, update_before_add=True)


class AigostarKettle(WaterHeaterEntity):
    """Aigostar smart kettle."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.ON_OFF
    )
    _attr_min_temp = 40
    _attr_max_temp = 100
    _attr_precision = 1.0

    def __init__(
        self, client: AlibabaIoTClient, iot_id: str, name: str,
        online: bool, raw_device: dict | None = None,
    ) -> None:
        self._client = client
        self._attr_unique_id = iot_id

        raw = raw_device or {}
        product_name = raw.get("productName") or raw.get("categoryName") or "Electric Kettle"
        fw_version = raw.get("firmwareVersion") or raw.get("moduleVersion") or None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=name,
            manufacturer="Aigostar",
            model=product_name,
            sw_version=fw_version,
        )

        self._current_temp: float | None = None
        self._target_temp: float | None = None
        self._is_on: bool = False
        self._available: bool = online

    def update_token(self, new_token: str) -> None:
        """Update the iotToken after a refresh."""
        self._client.iot_token = new_token

    @property
    def state(self) -> str:
        return STATE_ELECTRIC if self._is_on else STATE_OFF

    @property
    def current_temperature(self) -> float | None:
        return self._current_temp

    @property
    def target_temperature(self) -> float | None:
        return self._target_temp

    @property
    def available(self) -> bool:
        return self._available

    def update(self) -> None:
        try:
            props = self._client.get_properties_sync()
            self._current_temp = props.get(PROP_KETTLE_TEMP)
            self._target_temp = props.get(PROP_KETTLE_TARGET)
            self._is_on = bool(props.get(PROP_KETTLE_SWITCH))
            self._available = True
        except Exception as exc:
            _LOGGER.warning("Aigostar kettle [%s] update failed: %s", self._attr_unique_id, exc)
            self._available = False

    def set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        try:
            self._client.set_properties_sync({PROP_KETTLE_TARGET: int(temp)})
            self._target_temp = temp
        except Exception as exc:
            _LOGGER.error("Aigostar kettle [%s] set_temperature failed: %s", self._attr_unique_id, exc)

    def turn_on(self, **kwargs: Any) -> None:
        try:
            self._client.set_properties_sync({PROP_KETTLE_SWITCH: 1})
            self._is_on = True
        except Exception as exc:
            _LOGGER.error("Aigostar kettle [%s] turn_on failed: %s", self._attr_unique_id, exc)

    def turn_off(self, **kwargs: Any) -> None:
        try:
            self._client.set_properties_sync({PROP_KETTLE_SWITCH: 0})
            self._is_on = False
        except Exception as exc:
            _LOGGER.error("Aigostar kettle [%s] turn_off failed: %s", self._attr_unique_id, exc)
