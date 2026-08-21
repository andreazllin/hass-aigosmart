# Aigostar Smart Lights — Claude Code Project Guide

## Project Overview

Custom Home Assistant integration for Aigostar smart bulbs (TG7100C chipset).
These bulbs use **Alibaba Cloud IoT** as their backend (not Tuya cloud, despite the Tuya-OEM chip).
The integration communicates via the Alibaba Cloud IoT API Gateway using x-ca-signature authentication.

## Architecture

### Login Flow (5 steps, reverse-engineered from AigoSmart APK)

1. **UC Login** — `POST uc.aigostar.com/v1.0/connect/token` → access_token
2. **UC Authorize** — `GET uc.aigostar.com/v1.0/connect/authorize` → authCode
3. **Region Discovery** — `POST api.link.aliyun.com/living/account/region/get` → OA host
4. **OAuth Login** — `POST {oaHost}/api/prd/loginbyoauth.json` → sid (OA session)
5. **IoT Session** — `POST eu-central-1.api-iot.aliyuncs.com/account/createSessionByAuthCode` → iotToken

### API Authentication

- **UC API** (uc.aigostar.com): Custom MD5 signature → `MD5(AppKey + AESKey + timestamp + METHOD + URL + sortedParams)`
- **IoT API** (api-iot.aliyuncs.com): x-ca-signature → `Base64(HMAC-SHA1(canonical_string, AppSecret))`
- **Canonical string format**: `METHOD\nACCEPT\nCONTENT-MD5\nCONTENT-TYPE\nDATE\nCANONICAL-HEADERS\nPATH`
- **Password encryption**: AES-256-CBC, key = `tCx8BA0yKVr+NbBChH928URAV90=0000`, IV = 16 zero bytes

### API Credentials (from APK decompilation via jadx)

- AppKey: `28770785` (Android), `28803202` (iOS)
- Source: `com.aigostar.lib.aigo.api.constants.CommonValueApiConstant` in classes2.dex
- These are public app credentials, not user secrets

### TSL Properties (device data model)

| Property | Type | Range | Description |
|----------|------|-------|-------------|
| LightSwitch | bool | 0/1 | On/off |
| Brightness | int | 1-100 | Percentage |
| ColorTemperature | int | 0-100 | 0=warm 2700K, 100=cool 6500K |
| LightMode | enum | 0/1 | 0=white, 1=color (only white on TG7100C) |

## File Structure

```
custom_components/aigostar/
├── __init__.py      — Entry setup, token refresh/persistence, device sync, services
├── alibaba_api.py   — Full API client: login flow, device list, property get/set, TSL fetch
├── brand/           — Integration icons for HA 2026.3+ (icon.png, icon@2x.png)
├── color_model.py   — Colour-property detection from TSL models (Wi-Fi + BT Mesh)
├── config_flow.py   — HA config flow: email/password login or manual token entry
├── const.py         — Constants: API keys, TSL property names, conversion ranges
├── fan.py           — FanEntity: speed, preset modes, oscillation
├── helpers.py       — Shared entity registry + device-type predicates
├── light.py         — LightEntity: polling, brightness/color_temp/HS colour control
├── manifest.json    — HA integration metadata
├── number.py        — Fan auto-off timer
├── services.yaml    — sync_devices + dump_tsl service definitions
├── strings.json     — UI strings (English, canonical)
├── switch.py        — Fan key beep, kettle boiling/keep-warm switches
├── translations/    — en.json, it.json, fr.json, es.json, de.json
└── water_heater.py  — Kettle: on/off, current/target temperature

scripts/dump_device_props.py — CLI diagnostic: dump real TSL identifiers per device
tests/test_light.py          — Light platform unit tests (plain pytest, HA mocked)
```

## Key Technical Details

- **Token refresh**: iotToken expires (default 7200s). Refreshed automatically every hour via `refreshToken` or full re-login as fallback.
- **Device sync**: New devices auto-detected every 5 minutes. Manual sync via `aigostar.sync_devices` service.
- **Polling interval**: 30 seconds (`SCAN_INTERVAL_SECONDS` in const.py).
- **EU region**: All endpoints use eu-central-1. Region is resolved dynamically via the region API.
- **OA login quirk**: `oauthPlateform` must be integer `23`, not string. Field name is intentionally misspelled (matches the API).

## Development Workflow

### Branches
- `main` — the only branch: all work happens here, releases are tagged `vX.Y.Z` (see Release Process below)

### Release Process (Claude-driven versioning)

Versioning is manual and done locally by Claude; CI only publishes.

**When the user says "new major version", "new minor version" or "new patch version"**, do exactly this:

1. Make sure the release commit will contain only the manifest bump — stash or set aside any unrelated pending changes first
2. Read the current version from `custom_components/aigostar/manifest.json`
3. Bump the requested part (semver): major → `X+1.0.0`, minor → `X.Y+1.0`, patch → `X.Y.Z+1`
4. Write the new version into `manifest.json`
5. Commit only that file with the message `chore(release): vX.Y.Z`
6. Create an annotated tag on that commit: `git tag -a vX.Y.Z -m "vX.Y.Z"` (annotated, so `--follow-tags` pushes it)
7. Do **NOT** push by default — the user pushes with `git push origin main --follow-tags`.
   Only if the user explicitly asks for the push as part of the release request
   (e.g. "new minor version and push"), run `git push origin main --follow-tags`
   after tagging — this publishes the release, so never infer it

When the tag reaches GitHub, `.github/workflows/release.yml`:
- verifies the tag matches the manifest version (fails otherwise)
- builds `aigostar.zip` from `custom_components/aigostar/` — the HACS artifact (`zip_release` + `filename` in hacs.json point HACS at this release asset)
- creates the GitHub Release with auto-generated notes: commit list and full-changelog diff link since the previous release

No PAT/secret is required: the workflow never pushes commits, so the default `GITHUB_TOKEN` is enough.

### Deploy to Home Assistant (dev/test)
```bash
# Set up SSH password file
python3 -c "f=open('/tmp/.sshpw','w'); f.write('YOUR_PASSWORD'); f.close()"

# Sync files to HA
sshpass -f /tmp/.sshpw rsync -av -e "ssh -o PreferredAuthentications=password -o StrictHostKeyChecking=no" \
  custom_components/aigostar/ USER@HA_IP:/config/custom_components/aigostar/

# Restart HA via API
curl -s -X POST -H "Authorization: Bearer YOUR_TOKEN" \
  http://HA_IP:8123/api/services/homeassistant/restart
```

### Testing commands via HA API
```bash
# Turn on with brightness and color temp
curl -X POST -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" \
  -d '{"entity_id": "light.ENTITY", "brightness": 128, "color_temp_kelvin": 3500}' \
  http://HA_IP:8123/api/services/light/turn_on

# Call sync service
curl -X POST -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" \
  -d '{}' http://HA_IP:8123/api/services/aigostar/sync_devices
```

## Language

- Code, comments, docstrings, log messages: **English**
- User communicates in **Italian** — respond in Italian
- All code, comments, docstrings, log messages, and CLI output must be in **English**

## Translations (user-facing strings)

Supported languages: **English, Italian, French, Spanish, German**
(`translations/en.json`, `it.json`, `fr.json`, `es.json`, `de.json`).

**Whenever you add or change a user-facing string** (config flow steps, error
messages, service names/descriptions, entity names via translation keys):

1. Update `strings.json` first — it is the canonical English source
2. Update **all five** files in `translations/` with the same key structure
3. `translations/en.json` must stay identical to `strings.json`
4. Verify key parity across files, e.g.:
   ```bash
   python3 -c "
   import json
   def keys(d, p=''):
       return {f'{p}.{k}' for k in d} | {x for k, v in d.items() if isinstance(v, dict) for x in keys(v, f'{p}.{k}')}
   ref = keys(json.load(open('custom_components/aigostar/strings.json')))
   for lang in ('en', 'it', 'fr', 'es', 'de'):
       got = keys(json.load(open(f'custom_components/aigostar/translations/{lang}.json')))
       assert got == ref, (lang, ref ^ got)
   print('translations OK')"
   ```

Never leave a language file behind: a missing key silently falls back to the
raw key name in the HA UI.
