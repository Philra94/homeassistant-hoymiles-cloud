"""Tests for entry-scoped persistence migration."""

from tests.module_loader import load_integration_module


storage = load_integration_module("storage")


def test_migration_copies_only_owned_stations_without_aliasing():
    legacy = {"stations": {
        "owned": {"schedule_editor": {"modes": {"2": {"draft": [1]}}}},
        "other": {"schedule_editor": {"modes": {"8": {"draft": [2]}}}},
    }}
    migrated = storage.migrate_legacy_stations(legacy, {"owned"})
    assert set(migrated["stations"]) == {"owned"}
    migrated["stations"]["owned"]["schedule_editor"]["modes"]["2"]["draft"].append(3)
    assert legacy["stations"]["owned"]["schedule_editor"]["modes"]["2"]["draft"] == [1]
    assert "other" in legacy["stations"]


def test_entry_keys_are_distinct():
    assert storage.entry_storage_key("hoymiles_cloud_data", "one") != storage.entry_storage_key(
        "hoymiles_cloud_data", "two"
    )
