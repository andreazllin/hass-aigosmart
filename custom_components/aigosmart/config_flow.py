"""Config flow for Aigostar — email + password login, or manual token entry."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .alibaba_api import (
    NeedSecurityCodeError,
    full_login_sync,
    list_devices_sync,
    refresh_iot_token_sync,
    send_verification_code_sync,
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

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_TOKEN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IOT_TOKEN): str,
        vol.Required(CONF_REFRESH_TOKEN): str,
        vol.Required(CONF_IDENTITY_ID): str,
    }
)

STEP_VERIFY_SCHEMA = vol.Schema(
    {
        vol.Required("security_code"): str,
    }
)


class AigosmartConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow: asks for email + password, optionally a verification code."""

    VERSION = 5

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """First step: choose between account login and manual token entry."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["login", "token_bypass"],
        )

    async def async_step_login(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            try:
                session = await self.hass.async_add_executor_job(
                    full_login_sync,
                    self._email, self._password, APP_KEY, APP_SECRET,
                )
                return await self._finish_login(session, user_input)

            except NeedSecurityCodeError:
                _LOGGER.info("Server requires verification code for %s", self._email)
                try:
                    await self.hass.async_add_executor_job(
                        send_verification_code_sync, self._email,
                    )
                except Exception as exc:
                    _LOGGER.warning("Failed to send verification code: %s", exc)
                return await self.async_step_verify()

            except ValueError as exc:
                _LOGGER.warning("Aigosmart login failed: %s", exc)
                errors["base"] = "cannot_connect"
            except ImportError as exc:
                _LOGGER.error("Missing dependency: %s", exc)
                errors["base"] = "unknown"
            except Exception as exc:
                _LOGGER.exception("Aigosmart login error: %s", exc)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="login",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_token_bypass(self, user_input: dict | None = None) -> FlowResult:
        """Accept a session captured externally (e.g. with mitmproxy from the
        AigoSmart app) — a workaround for accounts stuck on NEED_SECURITY_CODE."""
        errors: dict[str, str] = {}

        if user_input is not None:
            iot_token = user_input[CONF_IOT_TOKEN].strip()
            refresh_token = user_input[CONF_REFRESH_TOKEN].strip()
            identity_id = user_input[CONF_IDENTITY_ID].strip()

            devices = None
            try:
                devices = await self.hass.async_add_executor_job(
                    list_devices_sync, APP_KEY, APP_SECRET, iot_token,
                )
                _LOGGER.info("Aigosmart token entry: %d devices found", len(devices))
            except Exception as exc:
                # Token might already be expired — try the refreshToken
                _LOGGER.info("Aigosmart: provided iotToken rejected (%s), trying refresh", exc)
                try:
                    new_session = await self.hass.async_add_executor_job(
                        refresh_iot_token_sync,
                        refresh_token, identity_id, APP_KEY, APP_SECRET,
                    )
                    iot_token = new_session["iotToken"]
                    refresh_token = new_session.get("refreshToken", refresh_token)
                    identity_id = new_session.get("identityId", identity_id)
                    devices = await self.hass.async_add_executor_job(
                        list_devices_sync, APP_KEY, APP_SECRET, iot_token,
                    )
                    _LOGGER.info(
                        "Aigosmart token entry (after refresh): %d devices found", len(devices),
                    )
                except Exception as exc2:
                    _LOGGER.warning("Aigosmart token entry failed: %s", exc2)
                    errors["base"] = "invalid_token"

            if devices is not None:
                await self.async_set_unique_id("aigosmart_account")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Aigosmart ({len(devices)} lights)",
                    data={
                        CONF_EMAIL: "",
                        CONF_PASSWORD: "",
                        CONF_IOT_TOKEN: iot_token,
                        CONF_REFRESH_TOKEN: refresh_token,
                        CONF_IDENTITY_ID: identity_id,
                    },
                )

        return self.async_show_form(
            step_id="token_bypass",
            data_schema=STEP_TOKEN_SCHEMA,
            errors=errors,
        )

    async def async_step_verify(self, user_input: dict | None = None) -> FlowResult:
        """Step 2: ask for the verification code sent via email."""
        errors: dict[str, str] = {}

        if user_input is not None:
            code = user_input["security_code"].strip()
            try:
                session = await self.hass.async_add_executor_job(
                    full_login_sync,
                    self._email, self._password, APP_KEY, APP_SECRET, code,
                )
                return await self._finish_login(
                    session, {CONF_EMAIL: self._email, CONF_PASSWORD: self._password},
                )
            except NeedSecurityCodeError:
                errors["base"] = "invalid_code"
            except ValueError as exc:
                _LOGGER.warning("Login with code failed: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception as exc:
                _LOGGER.exception("Aigosmart verification error: %s", exc)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="verify",
            data_schema=STEP_VERIFY_SCHEMA,
            errors=errors,
        )

    async def _finish_login(self, session: dict, user_input: dict) -> FlowResult:
        """Complete the login: list devices and create config entry."""
        devices = await self.hass.async_add_executor_job(
            list_devices_sync, APP_KEY, APP_SECRET, session["iotToken"],
        )
        _LOGGER.info("Aigosmart: login OK, %d devices found", len(devices))

        await self.async_set_unique_id("aigosmart_account")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Aigosmart ({len(devices)} lights)",
            data={
                **user_input,
                # Store the session so setup can skip the full login
                CONF_IOT_TOKEN: session.get("iotToken", ""),
                CONF_REFRESH_TOKEN: session.get("refreshToken", ""),
                CONF_IDENTITY_ID: session.get("identityId", ""),
            },
        )
