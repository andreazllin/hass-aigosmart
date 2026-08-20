#!/usr/bin/env python3
"""
Diagnostic: log in and dump the REAL TSL property identifiers of each device.

Use this to debug Alibaba IoT error 5092 "property not found": it prints the
exact property names the device exposes, so we can compare them against the
hardcoded names in const.py (LightSwitch / Brightness / ColorTemperature /
LightMode).

Run it from the repo root:

    AIGO_EMAIL='you@example.com' AIGO_PASSWORD='yourpassword' \
        python3 scripts/dump_device_props.py

If the account asks for an email verification code, set AIGO_CODE too.
Requires the `cryptography` package (same dependency the integration uses).
"""
from __future__ import annotations

import importlib.util
import os

_PKG = os.path.join(os.path.dirname(__file__), "..", "custom_components", "aigostar")


def _load(name: str):
    """Load a module directly by file path, bypassing the package __init__
    (which imports homeassistant and isn't available outside HA)."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(_PKG, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


api = _load("alibaba_api")
const = _load("const")
APP_KEY, APP_SECRET = const.APP_KEY, const.APP_SECRET


def main() -> int:
    email = os.environ.get("AIGO_EMAIL", "").strip()
    password = os.environ.get("AIGO_PASSWORD", "")
    code = os.environ.get("AIGO_CODE", "").strip()

    if not email or not password:
        print("Set AIGO_EMAIL and AIGO_PASSWORD environment variables.")
        return 2

    try:
        session = api.full_login_sync(email, password, APP_KEY, APP_SECRET, code)
    except api.NeedSecurityCodeError as exc:
        print(f"Email verification required: {exc}")
        print("Re-run with AIGO_CODE=<code-from-email>.")
        return 3

    iot_token = session["iotToken"]
    print("Login OK.\n")

    devices = api.list_devices_sync(APP_KEY, APP_SECRET, iot_token)
    print(f"Found {len(devices)} device(s).\n")

    for dev in devices:
        iot_id = dev.get("iotId", "")
        nick = dev.get("nickName") or dev.get("deviceName") or iot_id
        print("=" * 70)
        print(f"Device: {nick}")
        print(f"  iotId       : {iot_id}")
        print(f"  productName : {dev.get('productName')}")
        print(f"  productKey  : {dev.get('productKey')}")
        print(f"  status      : {dev.get('status')} (1 = online)")

        # 1) Current property values -> these keys are the REAL identifiers.
        try:
            res = api._call_sync(
                api.PATH_GET, {"iotId": iot_id},
                APP_KEY, APP_SECRET, iot_token,
            )
            data = res.get("data", {})
            print("\n  --- properties/get (real identifiers currently reported) ---")
            if data:
                for key, val in data.items():
                    v = val.get("value") if isinstance(val, dict) else val
                    print(f"    {key!r}: {v}")
            else:
                print("    (empty — device may be offline; try again with it online)")
        except Exception as exc:
            print(f"  properties/get failed: {exc}")

        # 2) Full TSL model (definitive list of all supported properties).
        for path, params in (
            ("/thing/tsl/get", {"iotId": iot_id}),
            ("/thing/tsl/get", {"productKey": dev.get("productKey")}),
        ):
            try:
                res = api._call_sync(path, params, APP_KEY, APP_SECRET, iot_token)
                tsl = res.get("data", {})
                props = (tsl.get("tsl") or tsl).get("properties") if isinstance(tsl, dict) else None
                if props:
                    print("\n  --- TSL properties (definitive supported list) ---")
                    for p in props:
                        print(f"    identifier={p.get('identifier')!r}  "
                              f"name={p.get('name')!r}  "
                              f"dataType={(p.get('dataType') or {}).get('type')}")
                    break
            except Exception:
                continue

    print("\nDone. Please share the identifiers listed above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
