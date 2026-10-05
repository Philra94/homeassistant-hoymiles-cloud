"""HA-free regression tests for late entity discovery."""

from types import SimpleNamespace

from tests.module_loader import load_integration_module


def test_register_discovery_adds_late_entities_once_and_unloads() -> None:
    discovery = load_integration_module("discovery")
    listeners = []
    unloads = []
    added = []
    entities = [SimpleNamespace(unique_id="station_pv1")]
    coordinator = SimpleNamespace(async_add_listener=lambda callback: listeners.append(callback) or listeners.clear)
    entry = SimpleNamespace(async_on_unload=unloads.append)

    discovery.register_discovery(coordinator, entry, added.append, lambda: entities)
    assert [[item.unique_id for item in batch] for batch in added] == [["station_pv1"]]
    entities.append(SimpleNamespace(unique_id="station_pv2"))
    listeners[0]()
    listeners[0]()
    assert [[item.unique_id for item in batch] for batch in added] == [["station_pv1"], ["station_pv2"]]
    unloads[0]()
    assert listeners == []


def test_register_discovery_deduplicates_batch_and_retries_failed_add() -> None:
    discovery = load_integration_module("discovery")
    listeners = []
    calls = []
    entities = [SimpleNamespace(unique_id="initial")]
    coordinator = SimpleNamespace(async_add_listener=lambda callback: listeners.append(callback) or (lambda: None))
    entry = SimpleNamespace(async_on_unload=lambda callback: None)

    def add(batch):
        calls.append([entity.unique_id for entity in batch])
        if len(calls) == 2:
            raise RuntimeError("setup failed")

    discovery.register_discovery(coordinator, entry, add, lambda: entities)
    entities.extend([SimpleNamespace(unique_id="same"), SimpleNamespace(unique_id="same")])
    try:
        listeners[0]()
    except RuntimeError:
        pass
    else:
        raise AssertionError("first late setup should fail")
    listeners[0]()
    assert calls == [["initial"], ["same"], ["same"]]


def test_parent_resolution_is_account_scoped_and_does_not_mutate_info(monkeypatch):
    discovery = load_integration_module("discovery")
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id="parent-" + kwargs["config_entry_id"])
    monkeypatch.setattr(discovery, "dr", SimpleNamespace(
        async_get_device_id_by_identifier=object(),
        async_get=lambda hass: SimpleNamespace(async_get_or_create=create)))
    source = {"identifiers": {("hoymiles_cloud", "battery-test")},
              "via_device": ("hoymiles_cloud", "station-test")}
    for account in ("account-a", "account-b"):
        entity = SimpleNamespace(_attr_device_info=source)
        discovery.resolve_via_device(SimpleNamespace(hass=object()), SimpleNamespace(entry_id=account), entity)
        assert entity._attr_device_info["via_device_id"] == "parent-" + account
        assert "via_device" not in entity._attr_device_info
    assert "via_device" in source
    assert [call["config_entry_id"] for call in calls] == ["account-a", "account-b"]


def test_legacy_registry_retains_compatible_parent_field(monkeypatch):
    discovery = load_integration_module("discovery")
    monkeypatch.setattr(discovery, "dr", SimpleNamespace())
    entity = SimpleNamespace(_attr_device_info={"via_device": ("hoymiles_cloud", "station-test")})
    discovery.resolve_via_device(None, None, entity)
    assert entity._attr_device_info == {"via_device": ("hoymiles_cloud", "station-test")}


def test_parent_resolution_omits_self_reference(monkeypatch):
    discovery = load_integration_module("discovery")
    monkeypatch.setattr(discovery, "dr", SimpleNamespace(async_get_device_id_by_identifier=object()))
    identifier = ("hoymiles_cloud", "station-test")
    entity = SimpleNamespace(_attr_device_info={"identifiers": {identifier}, "via_device": identifier})
    discovery.resolve_via_device(None, None, entity)
    assert entity._attr_device_info == {"identifiers": {identifier}}
