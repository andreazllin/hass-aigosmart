# Aigosmart for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/andreazllin/hass-aigosmart?style=for-the-badge)](https://github.com/andreazllin/hass-aigosmart/releases)

A Home Assistant custom integration for **Aigostar smart bulbs** (TG7100C chipset).

Control your Aigostar lights directly from Home Assistant — no local flashing required. The integration communicates with the same backend as the AigoSmart app.

## Features

- **Automatic device discovery** — all bulbs linked to your AigoSmart account are added automatically
- **Periodic device sync** — new bulbs added via the AigoSmart app are detected every 5 minutes
- **Manual sync service** — `aigosmart.sync_devices` to force device re-discovery
- **Automatic token refresh** — iotToken is renewed before expiration
- **Brightness control** (1–100%)
- **Color temperature** (2700K warm – 6500K cool)
- **Email verification** support (when the server requires a security code)
- **Multilingual UI** — English, Italian, French, Spanish and German translations included


## Fans

Aigostar smart fans on the same AigoSmart account are supported as well. They are
detected automatically (`categoryKey: fan`) and exposed as a proper `fan` entity
instead of an unusable light.

| Control | Entity | TSL property |
|---|---|---|
| On / off, speed 1-3 | `fan.*` | `powerstate`, `windspeed` |
| Preset modes: Normal, Natural, Sleep | `fan.*` | `mode` |
| Left/right swing | `fan.*` | `angleAutoLROnOff` |
| Auto-off timer, 0-24 h | `number.*` | `appointmentClosingTime` |
| Key beep | `switch.*` | `buzzerSwitch` |

The fan also reports `CuTemperature`. It is **not** exposed: the probe sits next to
the motor and reads its warm air, not the room temperature.

Verified on a 5-blade Aigostar tower fan (`productKey a1mZFNZz7pq`). Other fans using
the same TSL should work; open an issue with the output of `/thing/tsl/get` if yours
differs.

## Supported Devices

| Device | Chipset | Protocol | Status |
|--------|---------|----------|--------|
| Aigostar smart bulb (E27/E14/GU10) | TG7100C (Bouffalo Lab) | AigoSmart | Tested |

> Other Aigostar smart devices using the AigoSmart app may work but have not been tested.

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=andreazllin&repository=hass-aigosmart&category=integration)

Click the button above, or manually:

1. Open HACS in Home Assistant
2. Go to **Integrations** → **⋮** (top right) → **Custom repositories**
3. Add this repository URL: `https://github.com/andreazllin/hass-aigosmart`
4. Select **Integration** as the category
5. Click **Add**, then find **Aigosmart** in the list and install it
6. Restart Home Assistant

### Manual

1. Download or clone this repository
2. Copy the `custom_components/aigosmart` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=aigosmart)

Or manually:

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Aigosmart**
3. Enter your **AigoSmart** account email and password
4. If the server requests a verification code, enter the code sent to your email
5. All bulbs linked to your account will be discovered automatically

## Services

### `aigosmart.sync_devices`

Force re-discovery of all devices from your Aigostar account. New devices are added automatically. You can call this service from:

- **Developer Tools** → **Services**
- Automations or scripts

## How It Works

The integration uses the same 5-step login flow as the AigoSmart Android app (reverse-engineered via APK decompilation):

1. **UC Login** — authenticate with email/password on Aigostar User Center
2. **UC Authorize** — obtain an authorization code
3. **Region Discovery** — resolve the correct EU OAuth API gateway
4. **OAuth Login** — exchange the authCode for an OA session ID
5. **IoT Session** — exchange the session ID for an iotToken

Device control is performed via the same API gateway used by the AigoSmart app.

## Troubleshooting

### Login fails
- Verify your email and password are correct (same as the AigoSmart app)
- If you get a verification code prompt, check your email inbox (including spam)

### Devices show as unavailable
- The bulb must be powered on and connected to Wi-Fi
- Check that the bulb works in the AigoSmart app first

### New bulbs not appearing
- Wait up to 5 minutes for auto-sync, or call `aigosmart.sync_devices`
- You can also reload the integration: **Settings** → **Integrations** → **Aigostar** → **⋮** → **Reload**

## Disclaimer

This initial integration was built by [@MarcoM1993](https://github.com/MarcoM1993) from scratch by reverse engineering the AigoSmart app — no public API, no documentation, just hours of packet sniffing and APK decompilation.

It is unofficial and not affiliated with Aigostar, for personal and educational use.

Use at your own risk.
