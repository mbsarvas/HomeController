"""
Minimal Govee LAN API client - discovery + control over UDP.
No internet/cloud required. Tested protocol for WiFi-enabled bulbs
like the H1401 with "LAN Control" enabled in the Govee Home app.
"""
import json
import socket
import time

MULTICAST_GROUP = "239.255.255.250"
DISCOVER_PORT = 4001     # send scan requests here
LISTEN_PORT = 4002       # devices reply here
CONTROL_PORT = 4003      # send commands here


def discover(timeout=3.0):
    """Broadcast a scan request, collect replies. Returns {ip: device_info}."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", LISTEN_PORT))
    sock.settimeout(timeout)

    msg = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}})
    sock.sendto(msg.encode(), (MULTICAST_GROUP, DISCOVER_PORT))

    devices = {}
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, addr = sock.recvfrom(4096)
            reply = json.loads(data)
            info = reply.get("msg", {}).get("data", {})
            if info.get("ip"):
                devices[info["ip"]] = info
        except socket.timeout:
            break
    sock.close()
    return devices


def query_status(ip, timeout=2.0):
    """
    Send a devStatus query directly to a known bulb IP and wait for its reply.
    Returns a dict like {"onOff": 1, "brightness": 80, "color": {...}, "colorTemInKelvin": 0}
    or None if the device didn't respond within timeout (e.g. powered off at
    the wall switch).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 0))  # any free local port for the reply
    sock.settimeout(timeout)

    msg = json.dumps({"msg": {"cmd": "devStatus", "data": {}}})
    sock.sendto(msg.encode(), (ip, CONTROL_PORT))

    try:
        data, addr = sock.recvfrom(4096)
        reply = json.loads(data)
        return reply.get("msg", {}).get("data")
    except (socket.timeout, json.JSONDecodeError):
        return None
    finally:
        sock.close()


def _send_command(ip, cmd, data):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = json.dumps({"msg": {"cmd": cmd, "data": data}})
    sock.sendto(payload.encode(), (ip, CONTROL_PORT))
    sock.close()


def turn_on(ip):
    _send_command(ip, "turn", {"value": 1})


def turn_off(ip):
    _send_command(ip, "turn", {"value": 0})


def set_brightness(ip, pct):
    """pct: 0-100"""
    _send_command(ip, "brightness", {"value": max(0, min(100, pct))})


def set_color(ip, r, g, b):
    _send_command(ip, "colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0})


def set_color_temp(ip, kelvin):
    _send_command(ip, "colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": kelvin})


# --- Undocumented but widely-used: raw BLE packet passthrough over LAN ---
# Lets you replay "scene codes" (raw bulb command bytes) that aren't part
# of the official LAN command set. See community writeups (egold555/
# Govee-Reverse-Engineering, wez/govee2mqtt, homebridge-govee wiki) for
# how to capture the byte sequence for a specific scene from your own
# account — this is a one-time setup step, done once per scene.
import base64


def _checksum(packet_bytes):
    x = 0
    for b in packet_bytes:
        x ^= b
    return x


def build_scene_packet(payload_bytes):
    """
    payload_bytes: the scene-specific command bytes (e.g. [0x05, 0x04, 0xcf, 0x27]
    for a particular built-in scene, captured per the methods above).
    Returns the base64 string ready to send via ptReal.
    """
    packet = bytearray(20)
    packet[0] = 0x33  # single-packet command header used for scene/mode commands
    for i, b in enumerate(payload_bytes):
        packet[1 + i] = b
    packet[19] = _checksum(packet[:19])
    return base64.b64encode(bytes(packet)).decode()


def set_scene(ip, payload_bytes):
    """Send a captured scene code to a device via the undocumented ptReal command."""
    b64_packet = build_scene_packet(payload_bytes)
    _send_command(ip, "ptReal", {"command": [b64_packet]})


# Example: once you've captured your own scene codes, store them like this
# and call set_scene(ip, KNOWN_SCENES["sunset"])
KNOWN_SCENES = {
    # "sunset": [0x05, 0x04, 0xcf, 0x27],  # <- replace with your captured bytes
}


if __name__ == "__main__":
    print("Scanning for Govee LAN devices...")
    found = discover()
    for ip, info in found.items():
        print(f"  {ip}: {info.get('sku')} ({info.get('device')})")

    # Example: turn the first bulb on and set it to warm white
    if found:
        first_ip = next(iter(found))
        turn_on(first_ip)
        set_brightness(first_ip, 80)
        set_color(first_ip, 255, 180, 100)
