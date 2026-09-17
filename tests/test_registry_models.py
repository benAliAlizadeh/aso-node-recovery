from sqlalchemy import UniqueConstraint, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.database import metadata
from app.models import Node, NodeState, Provider, ProviderType, SecretReferenceBackend


EXPECTED_TABLES = {
    "providers",
    "nodes",
    "node_credentials",
    "node_checks",
    "vps_instances",
    "replacement_jobs",
    "deployments",
    "events",
    "settings",
}


def test_registry_metadata_contains_phase2_tables() -> None:
    assert set(metadata.tables) == EXPECTED_TABLES


def test_all_tables_compile_for_postgresql() -> None:
    dialect = postgresql.dialect()
    for table in metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert f"CREATE TABLE {table.name}" in ddl


def test_node_master_mapping_is_explicit_and_unique() -> None:
    table = inspect(Node).local_table
    master_node_id = table.c.master_node_id
    assert master_node_id.nullable is False
    assert master_node_id.unique is True


def test_node_monitoring_lease_is_persisted_for_duplicate_prevention() -> None:
    table = inspect(Node).local_table
    assert "monitoring_lease_token" in table.c
    assert "monitoring_lease_until" in table.c


def test_only_one_active_replacement_slot_per_node_is_constrained() -> None:
    table = metadata.tables["replacement_jobs"]
    constraints = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    constraint = constraints["one_active_replacement_per_node"]
    assert [column.name for column in constraint.columns] == ["node_id", "active_slot"]


def test_node_state_is_persisted_under_state_column() -> None:
    table = inspect(Node).local_table
    assert "state" in table.c
    assert "_state" not in table.c
    assert set(item.value for item in NodeState) == {
        "unknown",
        "healthy",
        "degraded",
        "failed",
        "replacing",
        "deploying",
        "verifying",
        "disabled",
    }


def test_provider_supports_initial_provider_types_without_storing_raw_api_token() -> None:
    table = inspect(Provider).local_table
    assert set(item.value for item in ProviderType) == {"hetzner", "linode"}
    assert "credential_ref" in table.c
    assert "api_token" not in table.c
    assert "password" not in table.c


def test_node_credentials_store_secret_references_not_secret_material() -> None:
    table = metadata.tables["node_credentials"]
    column_names = set(table.c.keys())
    assert "ssh_secret_ref" in column_names
    assert "panel_password_ref" in column_names
    assert "api_token_ref" in column_names
    assert "ssh_password" not in column_names
    assert "private_key" not in column_names
    assert "api_token" not in column_names
    assert set(item.value for item in SecretReferenceBackend) == {
        "environment",
        "file",
        "external",
        "database_encrypted",
    }
