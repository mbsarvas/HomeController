"""
Touchscreen UI for controlling the Govee devices.

Reads live state from DeviceManager's background poller (never blocks
on network I/O) and sends taps through as non-blocking commands.
"""
from kivy.config import Config
# Rotate the whole app 90 degrees clockwise to match the Touch Display 2's
# landscape mounting. This must be set before any other kivy import that
# might trigger window creation. If the screen comes out upside-down or
# mirrored, change this to '270' instead.
Config.set('graphics', 'rotation', '90')

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.slider import Slider

from device_manager import Device, DeviceManager

# Simple color palette shown as tap-to-set swatches on any device with
# supports_color=True. Each entry is (name, (r, g, b)) - name is unused in
# the UI itself (buttons are just solid color blocks) but useful if you
# want to add labels or tooltips later.
COLOR_PRESETS = [
    ("Warm White", (255, 180, 100)),
    ("Cool White", (255, 255, 255)),
    ("Red", (255, 0, 0)),
    ("Orange", (255, 120, 0)),
    ("Green", (0, 200, 0)),
    ("Blue", (0, 90, 255)),
    ("Purple", (150, 0, 220)),
]

# --- Define your devices here. Fill in real ip / device_id / sku once
# hardware is set up; in MOCK_MODE these values are ignored. ---------------
DEVICES = [
    Device("bulb_1", "Office Light", "lan", ip="192.168.68.69"),
    # Device("bulb_2", "Den Light", "lan", ip="192.168.1.51"),
    # Device(
    #     "tv_backlight", "TV Backlight", "cloud",
    #     device_id="AA:BB:CC:DD:EE:FF:00:11", sku="H6099",
    # ),
    # Device(
    #     "plug", "Smart Plug", "cloud",
    #     device_id="11:22:33:44:55:66:77:88", sku="H5086",
    #     supports_brightness=False, supports_color=False,
    # ),
]


class DeviceTile(BoxLayout):
    def __init__(self, device, manager, **kwargs):
        super().__init__(orientation="vertical", padding=10, spacing=6, **kwargs)
        self.device = device
        self.manager = manager

        self.name_label = Label(text=device.name, font_size=20, size_hint_y=0.25)
        self.status_label = Label(text="checking...", font_size=14, size_hint_y=0.15)

        self.toggle_btn = Button(text="—", font_size=18, size_hint_y=0.3)
        self.toggle_btn.bind(on_release=self._on_toggle)

        self.add_widget(self.name_label)
        self.add_widget(self.status_label)
        self.add_widget(self.toggle_btn)

        if device.supports_brightness:
            self.brightness_slider = Slider(min=1, max=100, value=100, size_hint_y=0.3)
            self.brightness_slider.bind(value=self._on_brightness_change)
            self.brightness_slider.bind(on_touch_down=self._on_slider_touch_down)
            self.brightness_slider.bind(on_touch_up=self._on_slider_touch_up)
            self._slider_dragging = False
            self.add_widget(self.brightness_slider)
        else:
            self.brightness_slider = None
            self._slider_dragging = False

        if device.supports_color:
            color_row = BoxLayout(orientation="horizontal", size_hint_y=0.3, spacing=6)
            for name, (r, g, b) in COLOR_PRESETS:
                swatch = Button(background_normal="", background_color=(r / 255, g / 255, b / 255, 1))
                swatch.bind(on_release=lambda _btn, rgb=(r, g, b): self._on_color_tap(rgb))
                color_row.add_widget(swatch)
            self.add_widget(color_row)

    def _on_toggle(self, *_args):
        online, on, brightness, color = self.manager.get_state(self.device.id)
        if not online:
            return  # ignore taps on offline devices
        if on:
            self.manager.turn_off(self.device.id)
        else:
            self.manager.turn_on(self.device.id)

    def _on_brightness_change(self, _slider, value):
        self.manager.set_brightness(self.device.id, int(value))

    def _on_color_tap(self, rgb):
        r, g, b = rgb
        self.manager.set_color(self.device.id, r, g, b)

    def _on_slider_touch_down(self, slider, touch):
        if slider.collide_point(*touch.pos):
            self._slider_dragging = True
        return False  # don't consume the event, let the slider still handle it

    def _on_slider_touch_up(self, _slider, _touch):
        self._slider_dragging = False
        return False

    def refresh(self):
        online, on, brightness, color = self.manager.get_state(self.device.id)

        if not online:
            self.status_label.text = "OFFLINE"
            self.toggle_btn.text = "—"
            self.toggle_btn.disabled = True
            self.opacity = 0.4
            return

        self.opacity = 1.0
        self.toggle_btn.disabled = False
        self.status_label.text = "ON" if on else "OFF"
        self.toggle_btn.text = "Turn Off" if on else "Turn On"

        if self.brightness_slider and not self._slider_dragging:
            # Avoid fighting the user's finger mid-drag
            self.brightness_slider.value = brightness


class ControllerRoot(GridLayout):
    def __init__(self, manager, **kwargs):
        super().__init__(cols=2, padding=20, spacing=20, **kwargs)
        self.manager = manager
        self.tiles = []
        for device in manager.devices.values():
            tile = DeviceTile(device, manager)
            self.tiles.append(tile)
            self.add_widget(tile)

    def refresh(self, *_args):
        for tile in self.tiles:
            tile.refresh()


class GoveeControllerApp(App):
    def build(self):
        self.manager = DeviceManager(DEVICES)
        self.manager.start()

        root = ControllerRoot(self.manager)
        Clock.schedule_interval(root.refresh, 0.5)
        return root

    def on_stop(self):
        self.manager.stop()


if __name__ == "__main__":
    GoveeControllerApp().run()
