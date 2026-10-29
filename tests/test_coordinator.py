"""Regression checks for merging upstream discovery with BLE gateway support."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

from aidot.exceptions import AidotAuthFailed, AidotUserOrPassIncorrect
from homeassistant.exceptions import ConfigEntryError
import pytest

from custom_components.aidot import coordinator as coord
from custom_components.aidot.ble_gateway_client import BleGatewayDeviceClient


@pytest.fixture
def manager(monkeypatch):
    """Use the real manager and library without network discovery or sessions."""
    monkeypatch.setattr(coord.AidotClient, "setup_discover", Mock())
    monkeypatch.setattr(coord, "async_get_clientsession", lambda hass: None)
    token = {
        "id": "user1",
        "username": "test@example.com",
        "password": "test-password",
        "region": "us",
        "country": "United States",
        "access_token": "test-token",
    }

    def make(data):
        entry = MagicMock(data=data, entry_id="entry1")
        return coord.AidotDeviceManagerCoordinator(MagicMock(), entry)

    return make, token


@pytest.mark.parametrize("nested", [False, True])
async def test_discovers_wifi_and_ble_lights(manager, monkeypatch, nested):
    """Both config formats must retain BLE lights alongside Wi-Fi lights."""
    make, token = manager
    coordinator = make({"login_info": token} if nested else token)
    hub = {"id": "hub1", "type": "BleMesh_Hub"}
    wifi = {"id": "wifi1", "type": "light", "aesKey": ["testkey"]}
    ble = {
        "id": "ble1",
        "type": "light",
        "aesKey": [None],
        "directGateway": "hub1",
        "bleMeshDeviceKey": "meshkey",
    }
    orphan = {**ble, "id": "orphan", "directGateway": "missing-hub"}
    coordinator.client.async_get_all_device = AsyncMock(
        return_value={"device_list": [hub, wifi, ble, orphan]}
    )
    wifi_client = SimpleNamespace(status=object())
    coordinator.client.get_device_client = Mock(return_value=wifi_client)

    async def first_refresh(device_coordinator):
        await device_coordinator._async_setup()
        device_coordinator.data = await device_coordinator._async_update_data()

    monkeypatch.setattr(
        coord.AidotDeviceUpdateCoordinator,
        "async_config_entry_first_refresh",
        first_refresh,
    )

    await coordinator._async_update_data()

    assert coordinator.client.login_info == token
    assert set(coordinator.device_coordinators) == {"wifi1", "ble1"}
    coordinator.client.get_device_client.assert_called_once_with(wifi)
    ble_client = coordinator.device_coordinators["ble1"].device_client
    assert isinstance(ble_client, BleGatewayDeviceClient)
    assert ble_client._user_id == "user1"
    assert ble_client.on_status_update is not None


@pytest.mark.parametrize(
    ("client_method", "manager_method", "error"),
    [
        ("async_post_login", "_async_setup", AidotUserOrPassIncorrect),
        ("async_get_all_device", "_async_update_data", AidotAuthFailed),
    ],
)
async def test_authentication_errors_follow_upstream(
    manager, client_method, manager_method, error
):
    """The merge must retain upstream's ConfigEntryError handling."""
    make, token = manager
    coordinator = make(
        {key: value for key, value in token.items() if key != "access_token"}
    )
    setattr(coordinator.client, client_method, AsyncMock(side_effect=error))

    with pytest.raises(ConfigEntryError) as raised:
        await getattr(coordinator, manager_method)()

    assert isinstance(raised.value.__cause__, error)
