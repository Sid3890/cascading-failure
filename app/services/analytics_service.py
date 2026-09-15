"""Criticality ranking and alternative-scenario comparison logic."""

from collections import deque
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.db.network_repository import ConflictError, NetworkRepository
from app.db.simulation_repository import SimulationRepository
from app.schemas.analysis import (
    AssetCriticality,
    CriticalityResponse,
    ScenarioComparisonItem,
    ScenarioComparisonRequest,
    ScenarioComparisonResponse,
)


class AnalyticsService:
    def __init__(
        self,
        network_repository: NetworkRepository,
        simulation_repository: SimulationRepository,
    ) -> None:
        self.network_repository = network_repository
        self.simulation_repository = simulation_repository

    def criticality(self, network_id: UUID, metric: str, limit: int) -> CriticalityResponse:
        network = self.network_repository.get_network(network_id)
        if metric == "betweenness":
            scores = self._betweenness_scores(network)
        elif metric == "load_ratio":
            scores = self._load_ratio_scores(network)
        else:
            scores = self._failure_impact_scores(network)
        assets = self._rank_assets(network, scores, metric)[:limit]
        return CriticalityResponse(network_id=network_id, metric=metric, assets=assets)

    def compare_scenarios(self, payload: ScenarioComparisonRequest) -> ScenarioComparisonResponse:
        scenarios = [self.simulation_repository.get_scenario(scenario_id) for scenario_id in payload.scenario_ids]
        network_ids = {scenario["network_id"] for scenario in scenarios}
        if len(network_ids) != 1:
            raise ConflictError("Scenarios can only be compared when they belong to the same network.")
        rows: list[dict] = []
        for scenario in scenarios:
            run = self.simulation_repository.create_run(UUID(scenario["id"]))
            result = self.simulation_repository.get_result(UUID(run["id"]))
            rows.append(
                {
                    "scenario_id": scenario["id"],
                    "run_id": run["id"],
                    "failed_node_count": len(result["failed_node_ids"]),
                    "failed_edge_count": len(result["failed_edge_ids"]),
                    "affected_demand": result["affected_demand"],
                    "service_loss_ratio": result["service_loss_ratio"],
                    "cascade_step_count": len(result["cascade_steps"]),
                }
            )
        rows.sort(key=lambda row: (row["service_loss_ratio"], row["affected_demand"], row["scenario_id"]))
        ranked = [ScenarioComparisonItem(rank=index, **row) for index, row in enumerate(rows, start=1)]
        return ScenarioComparisonResponse(
            network_id=UUID(network_ids.pop()),
            least_impact_scenario_id=ranked[0].scenario_id if ranked else None,
            evaluated_at=datetime.now(UTC),
            scenarios=ranked,
        )

    def _failure_impact_scores(self, network: dict) -> dict[tuple[str, str], float]:
        scores: dict[tuple[str, str], float] = {}
        for kind, assets in (("node", network["nodes"]), ("edge", network["edges"])):
            for asset in assets:
                result = self.simulation_repository._simulate(
                    uuid4(),
                    network,
                    {
                        "parameters": {},
                        "failure_events": [
                            {
                                "target_kind": kind,
                                "target_id": asset["id"],
                                "mode": "complete_failure",
                                "severity": 1.0,
                                "start_step": 0,
                            }
                        ],
                    },
                )
                scores[(kind, asset["id"])] = result.service_loss_ratio
        return scores

    @staticmethod
    def _load_ratio_scores(network: dict) -> dict[tuple[str, str], float]:
        scores: dict[tuple[str, str], float] = {}
        for node in network["nodes"]:
            scores[("node", node["id"])] = min(1.0, node["baseline_load"] / node["capacity"])
        for edge in network["edges"]:
            capacity = edge["capacity"] or 0
            flow = edge["baseline_flow"] or 0
            scores[("edge", edge["id"])] = min(1.0, flow / capacity) if capacity else 0.0
        return scores

    @staticmethod
    def _betweenness_scores(network: dict) -> dict[tuple[str, str], float]:
        node_ids = [node["id"] for node in network["nodes"]]
        adjacency: dict[str, list[tuple[str, str]]] = {node_id: [] for node_id in node_ids}
        for edge in network["edges"]:
            adjacency[edge["source_node_id"]].append((edge["target_node_id"], edge["id"]))
            adjacency[edge["target_node_id"]].append((edge["source_node_id"], edge["id"]))
        node_scores = {node_id: 0.0 for node_id in node_ids}
        edge_scores = {edge["id"]: 0.0 for edge in network["edges"]}
        for source in node_ids:
            stack: list[str] = []
            predecessors: dict[str, list[tuple[str, str]]] = {node_id: [] for node_id in node_ids}
            path_counts = {node_id: 0.0 for node_id in node_ids}
            distance = {node_id: -1 for node_id in node_ids}
            path_counts[source], distance[source] = 1.0, 0
            queue: deque[str] = deque([source])
            while queue:
                vertex = queue.popleft()
                stack.append(vertex)
                for neighbor, edge_id in adjacency[vertex]:
                    if distance[neighbor] < 0:
                        distance[neighbor] = distance[vertex] + 1
                        queue.append(neighbor)
                    if distance[neighbor] == distance[vertex] + 1:
                        path_counts[neighbor] += path_counts[vertex]
                        predecessors[neighbor].append((vertex, edge_id))
            dependency = {node_id: 0.0 for node_id in node_ids}
            while stack:
                vertex = stack.pop()
                for predecessor, edge_id in predecessors[vertex]:
                    contribution = path_counts[predecessor] / path_counts[vertex] * (1 + dependency[vertex])
                    dependency[predecessor] += contribution
                    edge_scores[edge_id] += contribution
                if vertex != source:
                    node_scores[vertex] += dependency[vertex]
        combined = {
            **{("node", node_id): score / 2 for node_id, score in node_scores.items()},
            **{("edge", edge_id): score / 2 for edge_id, score in edge_scores.items()},
        }
        return AnalyticsService._normalize_by_kind(combined)

    @staticmethod
    def _normalize_by_kind(scores: dict[tuple[str, str], float]) -> dict[tuple[str, str], float]:
        normalized: dict[tuple[str, str], float] = {}
        for kind in ("node", "edge"):
            values = [score for (asset_kind, _), score in scores.items() if asset_kind == kind]
            maximum = max(values, default=0.0)
            for key, score in scores.items():
                if key[0] == kind:
                    normalized[key] = score / maximum if maximum else 0.0
        return normalized

    @staticmethod
    def _rank_assets(
        network: dict, scores: dict[tuple[str, str], float], metric: str
    ) -> list[AssetCriticality]:
        names = {
            **{("node", node["id"]): node["name"] for node in network["nodes"]},
            **{
                ("edge", edge["id"]): f"Connection {edge['source_node_id'][:8]}–{edge['target_node_id'][:8]}"
                for edge in network["edges"]
            },
        }
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
        metric_label = metric.replace("_", " ")
        return [
            AssetCriticality(
                asset_id=asset_id,
                asset_kind=kind,
                asset_name=names[(kind, asset_id)],
                criticality_score=score,
                rank=rank,
                rationale=f"Normalized {metric_label} score for this {kind}.",
            )
            for rank, ((kind, asset_id), score) in enumerate(ordered, start=1)
        ]
