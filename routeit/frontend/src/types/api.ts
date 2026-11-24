/**
 * Shared TypeScript Contracts & Formatting Utilities for Route.it Dispatcher UI.
 */

export interface RoadNodeDto {
  id: string;
  name: string;
  lon: number;
  lat: number;
  in_depot_scc: boolean;
}

export interface RoadEdgeDto {
  id: string;
  u: string;
  v: string;
  length_m: number;
  road_class: string;
  free_flow_speed_mps: number;
  u_coord: [number, number];
  v_coord: [number, number];
}

export interface DepotDto {
  id: string;
  name: string;
  lat: number;
  lon: number;
  snapped_node_id: string;
  snap_distance_m: number;
  opening_time_utc_s: number;
  closing_time_utc_s: number | null;
  return_enabled: number | boolean;
  return_deadline_utc_s: number | null;
}

export interface CustomerDto {
  id: string;
  name: string;
  lat: number;
  lon: number;
  snapped_node_id: string;
  snap_distance_m: number;
  address_text: string;
  address_source: string;
  delivery_instructions: string;
  confirmation_status: 'CONFIRMED' | 'PENDING_CONFIRMATION';
}

export interface OrderDto {
  id: string;
  customer_id: string;
  customer_name: string;
  customer_code?: string;
  external_ref: string;
  demand_units: number;
  service_seconds: number;
  window_open_utc_s: number;
  window_close_utc_s: number;
  window_type: 'HARD' | 'SOFT';
  priority: 'CRITICAL' | 'STANDARD' | 'FLEXIBLE';
  status?: 'NEW' | 'IN_TRANSIT' | 'DELIVERED' | 'CANCELLED' | 'RETURNED';
  promised_date?: string;
  is_overdue?: number | boolean;
  lat: number;
  lon: number;
  snapped_node_id: string;
  address_text: string;
  delivery_instructions: string;
}

export interface VehicleDto {
  id: string;
  depot_id: string;
  code: string;
  capacity_units: number;
  activation_cost_paise: number;
  available: number | boolean;
  return_to_depot: number | boolean | null;
  vehicle_profile: string;
  driver_name?: string;
  driver_username?: string;
  driver_password?: string;
  in_transit?: number | boolean;
}

export interface CostProfileDto {
  id: string;
  name: string;
  version: number;
  rounding_policy_version: string;
  rates: {
    distance_rate_paise_per_km: { n: number; d: number };
    time_rate_paise_per_hour: { n: number; d: number };
    critical_sla_paise_per_min: { n: number; d: number };
    standard_sla_paise_per_min: { n: number; d: number };
    flexible_sla_paise_per_min: { n: number; d: number };
  };
}

export interface TrafficScenarioDto {
  id: string;
  name: string;
  kind: 'STATIC' | 'TIME_PROFILE' | 'INCIDENT_OVERLAY';
  revision: number;
  params: {
    closed_edge_ids: string[];
    edge_multipliers_override: Record<string, number>;
  };
}

export interface RouteStopDto {
  id: string;
  seq: number;
  order_id: string;
  external_ref: string;
  customer_name: string;
  customer_code?: string;
  demand_units: number;
  arrival_utc_s: number;
  wait_s: number;
  service_start_utc_s: number;
  service_end_utc_s: number;
  window_open_utc_s: number;
  window_close_utc_s: number;
  window_type: 'HARD' | 'SOFT';
  priority: 'CRITICAL' | 'STANDARD' | 'FLEXIBLE';
  lateness_s: number;
  sla_cost_paise: number;
  stop_state: string;
  order_status?: string;
  promised_date?: string;
  is_overdue?: number | boolean;
  address_text?: string;
  delivery_instructions?: string;
  lat: number;
  lon: number;
}

export interface RouteDto {
  id: string;
  vehicle_id: string;
  vehicle_code: string;
  departure_utc_s: number;
  return_utc_s: number;
  distance_m: number;
  paid_seconds: number;
  idle_seconds: number;
  initial_load_units: number;
  capacity_units: number;
  distance_cost_paise: number;
  time_cost_paise: number;
  sla_cost_paise: number;
  activation_paise: number;
  path_coords: [number, number][];
  outbound_path_coords?: [number, number][];
  return_path_coords?: [number, number][];
  stops: RouteStopDto[];
}

export interface PlanDto {
  id: string;
  run_id: string;
  shift_id: string;
  version: number;
  status: string;
  result_status: string;
  context_hash: string;
  coverage_critical: number;
  coverage_standard: number;
  coverage_flexible: number;
  total_cost_paise: number;
  idle_seconds: number;
  total_distance_m: number;
  total_paid_seconds: number;
  m_routes_used: number;
  m_new_activated: number;
  m_shift_activated_after: number;
  plan_hash: string;
  routes: RouteDto[];
  unserved_orders: {
    order_id: string;
    external_ref: string;
    customer_name: string;
    demand_units: number;
    priority: string;
    reason: string;
    detail: string;
    lat: number;
    lon: number;
  }[];
  cost_breakdown: {
    distance_cost_paise: number;
    time_cost_paise: number;
    sla_cost_paise: number;
    operating_cost_paise: number;
    incremental_activation_cost_paise: number;
    incremental_decision_cost_paise: number;
    activation_posted_before_paise: number;
    activation_posted_after_paise: number;
    sunk_cost_before_paise: number;
    shift_forecast_total_after_paise: number;
    rounding_policy_version: string;
  };
  shift_activation_ledger: {
    shift_id: string;
    vehicle_id: string;
    posted_paise: number;
    posted_by_plan_id: string;
    idempotency_key: string;
    posted_at: string;
  }[];
}

export function formatPaiseToINR(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return '—';
  const rupees = paise / 100;
  return `₹${rupees.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${paise.toLocaleString('en-IN')} paise)`;
}

export function formatSecondsToClockIST(epochSeconds: number): string {
  const date = new Date(epochSeconds * 1000);
  return (
    date.toLocaleTimeString('en-IN', {
      timeZone: 'Asia/Kolkata',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }) + ' IST'
  );
}

export function formatDurationSeconds(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const remS = seconds % 60;
  if (mins >= 60) {
    const hrs = Math.floor(mins / 60);
    const remM = mins % 60;
    return `${hrs}h ${remM}m ${remS}s`;
  }
  return `${mins}m ${remS}s`;
}
