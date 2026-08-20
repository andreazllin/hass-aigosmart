"""Aigostar integration for Home Assistant — automatic login."""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_time_interval

from .alibaba_api import (
    AlibabaIoTClient,
    full_login_sync,
    get_tsl_sync,
    list_devices_sync,
    refresh_iot_token_sync,
)
from .const import (
    APP_KEY,
    APP_SECRET,
    CONF_EMAIL,
    CONF_IDENTITY_ID,
    CONF_IOT_TOKEN,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["light", "fan", "number", "switch", "water_heater"]
TOKEN_REFRESH_INTERVAL = timedelta(hours=1)
DEVICE_SYNC_INTERVAL = timedelta(minutes=5)

# Internal keys used to persist token metadata across restarts
_CONF_TOKEN_EXPIRE = "token_expire"
_CONF_TOKEN_ISSUED_AT = "token_issued_at"

SERVICE_SYNC = "sync_devices"
SERVICE_DUMP_TSL = "dump_tsl"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = dict(entry.data)
    email = data.get(CONF_EMAIL, "")
    password = data.get(CONF_PASSWORD, "")

    def _persist_tokens(
        iot_token: str, refresh_token: str, identity_id: str,
        token_expire: int, token_created: float,
    ) -> None:
        """Write the session tokens back to the config entry so they survive restarts."""
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_IOT_TOKEN: iot_token,
                CONF_REFRESH_TOKEN: refresh_token,
                CONF_IDENTITY_ID: identity_id,
                _CONF_TOKEN_EXPIRE: token_expire,
                _CONF_TOKEN_ISSUED_AT: token_created,
            },
        )

    # Try the persisted session first so a restart does not need a full re-login
    iot_token = data.get(CONF_IOT_TOKEN, "")
    refresh_token = data.get(CONF_REFRESH_TOKEN, "")
    identity_id = data.get(CONF_IDENTITY_ID, "")
    token_expire = int(data.get(_CONF_TOKEN_EXPIRE, 7200))
    token_created = float(data.get(_CONF_TOKEN_ISSUED_AT) or time.time())

    devices = None
    if iot_token:
        try:
            devices = await hass.async_add_executor_job(
                list_devices_sync, APP_KEY, APP_SECRET, iot_token,
            )
            _LOGGER.info("Aigostar: stored iotToken valid, %d devices discovered", len(devices))
        except Exception as exc:
            _LOGGER.info("Aigostar: stored iotToken rejected (%s), trying refresh", exc)
            if refresh_token and identity_id:
                try:
                    new_session = await hass.async_add_executor_job(
                        refresh_iot_token_sync,
                        refresh_token, identity_id, APP_KEY, APP_SECRET,
                    )
                    iot_token = new_session["iotToken"]
                    refresh_token = new_session.get("refreshToken", refresh_token)
                    identity_id = new_session.get("identityId", identity_id)
                    token_expire = int(new_session.get("iotTokenExpire", 7200))
                    token_created = time.time()
                    devices = await hass.async_add_executor_job(
                        list_devices_sync, APP_KEY, APP_SECRET, iot_token,
                    )
                    _persist_tokens(iot_token, refresh_token, identity_id, token_expire, token_created)
                    _LOGGER.info("Aigostar: token refreshed, %d devices discovered", len(devices))
                except Exception as exc2:
                    _LOGGER.info("Aigostar: token refresh failed (%s), falling back to full login", exc2)

    if devices is None:
        if not email or not password:
            _LOGGER.error(
                "Aigostar: stored tokens are no longer valid and the entry has no "
                "account credentials — re-add the integration with fresh tokens"
            )
            return False

        # Full login
        session = await hass.async_add_executor_job(
            full_login_sync, email, password, APP_KEY, APP_SECRET,
        )

        iot_token = session["iotToken"]
        refresh_token = session.get("refreshToken", "")
        identity_id = session.get("identityId", "")
        token_expire = int(session.get("iotTokenExpire", 7200))
        token_created = time.time()

        # Discover devices
        devices = await hass.async_add_executor_job(
            list_devices_sync, APP_KEY, APP_SECRET, iot_token,
        )
        _persist_tokens(iot_token, refresh_token, identity_id, token_expire, token_created)
        _LOGGER.info("Aigostar: login OK, %d devices discovered", len(devices))

    # Shared state
    entry_data = {
        "devices": devices,
        "iot_token": iot_token,
        "refresh_token": refresh_token,
        "identity_id": identity_id,
        "token_expire": token_expire,
        "token_created": token_created,
        "email": email,
        "password": password,
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
    }

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry_data

    # Periodic token refresh
    async def _refresh_token(_now=None):
        ed = hass.data[DOMAIN].get(entry.entry_id)
        if not ed:
            return

        elapsed = time.time() - ed["token_created"]
        if elapsed < ed["token_expire"] - 1800:
            return

        try:
            if ed["refresh_token"] and ed["identity_id"]:
                new_session = await hass.async_add_executor_job(
                    refresh_iot_token_sync,
                    ed["refresh_token"], ed["identity_id"],
                    APP_KEY, APP_SECRET,
                )
            else:
                new_session = await hass.async_add_executor_job(
                    full_login_sync,
                    ed["email"], ed["password"],
                    APP_KEY, APP_SECRET,
                )

            new_token = new_session["iotToken"]
            ed["iot_token"] = new_token
            ed["refresh_token"] = new_session.get("refreshToken", ed["refresh_token"])
            ed["identity_id"] = new_session.get("identityId", ed["identity_id"])
            ed["token_expire"] = int(new_session.get("iotTokenExpire", 7200))
            ed["token_created"] = time.time()
            _persist_tokens(
                new_token, ed["refresh_token"], ed["identity_id"],
                ed["token_expire"], ed["token_created"],
            )

            for entity in hass.data.get(f"{DOMAIN}_entities", {}).get(entry.entry_id, []):
                entity.update_token(new_token)

            _LOGGER.info("Aigostar: iotToken refreshed successfully")

        except Exception as exc:
            _LOGGER.warning("Aigostar: token refresh failed, retrying with full login: %s", exc)
            try:
                new_session = await hass.async_add_executor_job(
                    full_login_sync,
                    ed["email"], ed["password"],
                    APP_KEY, APP_SECRET,
                )
                new_token = new_session["iotToken"]
                ed["iot_token"] = new_token
                ed["refresh_token"] = new_session.get("refreshToken", "")
                ed["identity_id"] = new_session.get("identityId", "")
                ed["token_expire"] = int(new_session.get("iotTokenExpire", 7200))
                ed["token_created"] = time.time()
                _persist_tokens(
                    new_token, ed["refresh_token"], ed["identity_id"],
                    ed["token_expire"], ed["token_created"],
                )

                for entity in hass.data.get(f"{DOMAIN}_entities", {}).get(entry.entry_id, []):
                    entity.update_token(new_token)

                _LOGGER.info("Aigostar: iotToken obtained via re-login")
            except Exception as exc2:
                _LOGGER.error("Aigostar: re-login also failed: %s", exc2)

    # Periodic device sync: check for new devices
    async def _periodic_sync(_now=None):
        ed = hass.data[DOMAIN].get(entry.entry_id)
        if not ed:
            return
        try:
            devices = await hass.async_add_executor_job(
                list_devices_sync, APP_KEY, APP_SECRET, ed["iot_token"],
            )
            known_ids = {d["iotId"] for d in ed["devices"] if "iotId" in d}
            new_ids = {d["iotId"] for d in devices if d.get("iotId")} - known_ids
            if new_ids:
                _LOGGER.info("Aigostar auto-sync: %d new devices found, reloading integration", len(new_ids))
                await hass.config_entries.async_reload(entry.entry_id)
        except Exception as exc:
            _LOGGER.debug("Aigostar auto-sync failed: %s", exc)

    # Immediate refresh callable — used by entities when they detect a
    # token-expired error mid-flight (bypasses the elapsed-time guard).
    async def _force_refresh() -> None:
        ed = hass.data[DOMAIN].get(entry.entry_id)
        if not ed:
            return
        ed["token_created"] = 0  # Reset so _refresh_token always triggers
        await _refresh_token()

    unsub_refresh = async_track_time_interval(hass, _refresh_token, TOKEN_REFRESH_INTERVAL)
    unsub_sync = async_track_time_interval(hass, _periodic_sync, DEVICE_SYNC_INTERVAL)
    entry_data["unsub_refresh"] = unsub_refresh
    entry_data["unsub_sync"] = unsub_sync
    entry_data["force_refresh"] = _force_refresh

    # Manual service: aigostar.sync_devices (reloads the integration)
    async def _handle_sync_service(call: ServiceCall) -> None:
        for eid in list(hass.data.get(DOMAIN, {})):
            cfg_entry = hass.config_entries.async_get_entry(eid)
            if cfg_entry:
                _LOGGER.info("Aigostar sync_devices: reloading integration %s", cfg_entry.title)
                await hass.config_entries.async_reload(eid)

    # Diagnostic service: aigostar.dump_tsl
    # Logs each product's TSL model plus a live property snapshot at WARNING
    # level so it lands in home-assistant.log without enabling debug logging.
    # This is how unknown property identifiers (notably on BT Mesh bulbs) are
    # identified when adding support for a new product.
    async def _handle_dump_tsl_service(call: ServiceCall) -> None:
        for eid, ed in list(hass.data.get(DOMAIN, {}).items()):
            if not isinstance(ed, dict) or "devices" not in ed:
                continue
            seen_products: set[str] = set()
            for dev in ed["devices"]:
                iot_id = dev.get("iotId", "")
                product_key = dev.get("productKey", "")
                _LOGGER.warning(
                    "Aigostar dump_tsl: device %s | name=%s | netType=%s | "
                    "productKey=%s | category=%s | raw=%s",
                    iot_id, dev.get("nickName"), dev.get("netType"),
                    product_key, dev.get("categoryKey") or dev.get("category"), dev,
                )

                if not iot_id:
                    continue

                # The TSL endpoint keys off iotId, but the model is per product,
                # so fetch it only once per productKey.
                cache_key = product_key or iot_id
                if cache_key not in seen_products:
                    seen_products.add(cache_key)
                    try:
                        tsl = await hass.async_add_executor_job(
                            get_tsl_sync, ed["app_key"], ed["app_secret"],
                            ed["iot_token"], iot_id,
                        )
                        _LOGGER.warning(
                            "Aigostar dump_tsl: TSL model for product %s: %s",
                            product_key or iot_id, tsl,
                        )
                    except Exception as exc:
                        _LOGGER.warning(
                            "Aigostar dump_tsl: TSL fetch failed for %s (product %s): %s",
                            iot_id, product_key, exc,
                        )
                try:
                    client = AlibabaIoTClient(
                        iot_id=iot_id, iot_token=ed["iot_token"],
                        app_key=ed["app_key"], app_secret=ed["app_secret"],
                    )
                    props = await hass.async_add_executor_job(client.get_properties_sync)
                    _LOGGER.warning(
                        "Aigostar dump_tsl: live properties for %s: %s", iot_id, props,
                    )
                except Exception as exc:
                    _LOGGER.warning(
                        "Aigostar dump_tsl: property read failed for %s: %s", iot_id, exc,
                    )

            # Report what each entity actually resolved, as a pasteable entry
            for entity in hass.data.get(f"{DOMAIN}_entities", {}).get(eid, []):
                if not hasattr(entity, "describe_color_profile"):
                    continue
                _LOGGER.warning(
                    "Aigostar dump_tsl: %s", entity.describe_color_profile(),
                )

    if not hass.services.has_service(DOMAIN, SERVICE_SYNC):
        hass.services.async_register(DOMAIN, SERVICE_SYNC, _handle_sync_service)
    if not hass.services.has_service(DOMAIN, SERVICE_DUMP_TSL):
        hass.services.async_register(DOMAIN, SERVICE_DUMP_TSL, _handle_dump_tsl_service)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    for key in ("unsub_refresh", "unsub_sync"):
        unsub = entry_data.get(key)
        if unsub:
            unsub()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data.get(f"{DOMAIN}_entities", {}).pop(entry.entry_id, None)
        # Remove services if no entries remain
        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_SYNC)
            hass.services.async_remove(DOMAIN, SERVICE_DUMP_TSL)
    return unload_ok
