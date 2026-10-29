"""Check upstream light behavior with both Wi-Fi and BLE gateway clients."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from aidot.device_client import DeviceClient
from homeassistant.components.light import ColorMode, LightEntityFeature
import pytest

from custom_components.aidot.ble_gateway_client import BleGatewayDeviceClient
from custom_components.aidot.light import AidotLight


def _make_client(kind: str):
    device = {
        "id": "light1",
        "modelId": "LK.A000181",
        "mac": "AA:BB:CC:DD:EE:FF",
        "name": "Spot 1",
        "product": {"serviceModules": [{"identity": "control.light.rgbw"}]},
        "properties": {},
    }
    if kind == "ble":
        return BleGatewayDeviceClient(device, {"id": "hub1"}, "user1")
    device["presets"] = {"Party": object()}
    return DeviceClient(device, {"id": "user1"}, None)


def _make_light(client):
    light = AidotLight(
        SimpleNamespace(
            device_client=client,
            data=client.status,
            last_update_success=True,
        )
    )
    light.async_write_ha_state = Mock()
    return light


def test_ble_light_loads_without_advertising_effects():
    """The new upstream effect attributes must not prevent BLE entity setup."""
    light = _make_light(_make_client("ble"))

    assert light.unique_id == "light1"
    assert light.supported_color_modes == {ColorMode.RGBW, ColorMode.COLOR_TEMP}
    assert not light.supported_features & LightEntityFeature.EFFECT
    assert light.effect is None


async def test_wifi_effects_remain_available():
    """Upstream presets are advertised and sent through the Wi-Fi client."""
    client = _make_client("wifi")
    client.async_set_effect = AsyncMock()
    light = _make_light(client)

    assert light.supported_features & LightEntityFeature.EFFECT
    assert light.effect_list == ["Party"]

    await light.async_turn_on(effect="Party")

    client.async_set_effect.assert_awaited_once_with("Party")
    assert light.effect == "Party"
    assert light.is_on


@pytest.mark.parametrize("kind", ["ble", "wifi"])
@pytest.mark.parametrize(
    ("kwargs", "method", "value", "color_mode"),
    [
        ({"color_temp_kelvin": 4000}, "async_set_cct", 4000, ColorMode.COLOR_TEMP),
        (
            {"rgbw_color": (25, 50, 75, 0)},
            "async_set_rgbw",
            (25, 50, 75, 0),
            ColorMode.RGBW,
        ),
    ],
)
async def test_scene_applies_brightness_and_color(kind, kwargs, method, value, color_mode):
    """A scene containing brightness must also apply its requested color."""
    client = _make_client(kind)
    client.async_set_brightness = AsyncMock()
    setattr(client, method, AsyncMock())
    light = _make_light(client)

    await light.async_turn_on(brightness=128, **kwargs)

    client.async_set_brightness.assert_awaited_once_with(128)
    getattr(client, method).assert_awaited_once_with(value)
    assert light.brightness == 128
    assert light.color_mode == color_mode
    assert light.is_on
    light.async_write_ha_state.assert_called_once()
