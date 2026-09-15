from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def build_client(tmp_path: Path, api_key: str | None = None) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                allowed_origins=("http://localhost:5173",),
                database_path=tmp_path / "test.db",
                api_key=api_key,
            )
        )
    )


def test_health_returns_service_metadata_and_request_id(tmp_path: Path) -> None:
    response = build_client(tmp_path).get("/health", headers={"X-Request-ID": "frontend-request-7"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "cascading-failure-api"
    assert response.headers["X-Request-ID"] == "frontend-request-7"


def test_meta_lists_only_currently_implemented_routes(tmp_path: Path) -> None:
    response = build_client(tmp_path).get("/api/v1/meta")

    assert response.status_code == 200
    body = response.json()
    assert body["implementation_phase"] == 5
    assert "GET/POST /api/v1/networks" in body["supported_routes"]


def test_missing_network_uses_the_documented_error_envelope(tmp_path: Path) -> None:
    response = build_client(tmp_path).get(
        "/api/v1/networks/00000000-0000-0000-0000-000000000001",
        headers={"X-Request-ID": "missing-1"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "RESOURCE_NOT_FOUND", "message": "Network not found.", "field": None},
        "request_id": "missing-1",
    }


def test_network_graph_can_be_created_and_read(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    response = client.post(
        "/api/v1/networks",
        json={
            "name": "Central mobility",
            "geographic_scope": "Bengaluru CBD",
            "nodes": [
                {
                    "external_id": "BRG-1",
                    "name": "Kaveri Bridge",
                    "asset_type": "bridge",
                    "capacity": 2200,
                    "baseline_load": 1350,
                },
                {
                    "external_id": "HSP-1",
                    "name": "City Hospital",
                    "asset_type": "hospital",
                    "capacity": 500,
                    "baseline_load": 300,
                },
            ],
            "edges": [
                {
                    "source_external_id": "BRG-1",
                    "target_external_id": "HSP-1",
                    "relation_type": "flow",
                    "capacity": 1800,
                }
            ],
        },
    )

    assert response.status_code == 201
    network = response.json()
    assert len(network["nodes"]) == 2
    assert network["edges"][0]["source_node_id"] != network["edges"][0]["target_node_id"]

    listed = client.get("/api/v1/networks").json()
    assert listed["total"] == 1
    assert listed["items"][0]["node_count"] == 2
    assert listed["items"][0]["edge_count"] == 1


def test_node_edge_mutations_keep_the_graph_consistent(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    network = client.post("/api/v1/networks", json={"name": "Test network"}).json()
    network_id = network["id"]
    node_a = client.post(
        f"/api/v1/networks/{network_id}/nodes",
        json={
            "external_id": "A",
            "name": "Asset A",
            "asset_type": "road_segment",
            "capacity": 100,
            "baseline_load": 50,
        },
    ).json()
    node_b = client.post(
        f"/api/v1/networks/{network_id}/nodes",
        json={
            "external_id": "B",
            "name": "Asset B",
            "asset_type": "hospital",
            "capacity": 80,
            "baseline_load": 30,
        },
    ).json()
    edge = client.post(
        f"/api/v1/networks/{network_id}/edges",
        json={
            "source_node_id": node_a["id"],
            "target_node_id": node_b["id"],
            "relation_type": "dependency",
            "dependency_strength": 0.7,
        },
    )

    assert edge.status_code == 201
    updated = client.patch(
        f"/api/v1/networks/{network_id}/nodes/{node_a['id']}",
        json={"status": "degraded", "baseline_load": 60},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "degraded"

    deleted = client.delete(f"/api/v1/networks/{network_id}/nodes/{node_a['id']}")
    assert deleted.status_code == 204
    graph = client.get(f"/api/v1/networks/{network_id}").json()
    assert len(graph["nodes"]) == 1
    assert graph["edges"] == []


def test_complete_failure_can_trigger_a_cascade_simulation(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    network = client.post(
        "/api/v1/networks",
        json={
            "name": "Two asset network",
            "nodes": [
                {
                    "external_id": "A",
                    "name": "Bridge A",
                    "asset_type": "bridge",
                    "capacity": 100,
                    "baseline_load": 70,
                },
                {
                    "external_id": "B",
                    "name": "Bridge B",
                    "asset_type": "bridge",
                    "capacity": 100,
                    "baseline_load": 80,
                },
            ],
            "edges": [
                {
                    "source_external_id": "A",
                    "target_external_id": "B",
                    "relation_type": "flow",
                }
            ],
        },
    ).json()
    node_a_id = next(node["id"] for node in network["nodes"] if node["external_id"] == "A")
    scenario = client.post(
        "/api/v1/scenarios",
        json={
            "name": "Bridge A closes",
            "network_id": network["id"],
            "failure_events": [
                {
                    "target_kind": "node",
                    "target_id": node_a_id,
                    "mode": "complete_failure",
                    "severity": 1,
                }
            ],
        },
    )
    assert scenario.status_code == 201

    run = client.post(f"/api/v1/scenarios/{scenario.json()['id']}/runs")
    assert run.status_code == 201
    assert run.json()["status"] == "completed"

    result = client.get(f"/api/v1/runs/{run.json()['id']}/result")
    assert result.status_code == 200
    assert len(result.json()["failed_node_ids"]) == 2
    assert result.json()["service_loss_ratio"] == 1
    assert len(result.json()["cascade_steps"]) >= 2


def test_criticality_and_scenario_comparison_rank_planning_choices(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    network = client.post(
        "/api/v1/networks",
        json={
            "name": "Alternative routes",
            "nodes": [
                {
                    "external_id": "A",
                    "name": "Bridge A",
                    "asset_type": "bridge",
                    "capacity": 100,
                    "baseline_load": 70,
                },
                {
                    "external_id": "B",
                    "name": "Bridge B",
                    "asset_type": "bridge",
                    "capacity": 200,
                    "baseline_load": 40,
                },
            ],
            "edges": [
                {
                    "source_external_id": "A",
                    "target_external_id": "B",
                    "relation_type": "flow",
                }
            ],
        },
    ).json()
    node_ids = {node["external_id"]: node["id"] for node in network["nodes"]}

    scenarios = []
    for external_id in ("A", "B"):
        response = client.post(
            "/api/v1/scenarios",
            json={
                "name": f"Close {external_id}",
                "network_id": network["id"],
                "failure_events": [
                    {
                        "target_kind": "node",
                        "target_id": node_ids[external_id],
                        "mode": "complete_failure",
                        "severity": 1,
                    }
                ],
            },
        )
        assert response.status_code == 201
        scenarios.append(response.json())

    criticality = client.get(f"/api/v1/networks/{network['id']}/criticality?metric=failure_impact")
    assert criticality.status_code == 200
    assert criticality.json()["assets"][0]["asset_name"] == "Bridge B"

    comparison = client.post(
        "/api/v1/scenario-comparisons",
        json={"scenario_ids": [scenario["id"] for scenario in scenarios]},
    )
    assert comparison.status_code == 200
    assert comparison.json()["least_impact_scenario_id"] == scenarios[0]["id"]
    assert comparison.json()["scenarios"][0]["rank"] == 1


def test_network_export_import_and_audit_trail(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    created = client.post(
        "/api/v1/networks",
        json={
            "name": "Exportable network",
            "nodes": [
                {
                    "external_id": "PUMP-1",
                    "name": "North Pump",
                    "asset_type": "water_pump",
                    "capacity": 100,
                    "baseline_load": 20,
                }
            ],
        },
    ).json()

    exported = client.get(f"/api/v1/networks/{created['id']}/export")
    assert exported.status_code == 200
    assert exported.json()["format"] == "cascading-failure-network/v1"

    imported = client.post("/api/v1/networks/network-imports", json=exported.json())
    assert imported.status_code == 201
    assert imported.json()["id"] != created["id"]
    assert imported.json()["nodes"][0]["external_id"] == "PUMP-1"

    audit_events = client.get("/api/v1/audit-events").json()
    assert audit_events["total"] >= 2
    assert audit_events["items"][0]["action"].startswith("POST ")


def test_api_key_is_optional_locally_and_enforced_when_configured(tmp_path: Path) -> None:
    client = build_client(tmp_path, api_key="prototype-secret")

    denied = client.get("/api/v1/meta")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "UNAUTHORIZED"

    allowed = client.get("/api/v1/meta", headers={"X-API-Key": "prototype-secret"})
    assert allowed.status_code == 200
