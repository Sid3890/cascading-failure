"""Scenario persistence and deterministic cascade simulation."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.db.network_repository import ConflictError, NetworkRepository, ResourceNotFoundError
from app.schemas.analysis import SimulationResultResponse, StepImpact
from app.schemas.scenario import (
    FailureEvent,
    ScenarioCreateRequest,
    SimulationParameters,
)


class SimulationRepository:
    def __init__(self, database_path: Path, network_repository: NetworkRepository) -> None:
        self.database_path = database_path
        self.network_repository = network_repository

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scenarios (
                    id TEXT PRIMARY KEY,
                    network_id TEXT NOT NULL REFERENCES networks(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS failure_events (
                    id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
                    target_kind TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    severity REAL NOT NULL,
                    start_step INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS simulation_runs (
                    id TEXT PRIMARY KEY,
                    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    completed_at TEXT,
                    error_message TEXT
                );
                CREATE TABLE IF NOT EXISTS simulation_results (
                    run_id TEXT PRIMARY KEY REFERENCES simulation_runs(id) ON DELETE CASCADE,
                    result_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_scenarios_network_id ON scenarios(network_id);
                CREATE INDEX IF NOT EXISTS idx_runs_scenario_id ON simulation_runs(scenario_id);
                """
            )

    def create_scenario(self, payload: ScenarioCreateRequest) -> dict:
        network = self.network_repository.get_network(payload.network_id)
        self._validate_failure_events(network, payload.failure_events)
        scenario_id = str(uuid4())
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO scenarios VALUES (?, ?, ?, ?, ?)",
                (
                    scenario_id,
                    str(payload.network_id),
                    payload.name,
                    json.dumps(payload.parameters.model_dump(mode="json")),
                    self._now(),
                ),
            )
            for event in payload.failure_events:
                connection.execute(
                    "INSERT INTO failure_events VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid4()),
                        scenario_id,
                        event.target_kind,
                        str(event.target_id),
                        event.mode,
                        event.severity,
                        event.start_step,
                    ),
                )
        return self.get_scenario(UUID(scenario_id))

    def list_scenarios(self, network_id: UUID | None, limit: int, offset: int) -> dict:
        where, args = ("", ()) if network_id is None else (" WHERE network_id = ?", (str(network_id),))
        with self._connection() as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM scenarios{where}", args).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM scenarios{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return {"items": [self._scenario_row(row) for row in rows], "total": total}

    def get_scenario(self, scenario_id: UUID) -> dict:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM scenarios WHERE id = ?", (str(scenario_id),)).fetchone()
            if row is None:
                raise ResourceNotFoundError("Scenario not found.")
            event_rows = connection.execute(
                "SELECT * FROM failure_events WHERE scenario_id = ? ORDER BY start_step, id",
                (str(scenario_id),),
            ).fetchall()
        result = self._scenario_row(row)
        result["failure_events"] = [self._event_row(event) for event in event_rows]
        return result

    def delete_scenario(self, scenario_id: UUID) -> None:
        with self._connection() as connection:
            deleted = connection.execute("DELETE FROM scenarios WHERE id = ?", (str(scenario_id),)).rowcount
        if not deleted:
            raise ResourceNotFoundError("Scenario not found.")

    def create_run(self, scenario_id: UUID) -> dict:
        scenario = self.get_scenario(scenario_id)
        run_id, submitted_at = str(uuid4()), self._now()
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO simulation_runs VALUES (?, ?, 'running', ?, NULL, NULL)",
                (run_id, str(scenario_id), submitted_at),
            )
        try:
            network = self.network_repository.get_network(UUID(scenario["network_id"]))
            result = self._simulate(UUID(run_id), network, scenario)
        except Exception as error:
            with self._connection() as connection:
                connection.execute(
                    "UPDATE simulation_runs SET status = 'failed', completed_at = ?, error_message = ? WHERE id = ?",
                    (self._now(), str(error), run_id),
                )
            return self.get_run(UUID(run_id))

        with self._connection() as connection:
            connection.execute(
                "UPDATE simulation_runs SET status = 'completed', completed_at = ? WHERE id = ?",
                (self._now(), run_id),
            )
            connection.execute(
                "INSERT INTO simulation_results VALUES (?, ?)",
                (run_id, json.dumps(result.model_dump(mode="json"))),
            )
        return self.get_run(UUID(run_id))

    def get_run(self, run_id: UUID) -> dict:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM simulation_runs WHERE id = ?", (str(run_id),)).fetchone()
        if row is None:
            raise ResourceNotFoundError("Simulation run not found.")
        result = dict(row)
        result.pop("error_message")
        return result

    def get_result(self, run_id: UUID) -> dict:
        run = self.get_run(run_id)
        if run["status"] == "failed":
            raise ConflictError("The simulation run failed and has no result.")
        if run["status"] != "completed":
            raise ConflictError("The simulation run is not complete.")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT result_json FROM simulation_results WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        if row is None:
            raise ConflictError("The simulation result is not available yet.")
        return json.loads(row["result_json"])

    def _simulate(self, run_id: UUID, network: dict, scenario: dict) -> SimulationResultResponse:
        parameters = SimulationParameters.model_validate(scenario["parameters"])
        events = [FailureEvent.model_validate(event) for event in scenario["failure_events"]]
        nodes = {node["id"]: node for node in network["nodes"]}
        edges = {edge["id"]: edge for edge in network["edges"]}
        loads = {node_id: float(node["baseline_load"]) for node_id, node in nodes.items()}
        capacities = {node_id: float(node["capacity"]) for node_id, node in nodes.items()}
        capacity_factor = {node_id: 1.0 for node_id in nodes}
        edge_factor = {edge_id: 1.0 for edge_id in edges}
        failed_nodes = {node_id for node_id, node in nodes.items() if node["status"] == "failed"}
        failed_edges: set[str] = set()
        pending_failures = set(failed_nodes)
        applied_event_indexes: set[int] = set()
        affected_demand = 0.0
        steps: list[StepImpact] = []
        total_demand = sum(loads.values())

        for step in range(parameters.max_steps):
            new_nodes = set(pending_failures)
            new_edges: set[str] = set()
            pending_failures = set()
            for index, event in enumerate(events):
                if index in applied_event_indexes or event.start_step != step:
                    continue
                applied_event_indexes.add(index)
                target_id = str(event.target_id)
                if event.target_kind == "node":
                    capacity_factor[target_id] *= 1 - event.severity
                    if event.mode == "complete_failure":
                        new_nodes.add(target_id)
                        failed_nodes.add(target_id)
                else:
                    edge_factor[target_id] *= 1 - event.severity
                    if event.mode == "complete_failure":
                        new_edges.add(target_id)
                        failed_edges.add(target_id)
                    edge = edges[target_id]
                    if edge["baseline_flow"] is not None:
                        effective_capacity = (edge["capacity"] or 0) * edge_factor[target_id]
                        affected_demand += max(0.0, float(edge["baseline_flow"]) - effective_capacity)

            for node_id in new_nodes:
                affected_demand += self._redistribute_load(
                    node_id,
                    loads,
                    capacities,
                    capacity_factor,
                    failed_nodes,
                    failed_edges,
                    edges,
                )
                self._apply_dependency_effects(
                    node_id, capacity_factor, failed_edges, edges
                )

            overloaded = {
                node_id
                for node_id in nodes
                if node_id not in failed_nodes
                and loads[node_id] > capacities[node_id] * capacity_factor[node_id] * parameters.overload_threshold
            }
            failed_nodes.update(overloaded)
            pending_failures.update(overloaded)
            new_nodes.update(overloaded)

            remaining_service = max(0.0, total_demand - affected_demand)
            service_ratio = 1.0 if total_demand == 0 else min(1.0, remaining_service / total_demand)
            if new_nodes or new_edges:
                steps.append(
                    StepImpact(
                        step=step,
                        newly_failed_node_ids=sorted(UUID(node_id) for node_id in new_nodes),
                        newly_failed_edge_ids=sorted(UUID(edge_id) for edge_id in new_edges),
                        affected_demand=affected_demand,
                        network_service_ratio=service_ratio,
                    )
                )
            future_events = any(event.start_step > step for event in events)
            if not pending_failures and not future_events:
                break

        service_loss = 0.0 if total_demand == 0 else min(1.0, affected_demand / total_demand)
        return SimulationResultResponse(
            run_id=run_id,
            final_status="completed",
            failed_node_ids=sorted(UUID(node_id) for node_id in failed_nodes),
            failed_edge_ids=sorted(UUID(edge_id) for edge_id in failed_edges),
            affected_demand=affected_demand,
            service_loss_ratio=service_loss,
            cascade_steps=steps,
        )

    @staticmethod
    def _redistribute_load(
        failed_node_id: str,
        loads: dict[str, float],
        capacities: dict[str, float],
        capacity_factor: dict[str, float],
        failed_nodes: set[str],
        failed_edges: set[str],
        edges: dict[str, dict],
    ) -> float:
        demand = loads[failed_node_id]
        loads[failed_node_id] = 0.0
        candidates: list[tuple[str, float]] = []
        for edge_id, edge in edges.items():
            if edge_id in failed_edges or edge_id == "":
                continue
            if edge["source_node_id"] == failed_node_id:
                candidate = edge["target_node_id"]
            elif edge["target_node_id"] == failed_node_id:
                candidate = edge["source_node_id"]
            else:
                continue
            if candidate in failed_nodes:
                continue
            effective_capacity = capacities[candidate] * capacity_factor[candidate]
            if effective_capacity > 0:
                candidates.append((candidate, effective_capacity))
        if not candidates:
            return demand
        total_capacity = sum(capacity for _, capacity in candidates)
        for candidate, capacity in candidates:
            loads[candidate] += demand * capacity / total_capacity
        return 0.0

    @staticmethod
    def _apply_dependency_effects(
        failed_node_id: str,
        capacity_factor: dict[str, float],
        failed_edges: set[str],
        edges: dict[str, dict],
    ) -> None:
        for edge_id, edge in edges.items():
            if edge_id in failed_edges or edge["relation_type"] != "dependency":
                continue
            if edge["source_node_id"] == failed_node_id:
                capacity_factor[edge["target_node_id"]] *= 1 - (edge["dependency_strength"] or 1.0)

    def _validate_failure_events(self, network: dict, events: list[FailureEvent]) -> None:
        node_ids = {node["id"] for node in network["nodes"]}
        edge_ids = {edge["id"] for edge in network["edges"]}
        for event in events:
            valid_ids = node_ids if event.target_kind == "node" else edge_ids
            if str(event.target_id) not in valid_ids:
                raise ConflictError("Every failure event target must belong to the scenario network.")

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _scenario_row(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["parameters"] = json.loads(result.pop("parameters_json"))
        result["failure_events"] = []
        return result

    @staticmethod
    def _event_row(row: sqlite3.Row) -> dict:
        result = dict(row)
        result.pop("id")
        result.pop("scenario_id")
        return result
