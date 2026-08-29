"""
Govee Cloud (Platform) API control - for devices that don't support
the LAN API: Smart Plug Pro (H5086), TV Backlight 3 Lite (H6099/H6097).

Requires internet access and an API key from the Govee Home app:
Profile -> About Us -> Apply for API Key

Rate limits: ~100 requests/min and ~10,000/day account-wide, so don't
poll aggressively - this is fine for occasional on/off/brightness taps
from a touchscreen.
"""
import requests

API_KEY = "YOUR_API_KEY_HERE"
BASE_URL = "https://openapi.api.govee.com/router/api/v1"

HEADERS = {
    "Govee-API-Key": API_KEY,
    "Content-Type": "application/json",
}


def list_devices():
    resp = requests.get(f"{BASE_URL}/user/devices", headers=HEADERS, timeout=5)
    resp.raise_for_status()
    return resp.json()


def _control(device, sku, capability_type, instance, value):
    payload = {
        "requestId": "uuid-not-critical-for-single-user",
        "payload": {
            "sku": sku,
            "device": device,
            "capability": {
                "type": capability_type,
                "instance": instance,
                "value": value,
            },
        },
    }
    resp = requests.post(f"{BASE_URL}/device/control", headers=HEADERS, json=payload, timeout=5)
    resp.raise_for_status()
    return resp.json()


def turn_on(device, sku):
    return _control(device, sku, "devices.capabilities.on_off", "powerSwitch", 1)


def turn_off(device, sku):
    return _control(device, sku, "devices.capabilities.on_off", "powerSwitch", 0)


def set_brightness(device, sku, pct):
    """pct: 0-100. Applies to the TV backlight; the plug has no brightness."""
    return _control(device, sku, "devices.capabilities.range", "brightness", max(0, min(100, pct)))


if __name__ == "__main__":
    devices = list_devices()
    for d in devices.get("data", []):
        print(f"{d.get('sku')}: {d.get('deviceName')} ({d.get('device')})")
