"""SQLite repository; the HTTP layer remains independent of storage details."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.schemas.network import (
    EdgeUpdateRequest,
    InfrastructureEdgeInput,
    InfrastructureNodeInput,
    NetworkCreateRequest,
    NetworkEdgeDraftInput,
    NetworkUpdateRequest,
    NodeUpdateRequest,
)


class ResourceNotFoundError(Exception):
    """The requested resource is absent."""


class ConflictError(Exception):
    """The requested state transition violates a network invariant."""


class NetworkRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS networks (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
                    geographic_scope TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY, network_id TEXT NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
                    external_id TEXT NOT NULL, name TEXT NOT NULL, asset_type TEXT NOT NULL,
                    capacity REAL NOT NULL, baseline_load REAL NOT NULL, latitude REAL, longitude REAL,
                    attributes_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'operational',
                    UNIQUE(network_id, external_id)
                );
                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY, network_id TEXT NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
                    source_node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    target_node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                    relation_type TEXT NOT NULL, capacity REAL, baseline_flow REAL,
                    dependency_strength REAL, attributes_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_nodes_network_id ON nodes(network_id);
                CREATE INDEX IF NOT EXISTS idx_edges_network_id ON edges(network_id);
                """
            )

    def create_network(self, payload: NetworkCreateRequest) -> dict:
        node_ids = self._node_ids_for_create(payload.nodes)
        self._validate_draft_edges(payload.edges, node_ids)
        now, network_id = self._now(), str(uuid4())
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO networks VALUES (?, ?, ?, ?, ?, ?)",
                (network_id, payload.name, payload.description, payload.geographic_scope, now, now),
            )
            for node in payload.nodes:
                self._insert_node(connection, network_id, node_ids[node.external_id], node)
            for edge in payload.edges:
                self._insert_draft_edge(connection, network_id, node_ids, edge)
        return self.get_network(UUID(network_id))

    def list_networks(self, limit: int, offset: int) -> dict:
        with self._connection() as connection:
            total = connection.execute("SELECT COUNT(*) FROM networks").fetchone()[0]
            rows = connection.execute(
                """
                SELECT n.*, COUNT(DISTINCT nd.id) AS node_count, COUNT(DISTINCT e.id) AS edge_count
                FROM networks n
                LEFT JOIN nodes nd ON nd.network_id = n.id
                LEFT JOIN edges e ON e.network_id = n.id
                GROUP BY n.id ORDER BY n.created_at DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    def export_network(self, network_id: UUID) -> dict:
        network = self.get_network(network_id)
        node_external_ids = {node["id"]: node["external_id"] for node in network["nodes"]}
        nodes = [
            {
                key: value
                for key, value in node.items()
                if key not in {"id", "status"}
            }
            for node in network["nodes"]
        ]
        edges = [
            {
                "source_external_id": node_external_ids[edge["source_node_id"]],
                "target_external_id": node_external_ids[edge["target_node_id"]],
                "relation_type": edge["relation_type"],
                "capacity": edge["capacity"],
                "baseline_flow": edge["baseline_flow"],
                "dependency_strength": edge["dependency_strength"],
                "attributes": edge["attributes"],
            }
            for edge in network["edges"]
        ]
        return {
            "format": "cascading-failure-network/v1",
            "exported_at": self._now(),
            "network": {
                "name": network["name"],
                "description": network["description"],
                "geographic_scope": network["geographic_scope"],
                "nodes": nodes,
                "edges": edges,
            },
        }

    def get_network(self, network_id: UUID) -> dict:
        with self._connection() as connection:
            network = connection.execute("SELECT * FROM networks WHERE id = ?", (str(network_id),)).fetchone()
            if network is None:
                raise ResourceNotFoundError("Network not found.")
            node_rows = connection.execute(
                "SELECT * FROM nodes WHERE network_id = ? ORDER BY external_id", (str(network_id),)
            ).fetchall()
            edge_rows = connection.execute(
                "SELECT * FROM edges WHERE network_id = ? ORDER BY id", (str(network_id),)
            ).fetchall()
        result = dict(network)
        result["nodes"] = [self._node_row(row) for row in node_rows]
        result["edges"] = [self._edge_row(row) for row in edge_rows]
        return result

    def update_network(self, network_id: UUID, payload: NetworkUpdateRequest) -> dict:
        self._require_network(network_id)
        values = payload.model_dump(exclude_unset=True)
        values["updated_at"] = self._now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connection() as connection:
            connection.execute(
                f"UPDATE networks SET {assignments} WHERE id = ?", (*values.values(), str(network_id))
            )
        return self.get_network(network_id)

    def delete_network(self, network_id: UUID) -> None:
        with self._connection() as connection:
            deleted = connection.execute("DELETE FROM networks WHERE id = ?", (str(network_id),)).rowcount
        if not deleted:
            raise ResourceNotFoundError("Network not found.")

    def add_node(self, network_id: UUID, payload: InfrastructureNodeInput) -> dict:
        self._require_network(network_id)
        node_id = str(uuid4())
        try:
            with self._connection() as connection:
                self._insert_node(connection, str(network_id), node_id, payload)
                self._touch_network(connection, network_id)
        except sqlite3.IntegrityError as error:
            raise ConflictError("external_id must be unique within a network.") from error
        return self.get_node(network_id, UUID(node_id))

    def get_node(self, network_id: UUID, node_id: UUID) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM nodes WHERE network_id = ? AND id = ?", (str(network_id), str(node_id))
            ).fetchone()
        if row is None:
            raise ResourceNotFoundError("Node not found in this network.")
        return self._node_row(row)

    def update_node(self, network_id: UUID, node_id: UUID, payload: NodeUpdateRequest) -> dict:
        self.get_node(network_id, node_id)
        values = payload.model_dump(exclude_unset=True)
        if "location" in values:
            location = values.pop("location")
            values["latitude"] = location["latitude"] if location else None
            values["longitude"] = location["longitude"] if location else None
        if "attributes" in values:
            values["attributes_json"] = json.dumps(values.pop("attributes"))
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connection() as connection:
            connection.execute(
                f"UPDATE nodes SET {assignments} WHERE id = ?", (*values.values(), str(node_id))
            )
            self._touch_network(connection, network_id)
        return self.get_node(network_id, node_id)

    def delete_node(self, network_id: UUID, node_id: UUID) -> None:
        with self._connection() as connection:
            deleted = connection.execute(
                "DELETE FROM nodes WHERE network_id = ? AND id = ?", (str(network_id), str(node_id))
            ).rowcount
            if deleted:
                self._touch_network(connection, network_id)
        if not deleted:
            raise ResourceNotFoundError("Node not found in this network.")

    def add_edge(self, network_id: UUID, payload: InfrastructureEdgeInput) -> dict:
        self._require_network(network_id)
        self._validate_node_ids(network_id, payload.source_node_id, payload.target_node_id)
        edge_id = str(uuid4())
        with self._connection() as connection:
            self._insert_edge(connection, edge_id, network_id, payload)
            self._touch_network(connection, network_id)
        return self.get_edge(network_id, UUID(edge_id))

    def get_edge(self, network_id: UUID, edge_id: UUID) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM edges WHERE network_id = ? AND id = ?", (str(network_id), str(edge_id))
            ).fetchone()
        if row is None:
            raise ResourceNotFoundError("Edge not found in this network.")
        return self._edge_row(row)

    def update_edge(self, network_id: UUID, edge_id: UUID, payload: EdgeUpdateRequest) -> dict:
        self.get_edge(network_id, edge_id)
        values = payload.model_dump(exclude_unset=True)
        if "attributes" in values:
            values["attributes_json"] = json.dumps(values.pop("attributes"))
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connection() as connection:
            connection.execute(
                f"UPDATE edges SET {assignments} WHERE id = ?", (*values.values(), str(edge_id))
            )
            self._touch_network(connection, network_id)
        return self.get_edge(network_id, edge_id)

    def delete_edge(self, network_id: UUID, edge_id: UUID) -> None:
        with self._connection() as connection:
            deleted = connection.execute(
                "DELETE FROM edges WHERE network_id = ? AND id = ?", (str(network_id), str(edge_id))
            ).rowcount
            if deleted:
                self._touch_network(connection, network_id)
        if not deleted:
            raise ResourceNotFoundError("Edge not found in this network.")

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _node_ids_for_create(nodes: list[InfrastructureNodeInput]) -> dict[str, str]:
        ids = {node.external_id: str(uuid4()) for node in nodes}
        if len(ids) != len(nodes):
            raise ConflictError("Each node external_id must be unique within a network.")
        return ids

    @staticmethod
    def _validate_draft_edges(edges: list[NetworkEdgeDraftInput], node_ids: dict[str, str]) -> None:
        for edge in edges:
            if edge.source_external_id not in node_ids or edge.target_external_id not in node_ids:
                raise ConflictError("Each edge must reference a node external_id in the same request.")

    def _require_network(self, network_id: UUID) -> None:
        with self._connection() as connection:
            found = connection.execute("SELECT 1 FROM networks WHERE id = ?", (str(network_id),)).fetchone()
        if found is None:
            raise ResourceNotFoundError("Network not found.")

    def _validate_node_ids(self, network_id: UUID, *node_ids: UUID) -> None:
        placeholders = ",".join("?" for _ in node_ids)
        with self._connection() as connection:
            count = connection.execute(
                f"SELECT COUNT(*) FROM nodes WHERE network_id = ? AND id IN ({placeholders})",
                (str(network_id), *(str(node_id) for node_id in node_ids)),
            ).fetchone()[0]
        if count != len(set(node_ids)):
            raise ConflictError("Every edge endpoint must be a node in the specified network.")

    @staticmethod
    def _insert_node(
        connection: sqlite3.Connection, network_id: str, node_id: str, payload: InfrastructureNodeInput
    ) -> None:
        location = payload.location
        connection.execute(
            "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'operational')",
            (
                node_id, network_id, payload.external_id, payload.name, payload.asset_type,
                payload.capacity, payload.baseline_load, location.latitude if location else None,
                location.longitude if location else None, json.dumps(payload.attributes),
            ),
        )

    def _insert_draft_edge(
        self, connection: sqlite3.Connection, network_id: str, node_ids: dict[str, str], payload: NetworkEdgeDraftInput
    ) -> None:
        edge = InfrastructureEdgeInput(
            source_node_id=node_ids[payload.source_external_id], target_node_id=node_ids[payload.target_external_id],
            relation_type=payload.relation_type, capacity=payload.capacity, baseline_flow=payload.baseline_flow,
            dependency_strength=payload.dependency_strength, attributes=payload.attributes,
        )
        self._insert_edge(connection, str(uuid4()), UUID(network_id), edge)

    @staticmethod
    def _insert_edge(
        connection: sqlite3.Connection, edge_id: str, network_id: UUID, payload: InfrastructureEdgeInput
    ) -> None:
        connection.execute(
            "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (edge_id, str(network_id), str(payload.source_node_id), str(payload.target_node_id),
             payload.relation_type, payload.capacity, payload.baseline_flow, payload.dependency_strength,
             json.dumps(payload.attributes)),
        )

    def _touch_network(self, connection: sqlite3.Connection, network_id: UUID) -> None:
        connection.execute("UPDATE networks SET updated_at = ? WHERE id = ?", (self._now(), str(network_id)))

    @staticmethod
    def _node_row(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["location"] = (
            {"latitude": value.pop("latitude"), "longitude": value.pop("longitude")}
            if value["latitude"] is not None else None
        )
        value["attributes"] = json.loads(value.pop("attributes_json"))
        value.pop("network_id")
        return value

    @staticmethod
    def _edge_row(row: sqlite3.Row) -> dict:
        value = dict(row)
        value["attributes"] = json.loads(value.pop("attributes_json"))
        value.pop("network_id")
        return value
