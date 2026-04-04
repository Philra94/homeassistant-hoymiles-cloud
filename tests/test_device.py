"""Tests for device helpers."""

from tests.module_loader import load_integration_module

device_module = load_integration_module("device")


def test_build_station_device_info_uses_energy_storage_model() -> None:
    """Energy-storage stations should surface a clearer top-level device model."""
    info = device_module.build_station_device_info(
        "123",
        "Roof",
        {"classify": 4, "name": "Roof Station"},
    )

    assert info["name"] == "Roof Station"
    assert info["model"] == "Energy Storage Plant"
    assert ("hoymiles_cloud", "123") in info["identifiers"]


def test_build_inverter_device_info_links_back_to_station() -> None:
    """Child devices should use via_device to connect to the station device."""
    info = device_module.build_inverter_device_info(
        "123",
        "Roof",
        {"sn": "INV-1", "model_no": "HYS-3.6", "soft_ver": "1.2.3", "hard_ver": "A"},
    )

    assert info["via_device"] == ("hoymiles_cloud", "123")
    assert ("hoymiles_cloud", "inverter_INV-1") in info["identifiers"]
    assert info["sw_version"] == "1.2.3"
