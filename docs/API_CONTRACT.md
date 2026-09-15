# Frontend–backend API contract

Base URL in local development: `http://localhost:8000`. The live, generated OpenAPI document is `/api/v1/openapi.json`; use `/docs` to inspect and try the routes.

All JSON field names are `snake_case`. IDs are UUID strings; date-times are ISO 8601 UTC strings. The frontend may send `X-Request-ID`, which is returned on every response to make debugging a request across both applications straightforward.

## Error convention

Every non-2xx response has this shape. Render `error.message`; retain `request_id` in any frontend error report.

```ts
type ErrorResponse = {
  error: {
    code: "VALIDATION_ERROR" | "RESOURCE_NOT_FOUND" | "CONFLICT" | "UNAUTHORIZED" | "HTTP_ERROR" | "INTERNAL_ERROR";
    message: string;
    field: string | null;
  };
  request_id: string;
};
```

`404` means an ID does not exist, `409` means a network invariant was violated (such as duplicate node `external_id`), and `422` means request validation failed.

## Phase 2 — implemented

### Core types

```ts
type GeoPoint = { latitude: number; longitude: number };
type AssetType =
  | "road_segment" | "bridge" | "hospital" | "power_substation"
  | "water_pump" | "telecom_tower" | "other";
type NodeStatus = "operational" | "degraded" | "failed";
type RelationType = "physical" | "dependency" | "flow" | "geographic";
type Attributes = Record<string, string | number | boolean>;

type InfrastructureNodeInput = {
  external_id: string; // unique inside its network
  name: string;
  asset_type: AssetType;
  capacity: number; // > 0
  baseline_load: number; // >= 0
  location?: GeoPoint | null;
  attributes?: Attributes;
};
type InfrastructureNode = InfrastructureNodeInput & {
  id: string;
  status: NodeStatus;
};

type InfrastructureEdgeInput = {
  source_node_id: string;
  target_node_id: string;
  relation_type: RelationType;
  capacity?: number | null;
  baseline_flow?: number | null;
  dependency_strength?: number | null; // 0 through 1
  attributes?: Attributes;
};
type InfrastructureEdge = InfrastructureEdgeInput & { id: string };
```

### Create a complete network

`POST /api/v1/networks` → `201 NetworkResponse`

When nodes and edges are submitted together, node UUIDs do not exist yet. Therefore `edges` must use the node `external_id` values, rather than UUIDs.

```ts
type NetworkEdgeDraftInput = Omit<InfrastructureEdgeInput, "source_node_id" | "target_node_id"> & {
  source_external_id: string;
  target_external_id: string;
};
type NetworkCreateRequest = {
  name: string;
  description?: string | null;
  geographic_scope?: string | null;
  nodes?: InfrastructureNodeInput[];
  edges?: NetworkEdgeDraftInput[];
};
type NetworkResponse = {
  id: string;
  name: string;
  description: string | null;
  geographic_scope: string | null;
  nodes: InfrastructureNode[];
  edges: InfrastructureEdge[];
  created_at: string;
  updated_at: string;
};
```

### Network endpoints

| Endpoint | Request body | Success response |
| --- | --- | --- |
| `GET /api/v1/networks?limit=50&offset=0` | None. `limit` is 1–100. | `200 NetworkListResponse` |
| `POST /api/v1/networks` | `NetworkCreateRequest` | `201 NetworkResponse` |
| `GET /api/v1/networks/{network_id}` | None | `200 NetworkResponse` |
| `PATCH /api/v1/networks/{network_id}` | `NetworkUpdateRequest` | `200 NetworkResponse` |
| `DELETE /api/v1/networks/{network_id}` | None | `204` empty body |

```ts
type NetworkUpdateRequest = {
  name?: string;
  description?: string | null;
  geographic_scope?: string | null;
}; // supply at least one field
type NetworkSummary = {
  id: string;
  name: string;
  description: string | null;
  geographic_scope: string | null;
  node_count: number;
  edge_count: number;
  created_at: string;
  updated_at: string;
};
type NetworkListResponse = { items: NetworkSummary[]; total: number };
```

### Node and edge endpoints

| Endpoint | Request body | Success response |
| --- | --- | --- |
| `POST /api/v1/networks/{network_id}/nodes` | `InfrastructureNodeInput` | `201 InfrastructureNode` |
| `GET /api/v1/networks/{network_id}/nodes/{node_id}` | None | `200 InfrastructureNode` |
| `PATCH /api/v1/networks/{network_id}/nodes/{node_id}` | `NodeUpdateRequest` | `200 InfrastructureNode` |
| `DELETE /api/v1/networks/{network_id}/nodes/{node_id}` | None | `204` empty body; connected edges are also deleted |
| `POST /api/v1/networks/{network_id}/edges` | `InfrastructureEdgeInput` | `201 InfrastructureEdge` |
| `GET /api/v1/networks/{network_id}/edges/{edge_id}` | None | `200 InfrastructureEdge` |
| `PATCH /api/v1/networks/{network_id}/edges/{edge_id}` | `EdgeUpdateRequest` | `200 InfrastructureEdge` |
| `DELETE /api/v1/networks/{network_id}/edges/{edge_id}` | None | `204` empty body |

```ts
type NodeUpdateRequest = Partial<Omit<InfrastructureNode, "id" | "external_id">>;
type EdgeUpdateRequest = Partial<Omit<InfrastructureEdgeInput, "source_node_id" | "target_node_id">>;
// Patch payloads must contain at least one field.
```

For `POST .../edges`, both node UUIDs must belong to the `network_id` in the route; otherwise the API returns `409 CONFLICT`.

## System endpoints

- `GET /health` → `{ status: "ok", service: string, version: string, timestamp: string }`
- `GET /api/v1/meta` → current phase and available resource groups.

## Phase 3 — implemented: scenarios and cascade simulation

### Scenario types

```ts
type FailureEvent = {
  target_kind: "node" | "edge";
  target_id: string; // must belong to network_id
  mode: "partial_capacity_loss" | "complete_failure";
  severity: number; // 0 through 1; exactly 1 for complete_failure
  start_step?: number; // default 0
};
type SimulationParameters = {
  max_steps?: number; // 1 through 500, default 20
  overload_threshold?: number; // > 0, default 1
  redistribution_strategy?: "proportional" | "shortest_path"; // default proportional
};
type ScenarioCreateRequest = {
  name: string;
  network_id: string;
  failure_events: FailureEvent[]; // at least one
  parameters?: SimulationParameters;
};
type ScenarioResponse = ScenarioCreateRequest & {
  id: string;
  created_at: string;
};
type ScenarioListResponse = { items: ScenarioResponse[]; total: number };
```

| Endpoint | Request body | Success response |
| --- | --- | --- |
| `POST /api/v1/scenarios` | `ScenarioCreateRequest` | `201 ScenarioResponse` |
| `GET /api/v1/scenarios?network_id={id}&limit=50&offset=0` | None; `network_id` is optional | `200 ScenarioListResponse` |
| `GET /api/v1/scenarios/{scenario_id}` | None | `200 ScenarioResponse` |
| `DELETE /api/v1/scenarios/{scenario_id}` | None | `204` empty body |

### Simulation endpoints and types

| Endpoint | Request body | Success response |
| --- | --- | --- |
| `POST /api/v1/scenarios/{scenario_id}/runs` | None | `201 SimulationRunResponse` |
| `GET /api/v1/runs/{run_id}` | None | `200 SimulationRunResponse` |
| `GET /api/v1/runs/{run_id}/result` | None | `200 SimulationResultResponse` when completed |

```ts
type SimulationRunResponse = {
  id: string;
  scenario_id: string;
  status: "queued" | "running" | "completed" | "failed";
  submitted_at: string;
  completed_at: string | null;
};
type StepImpact = {
  step: number;
  newly_failed_node_ids: string[];
  newly_failed_edge_ids: string[];
  affected_demand: number;
  network_service_ratio: number; // 0 through 1
};
type SimulationResultResponse = {
  run_id: string;
  final_status: "completed" | "failed";
  failed_node_ids: string[];
  failed_edge_ids: string[];
  affected_demand: number;
  service_loss_ratio: number; // 0 through 1
  cascade_steps: StepImpact[];
};
```

The prototype completes a run during the `POST` request, so it normally returns `status: "completed"` immediately. The frontend should still follow the pollable run/result contract; this keeps its integration unchanged when runs become background jobs later.

### Cascade model used by this prototype

1. A failure event reduces the target asset's capacity; a complete failure marks it unavailable.
2. A failed node redistributes its current load across connected, operational nodes in proportion to their effective capacity.
3. If an asset's redistributed load exceeds `capacity × overload_threshold`, that asset fails in the next cascade step.
4. A failed source node on a `dependency` edge reduces the target's capacity by `dependency_strength` (defaulting to a complete dependency when omitted).
5. Demand that cannot be redirected is accumulated as `affected_demand`; all steps are retained in `cascade_steps` for timeline/map visualization.

`redistribution_strategy` is reserved for Phase 4 routing enhancements; Phase 3 uses proportional redistribution for both accepted values.

## Phase 4 — implemented: resilience analytics

### Criticality ranking

`GET /api/v1/networks/{network_id}/criticality?metric=failure_impact&limit=25` → `200 CriticalityResponse`

`metric` may be `failure_impact` (default), `betweenness`, or `load_ratio`. `limit` is 1–1000. The response ranks nodes and edges together, with rank 1 being the most critical according to the selected measure.

```ts
type AssetCriticality = {
  asset_id: string;
  asset_kind: "node" | "edge";
  asset_name: string;
  criticality_score: number; // 0 through 1
  rank: number;
  rationale: string;
};
type CriticalityResponse = {
  network_id: string;
  metric: "failure_impact" | "betweenness" | "load_ratio";
  assets: AssetCriticality[];
};
```

- `failure_impact`: independently simulates complete loss of each node or edge; the score is service loss.
- `betweenness`: ranks assets that lie on more shortest network paths; scores are normalized separately for nodes and edges.
- `load_ratio`: ranks node `baseline_load / capacity` or edge `baseline_flow / capacity`.

For this prototype, criticality is calculated in the request. Keep `limit` modest for large networks; Phase 5 can move longer jobs to a worker.

### Alternative-scenario comparison

`POST /api/v1/scenario-comparisons` → `200 ScenarioComparisonResponse`

All submitted scenarios must be distinct and belong to the same network. The endpoint runs each scenario, stores the normal run record, then ranks alternatives by lowest service loss. This is useful when the scenarios represent alternative route closures, mitigations, or recovery choices.

```ts
type ScenarioComparisonRequest = {
  scenario_ids: string[]; // 2 through 10 unique IDs, all from one network
};
type ScenarioComparisonItem = {
  scenario_id: string;
  run_id: string;
  rank: number; // 1 is least impact
  failed_node_count: number;
  failed_edge_count: number;
  affected_demand: number;
  service_loss_ratio: number;
  cascade_step_count: number;
};
type ScenarioComparisonResponse = {
  network_id: string;
  ranking_metric: "service_loss_ratio";
  least_impact_scenario_id: string | null;
  evaluated_at: string;
  scenarios: ScenarioComparisonItem[];
};
```

## Phase 5 — implemented: operations and delivery safeguards

### Portable network export/import

| Endpoint | Request body | Success response |
| --- | --- | --- |
| `GET /api/v1/networks/{network_id}/export` | None | `200 NetworkExportResponse` |
| `POST /api/v1/networks/network-imports` | `NetworkImportRequest` | `201 NetworkResponse` |

Export intentionally omits database UUIDs and operational `status`, so it can be imported into another environment. Edges are represented by their source/target node `external_id` values, just like a normal network create request.

```ts
type NetworkExportResponse = {
  format: "cascading-failure-network/v1";
  exported_at: string;
  network: NetworkCreateRequest;
};
type NetworkImportRequest = {
  format: "cascading-failure-network/v1";
  network: NetworkCreateRequest;
};
```

### Optional API-key protection

Set `API_KEY` in the server environment to enable protection. When set, all `/api/v1` endpoints except the OpenAPI document require:

```http
X-API-Key: your-secret-value
```

If `API_KEY` is unset, local development remains open. This is a prototype safeguard, not a replacement for production identity management, role-based access control, or secret rotation.

### Audit log

Every `POST`, `PATCH`, and `DELETE` request to `/api/v1` is written to the append-only audit table without storing request bodies. Inspect it with `GET /api/v1/audit-events?limit=50&offset=0`.

```ts
type AuditEvent = {
  id: string;
  occurred_at: string;
  request_id: string;
  actor: "anonymous" | "api_key";
  action: string;
  resource_path: string;
  status_code: number;
};
type AuditEventListResponse = { items: AuditEvent[]; total: number };
```

## Delivered scope

All five planned prototype phases are implemented. The remaining work for a production deployment would be external identity/RBAC, a managed PostgreSQL/PostGIS database, background workers for large simulations, rate limiting, backups, and monitoring.
