import sys
import os
from unittest.mock import MagicMock, patch
import pytest
import asyncio

# Create mock classes for Home Assistant base classes
class DummyLightEntity:
    _attr_name = None
    _attr_unique_id = None

    @property
    def name(self):
        return self._attr_name

    @property
    def unique_id(self):
        return self._attr_unique_id

class DummyColorMode:
    COLOR_TEMP = "color_temp"
    HS = "hs"

# Mock the modules
mock_light = MagicMock()
mock_light.LightEntity = DummyLightEntity
mock_light.ColorMode = DummyColorMode
mock_light.ATTR_BRIGHTNESS = "brightness"
mock_light.ATTR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
mock_light.ATTR_HS_COLOR = "hs_color"

mock_core = MagicMock()
mock_config_entries = MagicMock()
mock_device_registry = MagicMock()
mock_device_registry.DeviceInfo = lambda **kwargs: kwargs

sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.light"] = mock_light
sys.modules["homeassistant.config_entries"] = mock_config_entries
sys.modules["homeassistant.core"] = mock_core
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.device_registry"] = mock_device_registry
sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.data_entry_flow"] = MagicMock()


# Ensure the custom_components directory is in the import path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from custom_components.aigostar.const import (
    DOMAIN,
    PROP_SWITCH,
    PROP_BRIGHTNESS,
    PROP_COLOR_TEMP,
    PROP_LIGHT_MODE,
    PROP_MESH_SWITCH,
    PROP_MESH_BRIGHTNESS,
    PROP_MESH_COLOR_TEMP,
    PROP_MESH_LIGHT_MODE,
)
from custom_components.aigostar.light import AigostarLight, async_setup_entry


def test_wifi_light_properties():
    # Test property mapping and commands for a WiFi light
    client = MagicMock()
    raw_device = {
        "netType": "NET_WIFI",
        "productName": "WiFi Bulb",
        "firmwareVersion": "1.0.0"
    }

    light = AigostarLight(client, "test_iot_id", "My WiFi Bulb", online=True, raw_device=raw_device)

    # Check initialized state
    assert not light._is_bt
    assert light.name is None  # _attr_name is None
    assert light.available

    # Test applying WiFi properties
    light._apply_props({
        PROP_SWITCH: 1,
        PROP_BRIGHTNESS: 50,
        PROP_COLOR_TEMP: 50,
    })

    assert light.is_on
    assert light.brightness == 126  # (50-1)/(100-1) * 255 = 126.2 -> 126
    assert light.color_temp_kelvin == 4600  # 2700 + 0.5 * (6500 - 2700)

    # Test turn_on command — the mode is written after the value it activates
    client.reset_mock()
    light.turn_on(brightness=255, color_temp_kelvin=6500)
    assert client.set_properties_sync.call_args_list == [
        (({PROP_SWITCH: 1, PROP_BRIGHTNESS: 100, PROP_COLOR_TEMP: 100},),),
        (({PROP_LIGHT_MODE: 0},),),
    ]

    # Test turn_off command
    light.turn_off()
    client.set_properties_sync.assert_called_with({
        PROP_SWITCH: 0
    })


def test_bt_mesh_light_properties():
    # Test property mapping and commands for a BT Mesh light
    client = MagicMock()
    raw_device = {
        "netType": "NET_BT",
        "productName": "Mesh Bulb",
        "firmwareVersion": "1.0.0"
    }

    light = AigostarLight(client, "test_iot_id", "My Mesh Bulb", online=True, raw_device=raw_device)

    # Check initialized state
    assert light._is_bt
    assert light.available

    # Test applying BT properties
    light._apply_props({
        PROP_MESH_SWITCH: 1,
        PROP_MESH_BRIGHTNESS: 50,
        PROP_MESH_COLOR_TEMP: 50,
    })

    assert light.is_on
    assert light.brightness == 126
    assert light.color_temp_kelvin == 4600

    # Test turn_on command — the mode is written after the value it activates
    client.reset_mock()
    light.turn_on(brightness=255, color_temp_kelvin=6500)
    assert client.set_properties_sync.call_args_list == [
        (({PROP_MESH_SWITCH: 1, PROP_MESH_BRIGHTNESS: 100, PROP_MESH_COLOR_TEMP: 100},),),
        (({PROP_MESH_LIGHT_MODE: 0},),),
    ]

    # Test turn_off command
    light.turn_off()
    client.set_properties_sync.assert_called_with({
        PROP_MESH_SWITCH: 0
    })


WIFI_COLOR_TSL = {
    "properties": [
        {
            "identifier": "HSVColor",
            "dataType": {
                "type": "struct",
                "specs": [
                    {"identifier": "Hue", "dataType": {"type": "int", "specs": {"min": "0", "max": "360"}}},
                    {"identifier": "Saturation", "dataType": {"type": "int", "specs": {"min": "0", "max": "100"}}},
                    {"identifier": "Value", "dataType": {"type": "int", "specs": {"min": "0", "max": "100"}}},
                ],
            },
        },
        {
            "identifier": "LightMode",
            "dataType": {"type": "enum", "specs": {"0": "White", "1": "Colour"}},
        },
    ]
}

# Bluetooth Mesh products mirror the SIG Light HSL model: lower-camelCase
# identifiers and 16-bit ranges.
MESH_COLOR_TSL = {
    "properties": [
        {
            "identifier": "hslColor",
            "dataType": {
                "type": "struct",
                "specs": [
                    {"identifier": "hue", "dataType": {"type": "int", "specs": {"min": "0", "max": "65535"}}},
                    {"identifier": "saturation", "dataType": {"type": "int", "specs": {"min": "0", "max": "65535"}}},
                    {"identifier": "lightness", "dataType": {"type": "int", "specs": {"min": "0", "max": "65535"}}},
                ],
            },
        },
        {
            "identifier": "mode",
            "dataType": {"type": "enum", "specs": {"0": "white", "2": "color"}},
        },
    ]
}


def test_wifi_light_hs_color():
    client = MagicMock()
    raw_device = {"netType": "NET_WIFI", "productName": "WiFi RGBCCT Bulb"}

    light = AigostarLight(
        client, "wifi_rgb", "RGB Bulb", online=True,
        raw_device=raw_device, tsl=WIFI_COLOR_TSL,
    )

    assert light._attr_supported_color_modes == {DummyColorMode.COLOR_TEMP, DummyColorMode.HS}

    light._apply_props({
        PROP_SWITCH: 1,
        PROP_LIGHT_MODE: 1,
        "HSVColor": {"Hue": 120, "Saturation": 100, "Value": 100},
    })

    assert light.color_mode == DummyColorMode.HS
    assert light.hs_color == (120.0, 100.0)
    assert light.brightness == 255

    # Already in colour mode: a single write, with no redundant mode switch
    client.reset_mock()
    light.turn_on(hs_color=(240.0, 50.0), brightness=255)
    assert client.set_properties_sync.call_args_list == [
        (({PROP_SWITCH: 1, "HSVColor": {"Hue": 240, "Saturation": 50, "Value": 100}},),),
    ]

    # Dimming in colour mode preserves hue/saturation
    client.reset_mock()
    light.turn_on(brightness=128)
    assert client.set_properties_sync.call_args_list == [
        (({PROP_SWITCH: 1, "HSVColor": {"Hue": 240, "Saturation": 50, "Value": 50}},),),
    ]


def test_mode_switch_is_written_after_the_colour_it_activates():
    # Sending the colour struct and the mode switch in one payload lets the
    # gateway apply the mode first, which makes the bulb flash its previously
    # stored colour. The mode must therefore be a separate, later write.
    client = MagicMock()
    light = AigostarLight(
        client, "wifi_rgb2", "RGB Bulb", online=True,
        raw_device={"netType": "NET_WIFI"}, tsl=WIFI_COLOR_TSL,
    )

    # Starts in colour-temp mode, so switching to a colour needs a mode change
    assert light.color_mode == DummyColorMode.COLOR_TEMP

    light.turn_on(hs_color=(120.0, 100.0), brightness=255)
    assert client.set_properties_sync.call_args_list == [
        (({PROP_SWITCH: 1, "HSVColor": {"Hue": 120, "Saturation": 100, "Value": 100}},),),
        (({PROP_LIGHT_MODE: 1},),),
    ]

    # Going back to white likewise writes the temperature before the mode
    client.reset_mock()
    light.turn_on(color_temp_kelvin=6500)
    assert client.set_properties_sync.call_args_list == [
        (({PROP_SWITCH: 1, PROP_COLOR_TEMP: 100},),),
        (({PROP_LIGHT_MODE: 0},),),
    ]


def test_known_product_profile_short_circuits_tsl_detection():
    from custom_components.aigostar.color_model import (
        ColorSpec,
        ModeSpec,
        ProductProfile,
        KNOWN_PRODUCT_PROFILES,
    )

    profile = ProductProfile(
        color=ColorSpec(
            identifier="hsvColor",
            encoding="hsv",
            members={"hue": "hue", "saturation": "saturation", "value": "value"},
            maxima={"hue": 360.0, "saturation": 100.0, "value": 100.0},
        ),
        mode=ModeSpec(identifier="LightMode", white_value=0, color_value=1),
    )
    KNOWN_PRODUCT_PROFILES["pk_test"] = profile
    try:
        client = MagicMock()
        # No TSL passed at all — the pinned profile supplies the capability
        light = AigostarLight(
            client, "pinned", "Pinned Bulb", online=True,
            raw_device={"netType": "NET_BT", "productKey": "pk_test"},
        )
        assert light._color_spec is profile.color
        assert light._attr_supported_color_modes == {
            DummyColorMode.COLOR_TEMP, DummyColorMode.HS,
        }

        light.turn_on(hs_color=(120.0, 100.0), brightness=255)
        assert client.set_properties_sync.call_args_list == [
            (({PROP_MESH_SWITCH: 1,
               "hsvColor": {"hue": 120, "saturation": 100, "value": 100}},),),
            (({PROP_MESH_LIGHT_MODE: 1},),),
        ]
    finally:
        KNOWN_PRODUCT_PROFILES.pop("pk_test", None)


def test_bt_mesh_light_hs_color_scales_16bit():
    client = MagicMock()
    raw_device = {"netType": "NET_BT", "productName": "Mesh RGB Bulb"}

    light = AigostarLight(
        client, "mesh_rgb", "Mesh RGB Bulb", online=True,
        raw_device=raw_device, tsl=MESH_COLOR_TSL,
    )

    assert light._is_bt
    assert light._attr_supported_color_modes == {DummyColorMode.COLOR_TEMP, DummyColorMode.HS}
    # Both the identifier and the colour enum value come from the TSL
    assert light._mode_spec.identifier == "mode"
    assert light._mode_spec.color_value == 2
    assert light._mode_spec.white_value == 0

    light._apply_props({
        PROP_MESH_SWITCH: 1,
        "mode": 2,
        "hslColor": {"hue": 32768, "saturation": 65535, "lightness": 65535},
    })

    assert light.color_mode == DummyColorMode.HS
    assert round(light.hs_color[0]) == 180
    assert light.hs_color[1] == 100.0
    assert light.brightness == 255

    # Already in colour mode, so no redundant mode write
    client.reset_mock()
    light.turn_on(hs_color=(0.0, 100.0), brightness=255)
    assert client.set_properties_sync.call_args_list == [
        (({PROP_MESH_SWITCH: 1,
           "hslColor": {"hue": 0, "saturation": 65535, "lightness": 65535}},),),
    ]

    # Colour temperature switches the device back to white mode
    client.reset_mock()
    light.turn_on(color_temp_kelvin=6500)
    assert client.set_properties_sync.call_args_list == [
        (({PROP_MESH_SWITCH: 1, PROP_MESH_COLOR_TEMP: 100},),),
        (({"mode": 0},),),
    ]
    assert light.color_mode == DummyColorMode.COLOR_TEMP


def test_color_spec_detected_from_live_properties_when_tsl_missing():
    # Products whose TSL cannot be fetched still gain colour support from the
    # shape of the properties the device reports.
    client = MagicMock()
    raw_device = {"netType": "NET_BT", "productName": "Mesh RGB Bulb"}

    light = AigostarLight(client, "mesh_no_tsl", "Mesh Bulb", online=True, raw_device=raw_device)
    assert light._attr_supported_color_modes == {DummyColorMode.COLOR_TEMP}

    light._apply_props({
        PROP_MESH_SWITCH: 1,
        PROP_MESH_LIGHT_MODE: 1,
        "rgbColor": {"red": 255, "green": 0, "blue": 0},
    })

    assert light._attr_supported_color_modes == {DummyColorMode.COLOR_TEMP, DummyColorMode.HS}
    assert light.hs_color == (0.0, 100.0)

    # The poll reported mode=1 (colour), so no redundant mode write is needed
    client.reset_mock()
    light.turn_on(hs_color=(120.0, 100.0), brightness=255)
    assert client.set_properties_sync.call_args_list == [
        (({PROP_MESH_SWITCH: 1, "rgbColor": {"red": 0, "green": 255, "blue": 0}},),),
    ]


def test_struct_property_returned_as_json_string():
    # Some devices report struct properties as JSON strings rather than objects
    client = MagicMock()
    light = AigostarLight(
        client, "wifi_rgb_str", "RGB Bulb", online=True,
        raw_device={"netType": "NET_WIFI"}, tsl=WIFI_COLOR_TSL,
    )

    light._apply_props({
        PROP_SWITCH: 1,
        PROP_LIGHT_MODE: 1,
        "HSVColor": '{"Hue": 240, "Saturation": 80, "Value": 100}',
    })

    assert light.hs_color == (240.0, 80.0)
    assert light.color_mode == DummyColorMode.HS


def test_light_without_color_support_is_unchanged():
    client = MagicMock()
    tsl = {"properties": [{"identifier": "Brightness", "dataType": {"type": "int"}}]}

    light = AigostarLight(
        client, "white_only", "White Bulb", online=True,
        raw_device={"netType": "NET_BT"}, tsl=tsl,
    )

    assert light._attr_supported_color_modes == {DummyColorMode.COLOR_TEMP}
    assert light._color_spec is None

    light.turn_on(hs_color=(120.0, 100.0), brightness=255)
    client.set_properties_sync.assert_called_with({
        PROP_MESH_SWITCH: 1,
        PROP_MESH_BRIGHTNESS: 100,
    })


# Trimmed from the real /thing/tsl/get response for the mesh "Downlight RGB CCT".
# Note the hybrid naming and the large "mode" scene enum.
DOWNLIGHT_RGBCCT_TSL = {
    "properties": [
        {
            "identifier": "LightMode",
            "dataType": {"type": "enum", "specs": {"0": "mono", "1": "color"}},
        },
        {
            "identifier": "colorTemperature",
            "dataType": {"type": "int", "specs": {"min": "0", "max": "100", "step": "1"}},
        },
        {
            "identifier": "HSVColor",
            "dataType": {
                "type": "struct",
                "specs": [
                    {"identifier": "Hue", "dataType": {"type": "double", "specs": {"min": "0", "max": "360", "step": "0.01"}}},
                    {"identifier": "Saturation", "dataType": {"type": "double", "specs": {"min": "0", "max": "100", "step": "0.01"}}},
                    {"identifier": "Value", "dataType": {"type": "double", "specs": {"min": "0", "max": "100", "step": "0.01"}}},
                ],
            },
        },
        {"identifier": "powerstate", "dataType": {"type": "bool", "specs": {"0": "Off", "1": "On"}}},
        {
            "identifier": "brightness",
            "dataType": {"type": "int", "specs": {"min": "1", "max": "100", "step": "25"}},
        },
        {
            # Scene selector — must never be picked as the white/colour switch
            "identifier": "mode",
            "dataType": {
                "type": "enum",
                "specs": {
                    "0": "关闭", "1": "春天", "2": "夏天", "3": "秋天", "4": "冬天",
                    "5": "初阳", "6": "彩虹", "7": "火焰", "8": "水纹", "9": "闪电",
                    "251": "呼吸", "252": "跳变", "254": "频闪",
                },
            },
        },
    ]
}


def test_scene_enum_is_not_mistaken_for_the_light_mode_switch():
    # "mode" here selects an animation (spring, rainbow, strobe...). Writing to
    # it would start an effect rather than switch between white and colour.
    client = MagicMock()
    light = AigostarLight(
        client, "downlight", "Downlight", online=True,
        raw_device={"netType": "NET_BT"}, tsl=DOWNLIGHT_RGBCCT_TSL,
    )

    assert light._mode_spec.identifier == "LightMode"
    assert light._mode_spec.white_value == 0
    assert light._mode_spec.color_value == 1
    assert light._color_spec.identifier == "HSVColor"
    assert light._color_spec.maxima == {"hue": 360.0, "saturation": 100.0, "value": 100.0}

    light.turn_on(hs_color=(127.0, 71.0), brightness=230)
    written = [c[0][0] for c in client.set_properties_sync.call_args_list]
    assert all("mode" not in items for items in written)
    assert written == [
        {PROP_MESH_SWITCH: 1, "HSVColor": {"Hue": 127, "Saturation": 71, "Value": 90}},
        {"LightMode": 1},
    ]


def test_pinned_downlight_profile_matches_the_tsl():
    # The shipped profile for the real product must agree with what detection
    # derives from that product's TSL, so pinning cannot silently drift.
    from custom_components.aigostar.color_model import (
        KNOWN_PRODUCT_PROFILES,
        color_spec_from_tsl,
        mode_spec_from_tsl,
    )

    profile = KNOWN_PRODUCT_PROFILES["a1uh0UxUu3Z"]
    assert profile.color == color_spec_from_tsl(DOWNLIGHT_RGBCCT_TSL)
    assert profile.mode == mode_spec_from_tsl(DOWNLIGHT_RGBCCT_TSL, "LightMode")


def test_tsl_is_fetched_by_iot_id_once_per_product():
    # /thing/tsl/get keys off iotId — passing productKey fails with code 20050
    # "iotId required". The model is still per product, so fetch it once per
    # productKey using any one of that product's devices.
    from custom_components.aigostar.light import _async_load_tsl_models

    calls = []

    class FakeHass:
        async def async_add_executor_job(self, func, *args):
            calls.append(args)
            return {"properties": []}

    devices = [
        {"iotId": "dev_a1", "productKey": "pk_shared"},
        {"iotId": "dev_a2", "productKey": "pk_shared"},
        {"iotId": "dev_b1", "productKey": "pk_other"},
        {"iotId": "dev_c1"},  # no productKey — keyed by iotId
    ]

    models = asyncio.run(
        _async_load_tsl_models(FakeHass(), devices, "key", "secret", "token")
    )

    # One fetch per product, each carrying an iotId as the final argument
    assert [c[-1] for c in calls] == ["dev_a1", "dev_b1", "dev_c1"]
    assert all("pk_shared" not in c and "pk_other" not in c for c in calls)
    assert set(models) == {"pk_shared", "pk_other", "dev_c1"}


@patch("custom_components.aigostar.light.AlibabaIoTClient")
def test_async_setup_entry_skips_gateway(mock_client_class):
    # Test async_setup_entry filters out gateway devices and creates other light entities
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry_id"

    devices = [
        {
            "iotId": "gateway_id",
            "nickName": "Mesh Gateway",
            "categoryKey": "gateway",
            "netType": "NET_WIFI"
        },
        {
            "iotId": "light_id",
            "nickName": "Mesh Light",
            "category": "light",
            "netType": "NET_BT"
        }
    ]

    hass.data = {
        DOMAIN: {
            "test_entry_id": {
                "devices": devices,
                "iot_token": "token",
                "app_key": "key",
                "app_secret": "secret"
            }
        }
    }

    async_add_entities = MagicMock()

    asyncio.run(async_setup_entry(hass, entry, async_add_entities))

    # Verify we registered only the light entity, not the gateway
    assert len(hass.data[f"{DOMAIN}_entities"]["test_entry_id"]) == 1
    entity = hass.data[f"{DOMAIN}_entities"]["test_entry_id"][0]
    assert entity.unique_id == "light_id"
    assert entity._is_bt

    async_add_entities.assert_called_once()
