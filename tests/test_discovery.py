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
