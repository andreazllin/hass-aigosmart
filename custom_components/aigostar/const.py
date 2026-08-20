"""Constants for the Aigostar integration."""

DOMAIN = "aigostar"

# Alibaba Cloud IoT EU endpoint
ALIBABA_IOT_HOST = "eu-central-1.api-iot.aliyuncs.com"
ALIBABA_IOT_BASE = f"https://{ALIBABA_IOT_HOST}"
ENDPOINT_GET     = "/thing/properties/get"
ENDPOINT_SET     = "/thing/properties/set"

# API credentials extracted from the AigoSmart Android APK (public, not user secrets)
APP_KEY    = "28770785"
APP_SECRET = "41fd4a1eb18fa7ace5e2abbbe3867f93"

# Config entry keys
CONF_EMAIL       = "email"
CONF_PASSWORD    = "password"

# TSL properties for Aigostar TG7100C (captured via /thing/tsl/get)
PROP_SWITCH     = "LightSwitch"       # bool  0=off 1=on
PROP_BRIGHTNESS = "Brightness"        # int   1-100 (percentage)
PROP_COLOR_TEMP = "ColorTemperature"  # int   0-100 (0=warm 2700K, 100=cool 6500K)
PROP_LIGHT_MODE = "LightMode"         # enum  0=white 1=color(RGB)
PROP_HSV_COLOR  = "HSVColor"          # struct {Hue:0-360, Saturation:0-100, Value:0-100}

# BT Mesh properties.
# Confirmed against /thing/tsl/get for the "Downlight RGB CCT" (a1uh0UxUu3Z):
# these products are hybrids. The switch, brightness and colour temperature use
# mesh identifiers, but colour and the white/colour switch reuse the Wi-Fi ones.
PROP_MESH_SWITCH     = "powerstate"
PROP_MESH_BRIGHTNESS = "brightness"        # int 1-100, but declared step 25
PROP_MESH_COLOR_TEMP = "colorTemperature"  # int 0-100
PROP_MESH_LIGHT_MODE = "LightMode"         # enum 0=mono 1=color

# "mode" is a scene/effect selector on these products (spring, rainbow,
# candlelight, strobe, ...), NOT the white/colour switch. Writing to it starts
# an animation, so it must never be treated as the light-mode property.
PROP_MESH_SCENE      = "mode"

NET_TYPE_BT          = "NET_BT"

# Some Wi-Fi products use the lower-camelCase identifiers despite not being
# mesh devices (confirmed on the "A60 RGB CCT" bulb, productKey a1tgw5jbxTS),
# so netType alone does not determine the naming. The light entity starts from
# the transport default and refines its identifiers at runtime by matching the
# properties the device actually reports (first candidate present wins).
PROP_SWITCH_CANDIDATES     = (PROP_SWITCH, PROP_MESH_SWITCH)
PROP_BRIGHTNESS_CANDIDATES = (PROP_BRIGHTNESS, PROP_MESH_BRIGHTNESS)
PROP_COLOR_TEMP_CANDIDATES = (PROP_COLOR_TEMP, PROP_MESH_COLOR_TEMP)

# BT Mesh bulbs do not share the Wi-Fi colour identifier: Alibaba's mesh model
# mirrors the Bluetooth SIG Light HSL model, so the identifier and its ranges
# vary per product. The colour property is detected at runtime from the TSL
# model (see color_model.py) instead of being hard-coded here.

# Kelvin <-> Aigostar percentage conversion
KELVIN_WARM = 2700   # ColorTemperature = 0
KELVIN_COOL = 6500   # ColorTemperature = 100

# HA brightness 1-255 <-> Aigostar 1-100
HA_BRIGHT_MAX   = 255
AIGO_BRIGHT_MIN = 1
AIGO_BRIGHT_MAX = 100

SCAN_INTERVAL_SECONDS = 30
