"""
Light platform for Aigostar — multi-device support.

Wi-Fi TSL properties (TG7100C):
  - LightSwitch      bool    0/1
  - Brightness       int     1-100
  - ColorTemperature int     0-100  (0=warm 2700K, 100=cool 6500K)
  - LightMode        enum    0=white 1=color
  - HSVColor         struct  {Hue:0-360, Saturation:0-100, Value:0-100}

Bluetooth Mesh TSL properties (bulbs behind an Aigostar hub, netType NET_BT):
  - powerstate       bool    0/1
  - brightness       int     1-100
  - colorTemperature int     0-100
  - mode             enum    white/color

Mesh products do not share the Wi-Fi colour identifier and their ranges differ
per product, so the colour property is resolved from each product's own TSL
model at setup time rather than hard-coded — see color_model.py.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .alibaba_api import AlibabaIoTClient, get_tsl_sync
from .color_model import (
    ColorSpec,
    as_source_snippet,
    color_spec_from_props,
    color_spec_from_tsl,
    known_profile,
    mode_spec_from_tsl,
)
from .const import (
    AIGO_BRIGHT_MAX,
    AIGO_BRIGHT_MIN,
    DOMAIN,
    HA_BRIGHT_MAX,
    KELVIN_COOL,
    KELVIN_WARM,
    PROP_BRIGHTNESS,
    PROP_COLOR_TEMP,
    PROP_LIGHT_MODE,
    PROP_SWITCH,
    PROP_MESH_SWITCH,
    PROP_MESH_BRIGHTNESS,
    PROP_MESH_COLOR_TEMP,
    PROP_MESH_LIGHT_MODE,
    NET_TYPE_BT,
    SCAN_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECONDS)


def _tsl_cache_key(dev: dict) -> str:
    """Devices of the same product share a TSL model; fall back to the device."""
    return dev.get("productKey") or dev.get("iotId", "")


async def _async_load_tsl_models(
    hass: HomeAssistant, devices: list[dict],
    app_key: str, app_secret: str, iot_token: str,
) -> dict[str, dict]:
    """Fetch the TSL model once per product so colour support can be detected."""
    models: dict[str, dict] = {}
    for dev in devices:
        iot_id = dev.get("iotId")
        cache_key = _tsl_cache_key(dev)
        if not iot_id or not cache_key or cache_key in models:
            continue
        try:
            models[cache_key] = await hass.async_add_executor_job(
                get_tsl_sync, app_key, app_secret, iot_token, iot_id,
            )
        except Exception as exc:
            _LOGGER.warning(
                "Aigostar: TSL model fetch failed for %s (product %s): %s — "
                "colour support will be detected from live properties instead",
                iot_id, dev.get("productKey"), exc,
            )
    return models


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    devices = entry_data["devices"]
    iot_token = entry_data["iot_token"]
    app_key = entry_data["app_key"]
    app_secret = entry_data["app_secret"]

    tsl_models = await _async_load_tsl_models(
        hass, devices, app_key, app_secret, iot_token,
    )
    entry_data["tsl_models"] = tsl_models

    entities = []
    for dev in devices:
        if dev.get("categoryKey") == "gateway" or dev.get("category") == "gateway":
            continue

        iot_id = dev.get("iotId", "")
        nick = dev.get("nickName") or dev.get("deviceName") or iot_id[:12]
        status = dev.get("status", 0)

        client = AlibabaIoTClient(
            iot_id=iot_id,
            iot_token=iot_token,
            app_key=app_key,
            app_secret=app_secret,
        )
        entities.append(
            AigostarLight(
                client, iot_id, nick,
                online=(status == 1),
                raw_device=dev,
                tsl=tsl_models.get(_tsl_cache_key(dev)),
            )
        )

    # Register entities for token refresh
    hass.data.setdefault(f"{DOMAIN}_entities", {})
    hass.data[f"{DOMAIN}_entities"][entry.entry_id] = entities

    _LOGGER.info("Aigostar: creating %d light entities", len(entities))
    async_add_entities(entities, update_before_add=True)


class AigostarLight(LightEntity):
    """Aigostar smart bulb."""

    _attr_has_entity_name = True
    _attr_name = None  # Use device name as entity name
    _attr_min_color_temp_kelvin = KELVIN_WARM
    _attr_max_color_temp_kelvin = KELVIN_COOL

    def __init__(
        self, client: AlibabaIoTClient, iot_id: str, name: str,
        online: bool, raw_device: dict | None = None,
        tsl: dict | None = None,
    ) -> None:
        self._client = client
        self._attr_unique_id = iot_id

        raw = raw_device or {}
        product_name = raw.get("productName") or raw.get("categoryName") or "Smart Bulb"
        fw_version = raw.get("firmwareVersion") or raw.get("moduleVersion") or None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=name,
            manufacturer="Aigostar",
            model=product_name,
            sw_version=fw_version,
        )

        self._is_bt: bool = raw.get("netType") == NET_TYPE_BT

        # Transport-specific property identifiers
        self._prop_switch = PROP_MESH_SWITCH if self._is_bt else PROP_SWITCH
        self._prop_brightness = PROP_MESH_BRIGHTNESS if self._is_bt else PROP_BRIGHTNESS
        self._prop_color_temp = PROP_MESH_COLOR_TEMP if self._is_bt else PROP_COLOR_TEMP

        # Colour capability: a confirmed profile for this product if there is
        # one, otherwise resolved from the product's own TSL model.
        product_key = self._product_key = raw.get("productKey", "")
        fallback_mode = PROP_MESH_LIGHT_MODE if self._is_bt else PROP_LIGHT_MODE
        profile = known_profile(product_key)
        if profile is not None:
            self._color_spec: ColorSpec | None = profile.color
            self._mode_spec = profile.mode
        else:
            tsl = tsl or {}
            self._color_spec = color_spec_from_tsl(tsl)
            self._mode_spec = mode_spec_from_tsl(tsl, fallback_mode)

        self._spec_source = "pinned" if profile else "TSL"
        self._attr_supported_color_modes = self._build_supported_color_modes()
        if self._color_spec is not None:
            _LOGGER.info("Aigostar %s", self.describe_color_profile())

        self._is_on:        bool = False
        self._brightness:   int  = 255
        self._color_temp_k: int  = 4000
        self._color_mode:   ColorMode = ColorMode.COLOR_TEMP
        # Whether _color_mode reflects a real reading rather than the default
        # assumption above. Until it does, the mode is always written out.
        self._mode_known:   bool = False
        self._hs_color:     tuple[float, float] = (0.0, 0.0)
        self._available:    bool = online

        _LOGGER.debug(
            "Aigostar [%s] Initialized light entity. Name: '%s', is_bt: %s, netType: '%s', "
            "color_spec: %s, mode_spec: %s, raw_device: %s",
            iot_id, name, self._is_bt, raw.get("netType"),
            self._color_spec, self._mode_spec, raw,
        )

    def update_token(self, new_token: str) -> None:
        """Update the iotToken after a refresh."""
        self._client.iot_token = new_token

    def describe_color_profile(self) -> str:
        """Human-readable resolution result, with a pasteable pinning entry."""
        if self._color_spec is None:
            return (
                f"[{self._attr_unique_id}] productKey {self._product_key or '?'}: "
                f"no colour property resolved — white/colour-temperature only"
            )
        return (
            f"[{self._attr_unique_id}] resolved colour profile for productKey "
            f"{self._product_key or '?'} (source: {self._spec_source}) — add to "
            f"KNOWN_PRODUCT_PROFILES in color_model.py:\n"
            + as_source_snippet(self._product_key, self._color_spec, self._mode_spec)
        )

    def _build_supported_color_modes(self) -> set[ColorMode]:
        if self._color_spec is not None:
            return {ColorMode.COLOR_TEMP, ColorMode.HS}
        return {ColorMode.COLOR_TEMP}

    # ------------------------------------------------------------------
    # Conversions
    # ------------------------------------------------------------------

    @staticmethod
    def _aigo_to_ha_brightness(v: int) -> int:
        pct = (v - AIGO_BRIGHT_MIN) / (AIGO_BRIGHT_MAX - AIGO_BRIGHT_MIN)
        return max(1, round(pct * HA_BRIGHT_MAX))

    @staticmethod
    def _ha_to_aigo_brightness(v: int) -> int:
        pct = v / HA_BRIGHT_MAX
        return max(AIGO_BRIGHT_MIN, min(AIGO_BRIGHT_MAX, round(pct * AIGO_BRIGHT_MAX)))

    @staticmethod
    def _aigo_to_kelvin(v: int) -> int:
        """0 = warm 2700K, 100 = cool 6500K."""
        pct = v / 100.0
        return round(KELVIN_WARM + pct * (KELVIN_COOL - KELVIN_WARM))

    @staticmethod
    def _kelvin_to_aigo(k: int) -> int:
        pct = (k - KELVIN_WARM) / (KELVIN_COOL - KELVIN_WARM)
        return max(0, min(100, round(pct * 100)))

    # ------------------------------------------------------------------
    # HA properties
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int:
        return self._brightness

    @property
    def color_temp_kelvin(self) -> int:
        return self._color_temp_k

    @property
    def color_mode(self) -> ColorMode:
        return self._color_mode

    @property
    def hs_color(self) -> tuple[float, float]:
        return self._hs_color

    @property
    def available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Update (polling)
    # ------------------------------------------------------------------

    def _ensure_color_spec(self, props: dict) -> None:
        """
        Late colour detection for products whose TSL model could not be read.
        Runs before the entity is added to HA (update_before_add=True), so the
        advertised colour modes are still accurate.
        """
        if self._color_spec is not None:
            return
        spec = color_spec_from_props(props)
        if spec is None:
            return
        self._color_spec = spec
        self._spec_source = "live properties (ranges are inferred, not declared)"
        self._attr_supported_color_modes = self._build_supported_color_modes()
        _LOGGER.info("Aigostar %s", self.describe_color_profile())

    def _apply_props(self, props: dict) -> None:
        _LOGGER.debug(
            "Aigostar [%s] Applying properties (is_bt=%s): %s",
            self._attr_unique_id, self._is_bt, props,
        )
        self._ensure_color_spec(props)

        if self._prop_switch in props:
            self._is_on = bool(props[self._prop_switch])
            _LOGGER.debug(
                "Aigostar [%s] Parsed is_on: %s (from key '%s' value %s)",
                self._attr_unique_id, self._is_on, self._prop_switch,
                props[self._prop_switch],
            )

        in_color_mode = False
        if self._mode_spec.identifier in props:
            try:
                raw_mode = int(props[self._mode_spec.identifier])
            except (TypeError, ValueError):
                pass
            else:
                self._mode_known = True
                in_color_mode = (
                    self._color_spec is not None
                    and raw_mode == self._mode_spec.color_value
                )
        self._color_mode = ColorMode.HS if in_color_mode else ColorMode.COLOR_TEMP

        color_brightness_pct: float | None = None
        if self._color_spec is not None:
            raw_color = props.get(self._color_spec.identifier)
            hs = self._color_spec.to_hs(raw_color) if raw_color is not None else None
            if hs is not None:
                self._hs_color = hs
                color_brightness_pct = self._color_spec.to_brightness_pct(raw_color)
                _LOGGER.debug(
                    "Aigostar [%s] Parsed hs_color: %s (from key '%s' value %s)",
                    self._attr_unique_id, self._hs_color,
                    self._color_spec.identifier, raw_color,
                )

        # In colour mode the struct's value/lightness component is the brightness
        if in_color_mode and color_brightness_pct is not None:
            self._brightness = self._aigo_to_ha_brightness(round(color_brightness_pct))
        elif self._prop_brightness in props:
            self._brightness = self._aigo_to_ha_brightness(int(props[self._prop_brightness]))
            _LOGGER.debug(
                "Aigostar [%s] Parsed brightness: %s (from key '%s' value %s)",
                self._attr_unique_id, self._brightness, self._prop_brightness,
                props[self._prop_brightness],
            )

        if self._prop_color_temp in props:
            self._color_temp_k = self._aigo_to_kelvin(int(props[self._prop_color_temp]))
            _LOGGER.debug(
                "Aigostar [%s] Parsed color_temp: %s K (from key '%s' value %s)",
                self._attr_unique_id, self._color_temp_k, self._prop_color_temp,
                props[self._prop_color_temp],
            )

    def update(self) -> None:
        try:
            props = self._client.get_properties_sync()
            self._apply_props(props)
            self._available = True
        except Exception as exc:
            _LOGGER.warning("Aigostar [%s] update failed: %s", self._attr_unique_id, exc)
            self._available = False

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def _color_struct(self, hue: float, saturation: float, ha_brightness: int) -> dict[str, Any]:
        """Build the raw colour struct for the given HA hue/saturation/brightness."""
        assert self._color_spec is not None
        return self._color_spec.build(
            hue, saturation, self._ha_to_aigo_brightness(ha_brightness),
        )

    def turn_on(self, **kwargs: Any) -> None:
        _LOGGER.debug(
            "Aigostar [%s] turn_on called with kwargs: %s (is_bt=%s)",
            self._attr_unique_id, kwargs, self._is_bt,
        )
        try:
            items: dict[str, Any] = {self._prop_switch: 1}

            # The light-mode switch is written separately, after the colour or
            # colour-temperature value it activates. Sending both in one payload
            # lets the gateway apply them in either order, and when the mode
            # lands first the bulb briefly shows its previously stored colour.
            pending_mode: int | None = None

            requested_brightness = kwargs.get(ATTR_BRIGHTNESS)
            requested_hs = kwargs.get(ATTR_HS_COLOR)

            if requested_hs is not None and self._color_spec is not None:
                hue, saturation = requested_hs
                ha_b = (
                    int(requested_brightness)
                    if requested_brightness is not None
                    else self._brightness
                )
                items[self._color_spec.identifier] = self._color_struct(hue, saturation, ha_b)
                if not self._mode_known or self._color_mode != ColorMode.HS:
                    pending_mode = self._mode_spec.color_value
                self._hs_color = (float(hue), float(saturation))
                self._color_mode = ColorMode.HS
                self._brightness = ha_b

            elif requested_brightness is not None:
                ha_b = int(requested_brightness)
                if self._color_mode == ColorMode.HS and self._color_spec is not None:
                    # Keep the current hue/saturation while dimming in colour mode
                    items[self._color_spec.identifier] = self._color_struct(*self._hs_color, ha_b)
                else:
                    items[self._prop_brightness] = self._ha_to_aigo_brightness(ha_b)
                self._brightness = ha_b

            if ATTR_COLOR_TEMP_KELVIN in kwargs:
                k = int(kwargs[ATTR_COLOR_TEMP_KELVIN])
                items[self._prop_color_temp] = self._kelvin_to_aigo(k)
                if not self._mode_known or self._color_mode != ColorMode.COLOR_TEMP:
                    pending_mode = self._mode_spec.white_value
                self._color_temp_k = k
                self._color_mode = ColorMode.COLOR_TEMP

            _LOGGER.debug(
                "Aigostar [%s] Sending set_properties_sync (is_bt=%s): %s (pending_mode=%s)",
                self._attr_unique_id, self._is_bt, items, pending_mode,
            )
            self._client.set_properties_sync(items)

            if pending_mode is not None:
                mode_items = {self._mode_spec.identifier: pending_mode}
                _LOGGER.debug(
                    "Aigostar [%s] Sending light-mode switch: %s",
                    self._attr_unique_id, mode_items,
                )
                self._client.set_properties_sync(mode_items)

            self._is_on     = True
            self._available = True

        except Exception as exc:
            _LOGGER.error("Aigostar turn_on failed [%s]: %s", self._attr_unique_id, exc)
            self._available = False

    def turn_off(self, **kwargs: Any) -> None:
        _LOGGER.debug("Aigostar [%s] turn_off called (is_bt=%s)", self._attr_unique_id, self._is_bt)
        try:
            items = {self._prop_switch: 0}
            _LOGGER.debug(
                "Aigostar [%s] Sending set_properties_sync for off (is_bt=%s): %s",
                self._attr_unique_id, self._is_bt, items,
            )
            self._client.set_properties_sync(items)
            self._is_on     = False
            self._available = True
        except Exception as exc:
            _LOGGER.error("Aigostar turn_off failed [%s]: %s", self._attr_unique_id, exc)
            self._available = False
