"""Constants for the radoff integration."""

from datetime import timedelta

DOMAIN = "radoff"
CONF_POOL_ID = "pool_id"
CONF_POOL_REGION = "pool_region"
DEFAULT_SCAN_INTERVAL = 60
# Sensor values are reported as unavailable when the cloud has not received
# a payload from the device for longer than this.
STALE_DATA_TIMEOUT = timedelta(minutes=10)
MIN_SCAN_INTERVAL = 10
CONF_INDEX = "generate_index"

# AWS Cognito defaults for Radoff API
DEFAULT_POOL_ID = "eu-west-1_zD4CSIZ6i"
DEFAULT_POOL_REGION = "eu-west-1"
DEFAULT_CLIENT_ID = "61ckd0c4qoq0ov7mmphrj7kstj"
