"""
Fan platform for Aigostar — Alibaba Cloud IoT.

TSL properties (captured via /thing/tsl/get on productKey a1mZFNZz7pq,
categoryKey "fan"):
  powerstate             bool  rw  0=off 1=on
  windspeed              enum  rw  1 | 2 | 3
  mode                   enum  rw  0=normal wind, 1=natural wind, 2=sleep wind
  angleAutoLROnOff       bool  rw  left/right auto swing
  appointmentClosingTime int   rw  auto-off timer, 0-24 h  (number platform)
  buzzerSwitch           bool  rw  key beep               (switch platform)
  CuTemperature          int   r   onboard temperature — reads the motor's own
                                   warm air, not the room: deliberately not
                                   exposed as an entity.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .alibaba_api import AlibabaIoTClient
from .helpers import is_fan_device, register_for_token_refresh
from .const import (
    DOMAIN,
    FAN_PRESET_MODES,
    FAN_SPEEDS,
    PROP_FAN_MODE,
    PROP_FAN_OSCILLATE,
    PROP_FAN_POWER,
    PROP_FAN_SPEED,
    SCAN_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECONDS)

PRESET_TO_VALUE = {v: k for k, v in FAN_PRESET_MODES.items()}


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
        nick = dev.get("nickName") or dev.get("deviceName") or iot_id[:12]
        client = AlibabaIoTClient(
            iot_id=iot_id,
            iot_token=entry_data["iot_token"],
            app_key=entry_data["app_key"],
            app_secret=entry_data["app_secret"],
        )
        entities.append(
            AigosmartFan(client, iot_id, nick.strip(), dev.get("status", 0) == 1, dev)
        )

    register_for_token_refresh(hass, entry, entities)
    _LOGGER.info("Aigosmart: creating %d fan entities", len(entities))
    async_add_entities(entities, update_before_add=True)


class AigosmartFan(FanEntity):
    """Aigostar smart fan."""

    _attr_has_entity_name = True
    _attr_name = None  # use the device name
    _attr_preset_modes = list(FAN_PRESET_MODES.values())
    _attr_speed_count = len(FAN_SPEEDS)
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.OSCILLATE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        client: AlibabaIoTClient,
        iot_id: str,
        name: str,
        online: bool,
        raw_device: dict | None = None,
    ) -> None:
        self._client = client
        self._attr_unique_id = iot_id

        raw = raw_device or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=name,
            manufacturer="Aigostar",
            model=(raw.get("productName") or raw.get("categoryName") or "Fan").strip(),
            sw_version=raw.get("firmwareVersion") or raw.get("moduleVersion") or None,
        )

        self._is_on: bool = False
        self._speed: int = FAN_SPEEDS[0]
        self._mode: int = 0
        self._oscillating: bool = False
        self._available: bool = online

    def update_token(self, new_token: str) -> None:
        """Update the iotToken after a refresh."""
        self._client.iot_token = new_token

    # ------------------------------------------------------------------
    # HA properties
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def available(self) -> bool:
        return self._available

    @property
    def percentage(self) -> int:
        if not self._is_on:
            return 0
        return ordered_list_item_to_percentage(FAN_SPEEDS, self._speed)

    @property
    def preset_mode(self) -> str | None:
        return FAN_PRESET_MODES.get(self._mode)

    @property
    def oscillating(self) -> bool:
        return self._oscillating

    # ------------------------------------------------------------------
    # Update (polling)
    # ------------------------------------------------------------------

    def _apply_props(self, props: dict) -> None:
        if PROP_FAN_POWER in props:
            self._is_on = bool(int(props[PROP_FAN_POWER]))
        if PROP_FAN_SPEED in props:
            try:
                speed = int(props[PROP_FAN_SPEED])
                if speed in FAN_SPEEDS:
                    self._speed = speed
            except (TypeError, ValueError):
                pass
        if PROP_FAN_MODE in props:
            try:
                self._mode = int(props[PROP_FAN_MODE])
            except (TypeError, ValueError):
                pass
        if PROP_FAN_OSCILLATE in props:
            self._oscillating = bool(int(props[PROP_FAN_OSCILLATE]))

    def update(self) -> None:
        try:
            self._apply_props(self._client.get_properties_sync())
            self._available = True
        except Exception as exc:
            _LOGGER.warning("Aigosmart fan [%s] update failed: %s", self._attr_unique_id, exc)
            self._available = False

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        items: dict[str, Any] = {PROP_FAN_POWER: 1}
        if percentage:
            items[PROP_FAN_SPEED] = percentage_to_ordered_list_item(FAN_SPEEDS, percentage)
        if preset_mode in PRESET_TO_VALUE:
            items[PROP_FAN_MODE] = PRESET_TO_VALUE[preset_mode]

        self._client.set_properties_sync(items)
        self._is_on = True
        if PROP_FAN_SPEED in items:
            self._speed = items[PROP_FAN_SPEED]
        if PROP_FAN_MODE in items:
            self._mode = items[PROP_FAN_MODE]
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs: Any) -> None:
        self._client.set_properties_sync({PROP_FAN_POWER: 0})
        self._is_on = False
        self.schedule_update_ha_state()

    def set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            self.turn_off()
            return
        speed = percentage_to_ordered_list_item(FAN_SPEEDS, percentage)
        items: dict[str, Any] = {PROP_FAN_SPEED: speed}
        if not self._is_on:
            items[PROP_FAN_POWER] = 1
        self._client.set_properties_sync(items)
        self._speed = speed
        self._is_on = True
        self.schedule_update_ha_state()

    def set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in PRESET_TO_VALUE:
            return
        value = PRESET_TO_VALUE[preset_mode]
        self._client.set_properties_sync({PROP_FAN_MODE: value})
        self._mode = value
        self.schedule_update_ha_state()

    def oscillate(self, oscillating: bool) -> None:
        self._client.set_properties_sync({PROP_FAN_OSCILLATE: 1 if oscillating else 0})
        self._oscillating = oscillating
        self.schedule_update_ha_state()
