"""
Unified device manager for the touchscreen controller.

Presents one consistent interface to the UI regardless of whether a
device is controlled over LAN (bulb) or cloud (plug, TV backlight).
Runs a background thread that:
  - polls each device's status on its own interval
  - detects devices going offline (e.g. bulb cut at the wall switch)
    and coming back online, without the UI ever blocking on network I/O
  - drains a command queue so on/off/brightness taps also never block
    the UI thread (matters most for cloud calls, which can take ~1-2s)

Set MOCK_MODE = True to develop/test the whole UI without any real
hardware - mock devices behave like real ones, including going offline
and reconnecting, so you can build and test the wall-switch handling
before your hardware arrives.
"""
import queue
import random
import threading
import time

import govee_lan
import govee_cloud

MOCK_MODE = True  # flip to False once you have real hardware configured

# Consecutive missed polls before a device is marked offline. Multiple
# misses avoid flapping the UI on a single dropped packet.
OFFLINE_AFTER_MISSES = 3

LAN_POLL_INTERVAL = 5.0    # seconds - cheap, no rate limit, poll often
CLOUD_POLL_INTERVAL = 30.0  # seconds - respect Govee's cloud rate limits


class Device:
    """Static config for one physical device."""

    def __init__(self, id, name, kind, **kwargs):
        self.id = id                # stable key, e.g. "bedroom_bulb"
        self.name = name            # display name for the UI
        self.kind = kind            # "lan" or "cloud"
        self.ip = kwargs.get("ip")               # for kind="lan"
        self.sku = kwargs.get("sku")             # for kind="cloud"
        self.device_id = kwargs.get("device_id")  # for kind="cloud" (Govee's MAC-style id)
        self.supports_brightness = kwargs.get("supports_brightness", True)
        self.supports_color = kwargs.get("supports_color", True)


class DeviceState:
    """Latest known state for one device. Read freely from the UI thread."""

    def __init__(self):
        self.online = False
        self.on = False
        self.brightness = 100
        self.color = (255, 255, 255)
        self.last_updated = 0.0
        self.consecutive_misses = 0


class DeviceManager:
    def __init__(self, devices):
        self.devices = {d.id: d for d in devices}
        self.state = {d.id: DeviceState() for d in devices}
        self._lock = threading.Lock()
        self._commands = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    # --- UI-facing read API -------------------------------------------------

    def get_state(self, device_id):
        """Returns (online, on, brightness, color) for one device."""
        with self._lock:
            s = self.state[device_id]
            return (s.online, s.on, s.brightness, s.color)

    def snapshot(self):
        """Returns {device_id: (online, on, brightness, color)} for all devices."""
        with self._lock:
            return {
                did: (s.online, s.on, s.brightness, s.color)
                for did, s in self.state.items()
            }

    # --- UI-facing command API (non-blocking) --------------------------------

    def turn_on(self, device_id):
        self._commands.put((device_id, "turn_on", {}))

    def turn_off(self, device_id):
        self._commands.put((device_id, "turn_off", {}))

    def set_brightness(self, device_id, pct):
        self._commands.put((device_id, "set_brightness", {"pct": pct}))

    # --- background thread ---------------------------------------------------

    def _run(self):
        last_poll = {did: 0.0 for did in self.devices}
        while not self._stop.is_set():
            now = time.time()

            # Drain any pending commands first so taps feel immediate.
            while True:
                try:
                    device_id, action, kwargs = self._commands.get_nowait()
                except queue.Empty:
                    break
                self._execute_command(device_id, action, kwargs)

            # Poll devices whose interval has elapsed.
            for device_id, device in self.devices.items():
                interval = LAN_POLL_INTERVAL if device.kind == "lan" else CLOUD_POLL_INTERVAL
                if now - last_poll[device_id] >= interval:
                    last_poll[device_id] = now
                    self._poll_device(device)

            time.sleep(0.2)

    def _execute_command(self, device_id, action, kwargs):
        device = self.devices[device_id]
        try:
            if MOCK_MODE:
                self._mock_execute(device_id, action, kwargs)
                return

            if device.kind == "lan":
                if action == "turn_on":
                    govee_lan.turn_on(device.ip)
                elif action == "turn_off":
                    govee_lan.turn_off(device.ip)
                elif action == "set_brightness":
                    govee_lan.set_brightness(device.ip, kwargs["pct"])
            else:  # cloud
                if action == "turn_on":
                    govee_cloud.turn_on(device.device_id, device.sku)
                elif action == "turn_off":
                    govee_cloud.turn_off(device.device_id, device.sku)
                elif action == "set_brightness":
                    govee_cloud.set_brightness(device.device_id, device.sku, kwargs["pct"])
        except Exception as exc:
            # Network hiccup on a command - not fatal, next poll will
            # reconcile actual state. Log it however you prefer.
            print(f"[{device_id}] command {action} failed: {exc}")

    def _poll_device(self, device):
        try:
            if MOCK_MODE:
                status = self._mock_poll(device.id)
            elif device.kind == "lan":
                status = govee_lan.query_status(device.ip)
                if status:
                    status = {
                        "on": bool(status.get("onOff")),
                        "brightness": status.get("brightness", 0),
                        "color": tuple(status.get("color", {}).values()) or (255, 255, 255),
                    }
            else:
                status = govee_cloud.get_state(device.device_id, device.sku)

            with self._lock:
                s = self.state[device.id]
                if status is None:
                    s.consecutive_misses += 1
                    if s.consecutive_misses >= OFFLINE_AFTER_MISSES:
                        s.online = False
                else:
                    s.consecutive_misses = 0
                    s.online = True
                    s.on = status.get("on", s.on)
                    s.brightness = status.get("brightness", s.brightness)
                    s.color = status.get("color", s.color)
                    s.last_updated = time.time()
        except Exception as exc:
            print(f"[{device.id}] poll failed: {exc}")

    # --- mock backend for development without hardware ------------------------

    def _mock_execute(self, device_id, action, kwargs):
        with self._lock:
            s = self.state[device_id]
            if action == "turn_on":
                s.on = True
            elif action == "turn_off":
                s.on = False
            elif action == "set_brightness":
                s.brightness = kwargs["pct"]
            s.online = True
            s.consecutive_misses = 0

    def _mock_poll(self, device_id):
        # Occasionally simulate the wall-switch bulb going offline/online
        # so you can build and test that behavior before you have hardware.
        if random.random() < 0.02:
            return None
        with self._lock:
            s = self.state[device_id]
            return {"on": s.on, "brightness": s.brightness, "color": s.color}
