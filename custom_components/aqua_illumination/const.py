"""Constants for the Aqua Illumination integration."""
DOMAIN = "aqua_illumination"

CONF_HOST = "host"
CONF_NAME = "name"
CONF_POLL_INTERVAL = "poll_interval"
CONF_AUTO_CLOCK = "auto_clock"

DEFAULT_POLL_INTERVAL = 30  # seconds
DEFAULT_AUTO_CLOCK = True
SCHEDULE_REFRESH_EVERY = 10  # polls between full schedule re-reads
CLOCK_DRIFT_SECONDS = 120    # re-sync the light's clock past this drift

CHANNEL_NAMES = {
    "deep_red": "Deep Red",
    "uv": "UV",
    "deep_blue": "Deep Blue",
    "violet": "Violet",
    "cool_white": "Cool White",
    "warm_white": "Warm White",
    "neutral_white": "Neutral White",
    "green": "Green",
    "blue": "Blue",
    "royal": "Royal",
    "red": "Red",
    "far_red": "Far Red",
}

SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_SYNC_CLOCK = "sync_clock"
SERVICE_SET_NIGHT_LIGHT = "set_night_light"


def channel_label(key: str) -> str:
    return CHANNEL_NAMES.get(key, key.replace("_", " ").title())
