import React, { useEffect, useMemo, useRef, useState } from 'react';
import { apiClient, DriverJourneyState } from '../api/client';
import {
  DepotDto,
  OrderDto,
  PlanDto,
  RoadEdgeDto,
  RoadNodeDto,
  RouteDto,
  VehicleDto,
  formatSecondsToClockIST,
} from '../types/api';
import {
  InteractiveMap,
  RouteLegFilterMode,
  VEHICLE_COLORS,
  buildInstantStreetGeometryForRoute,
  deriveCustomerCode,
  fastDistMeters,
  normalizeAndUncrossRoutes,
} from './InteractiveMap';

export type DriverNavSection = 'manifest' | 'map' | 'drive' | 'switch';
export type CustomerNavSection = 'overview' | 'map' | 'receipt';

/**
 * Helper to check if a promised delivery date (YYYY-MM-DD) has already passed before today.
 */
export function isPromisedDateOverdue(promisedDate?: string | null): boolean {
  if (!promisedDate || !/^\d{4}-\d{2}-\d{2}$/.test(promisedDate.trim())) return false;
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  const todayStr = `${yyyy}-${mm}-${dd}`;
  return promisedDate.trim() < todayStr;
}

/**
 * Computes the real operational status of an order across the platform (Requirements 7 & 8)
 */
export function computeOrderOperationalStatus(
  order: any,
  activePlan: PlanDto | null,
  vehicles: VehicleDto[],
  driverJourneys: Record<string, DriverJourneyState>
): {
  label: string;
  badgeClass: string;
  isLate: boolean;
  isInTransit: boolean;
  isInDepot: boolean;
  assignedVehicleCode: string | null;
} {
  const rawStatus = String(order.status || order.order_status || 'NEW').toUpperCase();
  if (rawStatus === 'DELIVERED') {
    return {
      label: 'Delivered',
      badgeClass: 'badge-success',
      isLate: false,
      isInTransit: false,
      isInDepot: false,
      assignedVehicleCode: null,
    };
  }
  if (rawStatus === 'CANCELLED' || rawStatus === 'RETURNED') {
    return {
      label: rawStatus === 'CANCELLED' ? 'Cancelled' : 'Customer Not Available (Returned)',
      badgeClass: 'badge-neutral',
      isLate: false,
      isInTransit: false,
      isInDepot: false,
      assignedVehicleCode: null,
    };
  }

  const overdueByDate = Boolean(order.is_overdue) || isPromisedDateOverdue(order.promised_date);

  let matchedRoute: RouteDto | null = null;
  let matchedStop: any = null;
  if (activePlan && activePlan.routes) {
    for (const r of activePlan.routes) {
      const st = (r.stops || []).find(
        (s: any) => s.order_id === order.id || s.external_ref === order.external_ref
      );
      if (st) {
        matchedRoute = r;
        matchedStop = st;
        break;
      }
    }
  }

  const lateByWindow =
    matchedStop &&
    (Number(matchedStop.lateness_s || 0) > 0 ||
      Number(matchedStop.service_end_utc_s || 0) > Number(matchedStop.window_close_utc_s || 1e15));
  const isLate = Boolean(overdueByDate || lateByWindow);

  const vehObj = matchedRoute
    ? vehicles.find((v) => v.id === matchedRoute!.vehicle_id || v.code === matchedRoute!.vehicle_code)
    : null;
  const vehInTransit =
    rawStatus === 'IN_TRANSIT' ||
    Boolean(vehObj?.in_transit) ||
    Boolean(matchedRoute && driverJourneys[matchedRoute.vehicle_id]?.inTransit);

  if (vehInTransit) {
    return {
      label: isLate ? 'In Transit (Late)' : 'In Transit (On Time)',
      badgeClass: isLate ? 'badge-danger' : 'badge-info',
      isLate,
      isInTransit: true,
      isInDepot: false,
      assignedVehicleCode: matchedRoute?.vehicle_code || vehObj?.code || null,
    };
  }

  return {
    label: isLate ? 'In Depot (Past Deadline)' : 'In Depot',
    badgeClass: isLate ? 'badge-danger' : 'badge-warning',
    isLate,
    isInTransit: false,
    isInDepot: true,
    assignedVehicleCode: matchedRoute?.vehicle_code || null,
  };
}

/**
 * Universal Delete / Remove Confirmation Modal Popup
 */
export const UniversalConfirmModal: React.FC<{
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}> = ({
  title,
  message,
  confirmLabel = 'Confirm Delete',
  cancelLabel = 'Cancel',
  danger = true,
  onConfirm,
  onCancel,
}) => {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(22, 24, 22, 0.58)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        padding: 16,
      }}
    >
      <div
        className="card"
        style={{
          maxWidth: 460,
          width: '100%',
          margin: 0,
          border: '1.5px solid var(--border-strong)',
          boxShadow: '0 20px 50px rgba(0,0,0,0.35)',
        }}
      >
        <div className="card-title" style={{ color: danger ? '#9f1c1c' : 'var(--text-primary)' }}>
          {title}
        </div>
        <p style={{ fontSize: 13.5, color: 'var(--text-secondary)', lineHeight: 1.55, margin: '10px 0 18px' }}>
          {message}
        </p>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={danger ? 'btn btn-danger' : 'btn btn-primary'}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

/**
 * Vehicle Driver Details Inspection & Edit Modal
 */
export const DriverDetailsModal: React.FC<{
  vehicle: VehicleDto;
  onClose: () => void;
  onSave: (
    vehicleId: string,
    creds: { driver_name: string; driver_username: string; driver_password: string }
  ) => Promise<void>;
  onOpenDriverPortal?: (vehicle: VehicleDto) => void;
}> = ({ vehicle, onClose, onSave, onOpenDriverPortal }) => {
  const [driverName, setDriverName] = useState(vehicle.driver_name || '');
  const [driverUsername, setDriverUsername] = useState(vehicle.driver_username || '');
  const [driverPassword, setDriverPassword] = useState(vehicle.driver_password || '');
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await onSave(vehicle.id, {
        driver_name: driverName.trim() || `Driver (${vehicle.code})`,
        driver_username: driverUsername.trim() || vehicle.code.toLowerCase(),
        driver_password: driverPassword.trim() || 'pass123',
      });
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(22, 24, 22, 0.58)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9999,
        padding: 16,
      }}
    >
      <div
        className="card"
        style={{
          maxWidth: 490,
          width: '100%',
          margin: 0,
          border: '1.5px solid var(--border-strong)',
          boxShadow: '0 20px 50px rgba(0,0,0,0.35)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div className="card-title">Assigned Driver Details · {vehicle.code}</div>
            <div className="card-subtitle" style={{ marginBottom: 0 }}>
              Driver Portal credentials and operator profile for vehicle {vehicle.code} ({vehicle.capacity_units} kg)
            </div>
          </div>
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Close ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ marginTop: 16 }}>
          <div className="form-group">
            <label className="form-label">Driver Full Name</label>
            <input
              className="form-input"
              value={driverName}
              onChange={(e) => setDriverName(e.target.value)}
              placeholder="e.g., Rajesh Patel"
              required
            />
          </div>
          <div className="grid-2">
            <div className="form-group">
              <label className="form-label">Driver Portal Login Username</label>
              <input
                className="form-input mono"
                value={driverUsername}
                onChange={(e) => setDriverUsername(e.target.value)}
                placeholder="e.g., rajesh101"
                required
              />
            </div>
            <div className="form-group">
              <label className="form-label">Driver Portal Login Password</label>
              <input
                className="form-input mono"
                value={driverPassword}
                onChange={(e) => setDriverPassword(e.target.value)}
                placeholder="e.g., pass101"
                required
              />
            </div>
          </div>

          <div
            style={{
              padding: '12px 14px',
              borderRadius: 8,
              background: 'var(--bg-stone-header)',
              border: '1px solid var(--border-color)',
              fontSize: 12,
              marginBottom: 16,
            }}
          >
            <div>
              <strong>Current Credentials Summary:</strong>
            </div>
            <div className="mono" style={{ marginTop: 4 }}>
              Name: <strong>{driverName || '—'}</strong> · Username:{' '}
              <strong>{driverUsername || '—'}</strong> · Password:{' '}
              <strong>{driverPassword || '—'}</strong>
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
            {onOpenDriverPortal && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  onOpenDriverPortal({
                    ...vehicle,
                    driver_name: driverName,
                    driver_username: driverUsername,
                    driver_password: driverPassword,
                  });
                }}
              >
                🏍️ Open Driver Portal as {driverName || vehicle.code} →
              </button>
            )}
            <div style={{ display: 'flex', gap: 8, marginLeft: 'auto' }}>
              <button type="button" className="btn btn-secondary" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? 'Saving...' : 'Save Driver Details'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

/**
 * PORTAL 2: DRIVER PORTAL WITH GAMEPLAY WASD / ARROW KEYS NAVIGATION,
 * VARIABLE AUTO-CRUISE SPEED (1x / 2x / 4x / 8x), AND AUTO-STOP AT CUSTOMER STOPS!
 */
export const DriverPortalView: React.FC<{
  depot: DepotDto | null;
  vehicles: VehicleDto[];
  orders: OrderDto[];
  activePlan: PlanDto | null;
  roadNodes: RoadNodeDto[];
  roadEdges: RoadEdgeDto[];
  activeSection?: DriverNavSection;
  onChangeSection?: (sec: DriverNavSection) => void;
  preselectedVehicle?: VehicleDto | null;
  onRefreshData: () => Promise<void>;
  onShowToast: (msg: string) => void;
}> = ({
  depot,
  vehicles,
  orders,
  activePlan,
  roadNodes,
  roadEdges,
  activeSection = 'manifest',
  onChangeSection,
  preselectedVehicle,
  onRefreshData,
  onShowToast,
}) => {
  const [loginUser, setLoginUser] = useState('');
  const [loginPass, setLoginPass] = useState('');
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggedInVehicleId, setLoggedInVehicleId] = useState<string | null>(
    preselectedVehicle?.id || null
  );
  const [driverLegMode, setDriverLegMode] = useState<RouteLegFilterMode>('both');

  // Gameplay Street Navigation State
  const [navWindowOpen, setNavWindowOpen] = useState(false);
  const [navWaypointIdx, setNavWaypointIdx] = useState(0);
  // Lateral lane offset in meters (-7.5m left lane to +7.5m right lane within the road boundary)
  const [lateralOffsetM, setLateralOffsetM] = useState(0);
  const [autoCruise, setAutoCruise] = useState(false);
  // Cruise Speed Multiplier: 1x, 2x, 4x, 8x
  const [cruiseSpeedMult, setCruiseSpeedMult] = useState<1 | 2 | 4 | 8>(2);
  // Auto-stop customer prompt when bike arrives at an undelivered customer stop
  const [haltedStopForDelivery, setHaltedStopForDelivery] = useState<any | null>(null);

  useEffect(() => {
    if (preselectedVehicle) {
      setLoggedInVehicleId(preselectedVehicle.id);
      setLoginUser(preselectedVehicle.driver_username || '');
      setLoginPass(preselectedVehicle.driver_password || '');
    }
  }, [preselectedVehicle?.id]);

  // Open navigation window automatically if driver clicks "Live Street Drive (WASD)" in the Driver sidebar
  useEffect(() => {
    if (activeSection === 'drive' && loggedInVehicleId) {
      setNavWindowOpen(true);
    } else if (activeSection === 'switch') {
      setLoggedInVehicleId(null);
      if (onChangeSection) onChangeSection('manifest');
    }
  }, [activeSection]);

  const normalizedRoutes = useMemo(
    () => normalizeAndUncrossRoutes(activePlan?.routes || [], depot),
    [activePlan?.routes, depot]
  );

  const loggedInVehicle = useMemo(
    () => vehicles.find((v) => v.id === loggedInVehicleId) || null,
    [vehicles, loggedInVehicleId]
  );

  const driverRoute: RouteDto | null = useMemo(() => {
    if (!loggedInVehicle) return null;
    return (
      normalizedRoutes.find(
        (r) => r.vehicle_id === loggedInVehicle.id || r.vehicle_code === loggedInVehicle.code
      ) || null
    );
  }, [normalizedRoutes, loggedInVehicle]);

  const driverColor = useMemo(() => {
    if (!driverRoute) return '#15803d';
    const idx = normalizedRoutes.findIndex((r) => r.vehicle_id === driverRoute.vehicle_id);
    return VEHICLE_COLORS[Math.max(0, idx) % VEHICLE_COLORS.length];
  }, [normalizedRoutes, driverRoute]);

  // Build dense road-locked navigation waypoints (~18m spacing) along the driver's exact street route
  const roadLockedWaypoints: [number, number][] = useMemo(() => {
    const depLon = depot?.lon ?? 73.1685;
    const depLat = depot?.lat ?? 22.3106;
    const returnEnabled = depot ? Boolean(depot.return_enabled) : true;
    if (!driverRoute) return [[depLon, depLat]];

    const geom = buildInstantStreetGeometryForRoute(driverRoute, depLon, depLat, returnEnabled);
    const fullTrack: [number, number][] = [...geom.outbound];
    if (returnEnabled && geom.returnLeg.length > 1) {
      fullTrack.push(...geom.returnLeg.slice(1));
    }

    const dense: [number, number][] = [fullTrack[0] || [depLon, depLat]];
    for (let i = 1; i < fullTrack.length; i++) {
      const prev = dense[dense.length - 1];
      const curr = fullTrack[i];
      const dist = fastDistMeters(prev, curr);
      if (dist < 1.5) continue;
      if (dist > 22.0) {
        const steps = Math.min(24, Math.ceil(dist / 18.0));
        for (let s = 1; s < steps; s++) {
          const f = s / steps;
          dense.push([
            Number((prev[0] + f * (curr[0] - prev[0])).toFixed(5)),
            Number((prev[1] + f * (curr[1] - prev[1])).toFixed(5)),
          ]);
        }
      }
      dense.push(curr);
    }
    return dense;
  }, [driverRoute, depot]);

  // Map each customer stop to its nearest waypoint index along roadLockedWaypoints
  const stopWaypointIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    if (!driverRoute || !driverRoute.stops) return map;
    for (const s of driverRoute.stops) {
      const target: [number, number] = [Number(s.lon), Number(s.lat)];
      let bestIdx = 0;
      let bestD = 1e9;
      for (let i = 0; i < roadLockedWaypoints.length; i++) {
        const d = fastDistMeters(roadLockedWaypoints[i], target);
        if (d < bestD) {
          bestD = d;
          bestIdx = i;
        }
      }
      map.set(s.order_id, bestIdx);
    }
    return map;
  }, [driverRoute, roadLockedWaypoints]);

  useEffect(() => {
    if (!loggedInVehicle) return;
    const journeys = apiClient.getDriverJourneys();
    const saved = journeys[loggedInVehicle.id];
    if (saved && saved.waypointIdx < roadLockedWaypoints.length) {
      setNavWaypointIdx(saved.waypointIdx);
    } else {
      setNavWaypointIdx(0);
    }
  }, [loggedInVehicle?.id, roadLockedWaypoints.length]);

  // Compute exact 2D bike coordinates on the road including lateral lane shift (-7.5m left to +7.5m right)
  const currentBikeCoord: [number, number] = useMemo(() => {
    const idx = Math.max(0, Math.min(roadLockedWaypoints.length - 1, navWaypointIdx));
    const base = roadLockedWaypoints[idx] || [depot?.lon ?? 73.1685, depot?.lat ?? 22.3106];
    if (Math.abs(lateralOffsetM) < 0.1 || roadLockedWaypoints.length < 2) return base;

    const nextIdx = Math.min(roadLockedWaypoints.length - 1, idx + 1);
    const prevIdx = Math.max(0, idx - 1);
    const pA = roadLockedWaypoints[prevIdx];
    const pB = roadLockedWaypoints[nextIdx];
    const dx = (pB[0] - pA[0]) * 102900;
    const dy = (pB[1] - pA[1]) * 111130;
    const len = Math.hypot(dx, dy) || 1;
    // Perpendicular right-hand normal vector
    const nx = dy / len;
    const ny = -dx / len;
    return [
      Number((base[0] + (nx * lateralOffsetM) / 102900).toFixed(5)),
      Number((base[1] + (ny * lateralOffsetM) / 111130).toFixed(5)),
    ];
  }, [roadLockedWaypoints, navWaypointIdx, lateralOffsetM, depot]);

  const upcomingTurnInstruction = useMemo(() => {
    if (navWaypointIdx >= roadLockedWaypoints.length - 2) {
      return { dir: 'FINISH', text: '🏁 Approaching Final Destination / Central Depot (H)' };
    }
    const p0 = roadLockedWaypoints[navWaypointIdx];
    const p1 = roadLockedWaypoints[navWaypointIdx + 1];
    const p2 = roadLockedWaypoints[Math.min(navWaypointIdx + 2, roadLockedWaypoints.length - 1)];
    const a1 = Math.atan2(p1[1] - p0[1], p1[0] - p0[0]);
    const a2 = Math.atan2(p2[1] - p1[1], p2[0] - p1[0]);
    let diff = ((a2 - a1) * 180) / Math.PI;
    while (diff > 180) diff -= 360;
    while (diff < -180) diff += 360;

    if (diff > 16) return { dir: 'LEFT', text: '⬅ Left Curve Ahead — Press A / ← or W / ↑' };
    if (diff < -16) return { dir: 'RIGHT', text: '➡ Right Curve Ahead — Press D / → or W / ↑' };
    return { dir: 'STRAIGHT', text: '⬆ Straight Road Ahead — Press W / ↑ to Accelerate' };
  }, [roadLockedWaypoints, navWaypointIdx]);

  const nextUndeliveredStopInfo = useMemo(() => {
    if (!driverRoute || !driverRoute.stops) return null;
    for (const s of driverRoute.stops) {
      const ord = orders.find((o) => o.id === s.order_id);
      const isDeliv =
        ord?.status === 'DELIVERED' || s.order_status === 'DELIVERED' || s.stop_state === 'DELIVERED';
      if (!isDeliv) {
        const d = Math.round(fastDistMeters(currentBikeCoord, [Number(s.lon), Number(s.lat)]));
        return { stop: s, distM: d };
      }
    }
    return null;
  }, [driverRoute, orders, currentBikeCoord]);

  // Compute live compass heading (0°=N, 90°=E, 180°=S, 270°=W) along the direction of motion
  const [motionDirectionSign, setMotionDirectionSign] = useState<1 | -1>(1);

  const computeHeadingAtWaypoint = (idx: number, dirSign: 1 | -1 = 1): number => {
    if (roadLockedWaypoints.length < 2) return 90;
    const clamped = Math.max(0, Math.min(roadLockedWaypoints.length - 1, idx));
    const fromIdx =
      dirSign >= 0
        ? Math.max(0, clamped - 1)
        : Math.min(roadLockedWaypoints.length - 1, clamped + 1);
    const toIdx =
      dirSign >= 0
        ? Math.min(roadLockedWaypoints.length - 1, clamped + 1)
        : Math.max(0, clamped - 1);
    const pFrom = roadLockedWaypoints[fromIdx];
    const pTo = roadLockedWaypoints[toIdx];
    const dx = (pTo[0] - pFrom[0]) * 102900;
    const dy = (pTo[1] - pFrom[1]) * 111130;
    if (Math.hypot(dx, dy) < 0.2) return 90;
    // Compass bearing: 0° = North (+dy), 90° = East (+dx), 180° = South (-dy), 270° = West (-dx)
    return ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360;
  };

  const currentHeadingDeg = useMemo(
    () => computeHeadingAtWaypoint(navWaypointIdx, motionDirectionSign),
    [roadLockedWaypoints, navWaypointIdx, motionDirectionSign]
  );

  // Check if moving from `prevIdx` to `targetIdx` reaches any unhandled customer stop
  const findReachedUnhandledStop = (prevIdx: number, targetIdx: number): { stop: any; wpIdx: number } | null => {
    if (!driverRoute || !driverRoute.stops || targetIdx <= prevIdx) return null;
    for (const st of driverRoute.stops) {
      const stopWpIdx = stopWaypointIndexMap.get(st.order_id);
      const liveOrd = orders.find((o) => o.id === st.order_id);
      const stStatus = String(liveOrd?.status || st.order_status || 'NEW').toUpperCase();
      const isHandled =
        stStatus === 'DELIVERED' || stStatus === 'RETURNED' || stStatus === 'CANCELLED';
      if (!isHandled && stopWpIdx !== undefined && prevIdx < stopWpIdx && targetIdx >= stopWpIdx) {
        return { stop: st, wpIdx: stopWpIdx };
      }
    }
    return null;
  };

  const persistBikePosition = (newIdx: number, newLateral = lateralOffsetM, inTransit = true) => {
    if (!loggedInVehicle) return;
    // If vehicle is currently halted at a customer stop awaiting driver input, block forward movement!
    if (haltedStopForDelivery && newIdx > navWaypointIdx) {
      onShowToast(
        `⏸ Please select "Mark as Delivered" or "Customer Not Available" for ${haltedStopForDelivery.customer_name} before moving ahead!`
      );
      return;
    }

    const dirSign: 1 | -1 = newIdx < navWaypointIdx ? -1 : 1;
    setMotionDirectionSign(dirSign);

    let clampedIdx = Math.max(0, Math.min(roadLockedWaypoints.length - 1, newIdx));
    const reached = findReachedUnhandledStop(navWaypointIdx, clampedIdx);
    if (reached) {
      clampedIdx = reached.wpIdx;
      setAutoCruise(false);
      setHaltedStopForDelivery(reached.stop);
    }

    const clampedLatM = Math.max(-7.5, Math.min(7.5, newLateral));
    setNavWaypointIdx(clampedIdx);
    setLateralOffsetM(clampedLatM);

    const base = roadLockedWaypoints[clampedIdx];
    const hDeg = computeHeadingAtWaypoint(clampedIdx, dirSign);
    apiClient.setDriverJourneyState(loggedInVehicle.id, {
      vehicleId: loggedInVehicle.id,
      vehicleCode: loggedInVehicle.code,
      inTransit,
      lon: base[0],
      lat: base[1],
      waypointIdx: clampedIdx,
      headingDeg: hDeg,
      speedKmh: autoCruise ? cruiseSpeedMult * 22 : 28,
      updatedAt: new Date().toISOString(),
    });
  };

  // Gameplay Keyboard Handler (W/A/S/D and ArrowUp/ArrowLeft/ArrowDown/ArrowRight)
  const stateRef = useRef({ navWaypointIdx, lateralOffsetM, haltedStopForDelivery });
  stateRef.current = { navWaypointIdx, lateralOffsetM, haltedStopForDelivery };

  useEffect(() => {
    if (!navWindowOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const { navWaypointIdx: currIdx, lateralOffsetM: currLat, haltedStopForDelivery: halted } =
        stateRef.current;
      if (e.key === 'ArrowUp' || e.key === 'w' || e.key === 'W') {
        e.preventDefault();
        if (halted) {
          onShowToast(
            `⏸ Reached ${halted.customer_name}! Choose "Mark as Delivered" or "Customer Not Available" in the popup to proceed.`
          );
          return;
        }
        persistBikePosition(currIdx + 1, currLat * 0.85, true);
      } else if (e.key === 'ArrowDown' || e.key === 's' || e.key === 'S') {
        e.preventDefault();
        persistBikePosition(currIdx - 1, currLat * 0.85, true);
      } else if (e.key === 'ArrowLeft' || e.key === 'a' || e.key === 'A') {
        e.preventDefault();
        if (halted) return;
        persistBikePosition(currIdx + 1, Math.max(-7.5, currLat - 2.5), true);
      } else if (e.key === 'ArrowRight' || e.key === 'd' || e.key === 'D') {
        e.preventDefault();
        if (halted) return;
        persistBikePosition(currIdx + 1, Math.min(7.5, currLat + 2.5), true);
      } else if (e.key === ' ') {
        e.preventDefault();
        if (halted) return;
        setAutoCruise((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [navWindowOpen, roadLockedWaypoints.length, loggedInVehicle?.id, orders, driverRoute]);

  // Auto-Cruise with Variable Speed (1x, 2x, 4x, 8x) and Auto-Stop at Every Undelivered Customer Stop!
  useEffect(() => {
    if (!autoCruise || !navWindowOpen) return;
    const intervalMs =
      cruiseSpeedMult === 8
        ? 70
        : cruiseSpeedMult === 4
        ? 135
        : cruiseSpeedMult === 2
        ? 250
        : 480;

    const timer = setInterval(() => {
      setNavWaypointIdx((prev) => {
        if (prev >= roadLockedWaypoints.length - 1) {
          setAutoCruise(false);
          return prev;
        }
        const next = prev + 1;

        // Check if `next` reaches any undelivered customer stop!
        if (driverRoute && driverRoute.stops) {
          for (const st of driverRoute.stops) {
            const stopWpIdx = stopWaypointIndexMap.get(st.order_id);
            const liveOrd = orders.find((o) => o.id === st.order_id);
            const stStatus = String(liveOrd?.status || st.order_status || 'NEW').toUpperCase();
            const isHandled =
              stStatus === 'DELIVERED' || stStatus === 'RETURNED' || stStatus === 'CANCELLED';
            if (!isHandled && stopWpIdx !== undefined && prev < stopWpIdx && next >= stopWpIdx) {
              // Automatically pause Auto-Cruise right at the customer stop so driver can mark as delivered!
              setAutoCruise(false);
              setHaltedStopForDelivery(st);
              if (loggedInVehicle) {
                const pt = roadLockedWaypoints[stopWpIdx];
                apiClient.setDriverJourneyState(loggedInVehicle.id, {
                  vehicleId: loggedInVehicle.id,
                  vehicleCode: loggedInVehicle.code,
                  inTransit: true,
                  lon: pt[0],
                  lat: pt[1],
                  waypointIdx: stopWpIdx,
                  headingDeg: computeHeadingAtWaypoint(stopWpIdx, 1),
                  speedKmh: 0,
                  updatedAt: new Date().toISOString(),
                });
              }
              return stopWpIdx;
            }
          }
        }

        if (loggedInVehicle) {
          const pt = roadLockedWaypoints[next];
          apiClient.setDriverJourneyState(loggedInVehicle.id, {
            vehicleId: loggedInVehicle.id,
            vehicleCode: loggedInVehicle.code,
            inTransit: true,
            lon: pt[0],
            lat: pt[1],
            waypointIdx: next,
            headingDeg: computeHeadingAtWaypoint(next, 1),
            speedKmh: cruiseSpeedMult * 24,
            updatedAt: new Date().toISOString(),
          });
        }
        return next;
      });
    }, intervalMs);

    return () => clearInterval(timer);
  }, [
    autoCruise,
    navWindowOpen,
    cruiseSpeedMult,
    roadLockedWaypoints,
    loggedInVehicle,
    driverRoute,
    orders,
    stopWaypointIndexMap,
  ]);

  const handleDriverLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError(null);
    const u = loginUser.trim().toLowerCase();
    const p = loginPass.trim();
    const matched = vehicles.find(
      (v) =>
        (v.driver_username || '').toLowerCase() === u &&
        (v.driver_password || '') === p
    );
    if (!matched) {
      setLoginError(
        'Invalid driver username or password. Click one of the Quick Demo Driver accounts below to sign in immediately.'
      );
      return;
    }
    setLoggedInVehicleId(matched.id);
    onShowToast(`✓ Signed into Driver Cockpit as ${matched.driver_name} (${matched.code}).`);
  };

  const handleStartJourney = async () => {
    if (!loggedInVehicle) return;
    persistBikePosition(navWaypointIdx, 0, true);
    if (driverRoute) {
      for (const s of driverRoute.stops) {
        const ord = orders.find((o) => o.id === s.order_id);
        if (ord && ord.status !== 'DELIVERED' && ord.status !== 'CANCELLED') {
          await apiClient.updateOrder(s.order_id, { status: 'IN_TRANSIT' });
        }
      }
    }
    await onRefreshData();
    setNavWindowOpen(true);
    if (onChangeSection) onChangeSection('drive');
    onShowToast(
      `🏍️ Journey started for ${loggedInVehicle.code}! Use WASD / Arrow Keys or Auto-Cruise (1x–8x) to drive.`
    );
  };

  const handleCompleteJourneyAtDepot = async () => {
    if (!loggedInVehicle) return;
    setAutoCruise(false);
    setHaltedStopForDelivery(null);
    persistBikePosition(roadLockedWaypoints.length - 1, 0, false);
    await apiClient.updateVehicle(loggedInVehicle.id, { in_transit: false, available: true });
    await onRefreshData();
    setNavWindowOpen(false);
    if (onChangeSection) onChangeSection('manifest');
    onShowToast(
      `🏁 Journey completed! ${loggedInVehicle.code} returned to ${depot?.name || 'Central Depot'}.`
    );
  };

  const handleMarkStopDelivered = async (stop: any, resumeCruiseAfter = false) => {
    const custCode = stop.customer_code || deriveCustomerCode(stop.external_ref, stop.seq);
    await apiClient.updateOrder(stop.order_id, { status: 'DELIVERED' });
    setHaltedStopForDelivery(null);
    await onRefreshData();
    onShowToast(
      `✓ Order ${stop.external_ref} (${custCode} · ${stop.customer_name}) marked as DELIVERED!`
    );
    if (resumeCruiseAfter) {
      setAutoCruise(true);
    }
  };

  const handleMarkCustomerNotAvailable = async (stop: any, resumeCruiseAfter = false) => {
    const custCode = stop.customer_code || deriveCustomerCode(stop.external_ref, stop.seq);
    await apiClient.updateOrder(stop.order_id, { status: 'RETURNED' });
    setHaltedStopForDelivery(null);
    await onRefreshData();
    onShowToast(
      `🚪 Logged "Customer Not Available" for ${stop.external_ref} (${custCode} · ${stop.customer_name}). Moving to next stop.`
    );
    if (resumeCruiseAfter) {
      setAutoCruise(true);
    }
  };

  const handleJumpToNextStop = () => {
    if (!driverRoute || !driverRoute.stops) return;
    const targetStop = nextUndeliveredStopInfo?.stop;
    if (targetStop) {
      const idx = stopWaypointIndexMap.get(targetStop.order_id) ?? navWaypointIdx;
      persistBikePosition(idx, 0, true);
      setHaltedStopForDelivery(targetStop);
    } else {
      persistBikePosition(roadLockedWaypoints.length - 1, 0, true);
    }
  };

  if (!loggedInVehicle) {
    return (
      <div style={{ maxWidth: 640, margin: '24px auto' }}>
        <div className="card" style={{ padding: 30 }}>
          <div className="card-title" style={{ fontSize: 21 }}>
            🏍️ Route.it Driver Cockpit Sign-In
          </div>
          <div className="card-subtitle" style={{ marginBottom: 20 }}>
            Sign in with your assigned vehicle credentials to access your shift delivery manifest, dedicated single-vehicle route map, and interactive WASD street navigation.
          </div>

          {loginError && (
            <div
              style={{
                padding: '10px 14px',
                borderRadius: 6,
                background: '#fef2f2',
                border: '1px solid #f87171',
                color: '#991b1b',
                fontSize: 12.5,
                marginBottom: 16,
              }}
            >
              {loginError}
            </div>
          )}

          <form onSubmit={handleDriverLogin}>
            <div className="grid-2">
              <div className="form-group">
                <label className="form-label">Driver Username</label>
                <input
                  className="form-input mono"
                  value={loginUser}
                  onChange={(e) => setLoginUser(e.target.value)}
                  placeholder="e.g., rajesh101"
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label">Password</label>
                <input
                  type="password"
                  className="form-input mono"
                  value={loginPass}
                  onChange={(e) => setLoginPass(e.target.value)}
                  placeholder="••••••••"
                  required
                />
              </div>
            </div>
            <button
              type="submit"
              className="btn btn-emerald"
              style={{ width: '100%', padding: '11px 16px', fontSize: 14 }}
            >
              Enter Driver Cockpit →
            </button>
          </form>

          <div
            style={{
              marginTop: 24,
              paddingTop: 18,
              borderTop: '1px solid var(--border-color)',
            }}
          >
            <div
              style={{
                fontSize: 11.5,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                color: 'var(--text-muted)',
                marginBottom: 12,
              }}
            >
              1-Click Registered Driver Accounts (For Instant Evaluation):
            </div>
            <div className="grid-2" style={{ gap: 10 }}>
              {vehicles.map((v, idx) => {
                const hasRoute = normalizedRoutes.some(
                  (r) => r.vehicle_id === v.id || r.vehicle_code === v.code
                );
                const color = VEHICLE_COLORS[idx % VEHICLE_COLORS.length];
                return (
                  <button
                    key={v.id}
                    type="button"
                    onClick={() => {
                      setLoginUser(v.driver_username || '');
                      setLoginPass(v.driver_password || '');
                      setLoggedInVehicleId(v.id);
                      onShowToast(`✓ Signed in as ${v.driver_name} (${v.code}).`);
                    }}
                    style={{
                      padding: '10px 14px',
                      borderRadius: 8,
                      border: `1.5px solid ${hasRoute ? color : 'var(--border-strong)'}`,
                      background: 'var(--bg-surface)',
                      cursor: 'pointer',
                      textAlign: 'left',
                      fontSize: 12.5,
                    }}
                  >
                    <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                      👤 {v.driver_name || `Driver (${v.code})`} ·{' '}
                      <span className="mono" style={{ color }}>
                        {v.code}
                      </span>
                    </div>
                    <div className="mono" style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      {v.driver_username} / {v.driver_password}{' '}
                      {hasRoute ? '· ● Active Route' : '· Standby'}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    );
  }

  const deliveredStopsCount = (driverRoute?.stops || []).filter((s) => {
    const ord = orders.find((o) => o.id === s.order_id);
    return ord?.status === 'DELIVERED' || s.order_status === 'DELIVERED';
  }).length;
  const totalStopsCount = driverRoute?.stops?.length || 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Driver Top Telemetry Header Card */}
      <div
        className="card"
        style={{
          background: 'linear-gradient(135deg, #101e16 0%, #182b20 100%)',
          color: '#f7f4ed',
          border: '1px solid #264030',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 16,
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span
              style={{
                padding: '4px 11px',
                borderRadius: 6,
                background: driverColor,
                color: '#ffffff',
                fontWeight: 800,
                fontSize: 12.5,
              }}
              className="mono"
            >
              {loggedInVehicle.code}
            </span>
            <span style={{ fontSize: 19, fontWeight: 700 }}>
              {loggedInVehicle.driver_name}
            </span>
            <span
              className={`badge ${
                loggedInVehicle.in_transit ? 'badge-info' : 'badge-success'
              }`}
            >
              {loggedInVehicle.in_transit ? '🏍️ In Transit (Live GPS Active)' : 'Ready at Depot'}
            </span>
          </div>
          <div style={{ fontSize: 12.5, color: '#b7c9be', marginTop: 6 }}>
            Cargo Load:{' '}
            <strong style={{ color: '#ffffff' }}>
              {driverRoute?.initial_load_units || 0} / {loggedInVehicle.capacity_units} kg
            </strong>{' '}
            · Deliveries Completed:{' '}
            <strong style={{ color: '#6ee7b7' }}>
              {deliveredStopsCount} / {totalStopsCount} Stops
            </strong>{' '}
            · Total Tour:{' '}
            <strong style={{ color: '#ffffff' }}>
              {driverRoute ? (driverRoute.distance_m / 1000).toFixed(2) : '0.00'} km
            </strong>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {driverRoute && (
            <button
              type="button"
              onClick={handleStartJourney}
              style={{
                padding: '10px 20px',
                borderRadius: 8,
                border: '2px solid #6ee7b7',
                background: '#15803d',
                color: '#ffffff',
                fontWeight: 700,
                fontSize: 13.5,
                cursor: 'pointer',
                boxShadow: '0 4px 16px rgba(21, 128, 61, 0.45)',
              }}
            >
              {loggedInVehicle.in_transit
                ? '🎮 Open Street Drive Cockpit (WASD)'
                : '🚀 Start Journey (WASD Street Navigation)'}
            </button>
          )}
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setLoggedInVehicleId(null)}
          >
            Switch Driver
          </button>
        </div>
      </div>

      {!driverRoute ? (
        <div className="card" style={{ padding: 32, textAlign: 'center' }}>
          <div className="card-title">No Active Delivery Route Assigned to {loggedInVehicle.code}</div>
          <p style={{ color: 'var(--text-secondary)', fontSize: 13.5, maxWidth: 520, margin: '8px auto 16px' }}>
            Either no dispatch plan has been generated yet, or {loggedInVehicle.code} is on standby for this shift. Choose another active driver below or generate a plan in the Admin Console.
          </p>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 10, flexWrap: 'wrap' }}>
            {vehicles.map((v) => (
              <button
                key={v.id}
                type="button"
                className="btn btn-secondary"
                onClick={() => setLoggedInVehicleId(v.id)}
              >
                Switch to {v.code} ({v.driver_name})
              </button>
            ))}
          </div>
        </div>
      ) : activeSection === 'map' ? (
        /* Full-Width Driver Route Map Section when "Route & Map View" is clicked in Driver Sidebar */
        <div className="card">
          <div className="card-title">
            Full Interactive Route Map · {loggedInVehicle.code} ({driverRoute.stops.length} Customer Stops)
          </div>
          <div className="card-subtitle">
            Displays your vehicle&apos;s exact street route, live rider position (🏍️), and delivered customer badges (✓). Use the toolbar to switch between Departure Only, Return Path Only, or Both.
          </div>
          <InteractiveMap
            nodes={roadNodes}
            edges={roadEdges}
            depot={depot}
            orders={orders}
            vehicles={vehicles}
            routes={[driverRoute]}
            selectedVehicleIds={[driverRoute.vehicle_id]}
            legFilterMode={driverLegMode}
            onLegFilterModeChange={setDriverLegMode}
            driverBikeMarker={{
              lat: currentBikeCoord[1],
              lon: currentBikeCoord[0],
              headingDeg: currentHeadingDeg,
              label: `${loggedInVehicle.driver_name} (${loggedInVehicle.code})`,
              color: driverColor,
            }}
            height={520}
          />
        </div>
      ) : (
        <div className="grid-2" style={{ alignItems: 'start' }}>
          {/* Left Column: Assigned Customer Orders & Delivery Checkoff */}
          <div className="card">
            <div className="card-title">
              Assigned Delivery Manifest ({driverRoute.stops.length} Customer Stops)
            </div>
            <div className="card-subtitle">
              Deliver each parcel in sequence. Marking an order as Delivered immediately updates the Admin Overview and Dispatch Schedule maps with a ✓ Delivered badge.
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {driverRoute.stops.map((stop: any, sIdx: number) => {
                const custCode =
                  stop.customer_code || deriveCustomerCode(stop.external_ref, sIdx + 1);
                const liveOrd = orders.find((o) => o.id === stop.order_id);
                const isDelivered =
                  liveOrd?.status === 'DELIVERED' || stop.order_status === 'DELIVERED';
                const pDate = liveOrd?.promised_date || stop.promised_date;
                const overdue =
                  Boolean(liveOrd?.is_overdue || stop.is_overdue) ||
                  isPromisedDateOverdue(pDate) ||
                  Number(stop.lateness_s || 0) > 0;

                return (
                  <div
                    key={stop.id || stop.order_id}
                    style={{
                      padding: '14px 16px',
                      borderRadius: 10,
                      border: `1.5px solid ${
                        isDelivered ? '#10b981' : overdue ? '#dc2626' : 'var(--border-strong)'
                      }`,
                      background: isDelivered ? 'var(--brand-subtle)' : 'var(--bg-surface)',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 14,
                      flexWrap: 'wrap',
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 220 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span
                          className="mono"
                          style={{
                            padding: isDelivered ? '2px 8px' : '0',
                            width: isDelivered ? 'auto' : 26,
                            height: 26,
                            borderRadius: 13,
                            background: isDelivered ? '#065f46' : driverColor,
                            color: '#ffffff',
                            fontWeight: 800,
                            fontSize: 11,
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          {isDelivered ? `✓ ${custCode}` : custCode}
                        </span>
                        <strong style={{ fontSize: 14 }}>
                          Stop #{stop.seq}: {stop.customer_name}
                        </strong>
                        <span className="mono" style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                          ({stop.external_ref})
                        </span>
                        <span
                          className={`badge ${
                            isDelivered
                              ? 'badge-success'
                              : overdue
                              ? 'badge-danger'
                              : 'badge-info'
                          }`}
                        >
                          {isDelivered
                            ? '✓ Delivered'
                            : overdue
                            ? '⚠ Past Deadline / Late'
                            : loggedInVehicle.in_transit
                            ? 'In Transit (On Time)'
                            : 'Scheduled'}
                        </span>
                      </div>
                      <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 6 }}>
                        📍 <strong>Address:</strong> {liveOrd?.address_text || stop.address_text || 'Vadodara'}
                        {(liveOrd?.delivery_instructions || stop.delivery_instructions) && (
                          <span>
                            {' '}
                            · <strong>Note:</strong>{' '}
                            {liveOrd?.delivery_instructions || stop.delivery_instructions}
                          </span>
                        )}
                      </div>
                      <div className="mono" style={{ fontSize: 11.5, color: 'var(--text-muted)', marginTop: 4 }}>
                        Weight: <strong>{stop.demand_units} kg</strong> · Priority:{' '}
                        <strong>{stop.priority}</strong>
                        {pDate ? ` · Deadline: ${pDate}` : ''} · ETA:{' '}
                        <strong>{formatSecondsToClockIST(stop.arrival_utc_s)}</strong>
                      </div>
                    </div>

                    <div>
                      {isDelivered ? (
                        <span
                          style={{
                            padding: '8px 14px',
                            borderRadius: 6,
                            background: '#dcfce7',
                            color: '#065f46',
                            fontWeight: 700,
                            fontSize: 12,
                            display: 'inline-block',
                          }}
                        >
                          ✓ Order Delivered
                        </span>
                      ) : liveOrd?.status === 'RETURNED' || stop.order_status === 'RETURNED' ? (
                        <span
                          style={{
                            padding: '8px 14px',
                            borderRadius: 6,
                            background: '#fef2f2',
                            color: '#991b1b',
                            fontWeight: 700,
                            fontSize: 12,
                            display: 'inline-block',
                          }}
                        >
                          🚪 Customer Not Available
                        </span>
                      ) : (
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            className="btn btn-emerald"
                            onClick={() => handleMarkStopDelivered(stop, false)}
                          >
                            ✓ Mark as Delivered
                          </button>
                          <button
                            type="button"
                            className="btn btn-secondary"
                            style={{ color: '#991b1b', borderColor: '#fca5a5' }}
                            onClick={() => handleMarkCustomerNotAvailable(stop, false)}
                          >
                            🚪 Not Available
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right Column: Driver's Dedicated Single-Vehicle Interactive Route Map */}
          <div className="card">
            <div className="card-title">
              My Assigned Route Map ({loggedInVehicle.code} Only)
            </div>
            <div className="card-subtitle">
              Switch between Departure Only, Return Path Only, or Both. Delivered stops show as ✓ emerald badges.
            </div>

            <InteractiveMap
              nodes={roadNodes}
              edges={roadEdges}
              depot={depot}
              orders={orders}
              vehicles={vehicles}
              routes={[driverRoute]}
              selectedVehicleIds={[driverRoute.vehicle_id]}
              legFilterMode={driverLegMode}
              onLegFilterModeChange={setDriverLegMode}
              driverBikeMarker={{
                lat: currentBikeCoord[1],
                lon: currentBikeCoord[0],
                headingDeg: currentHeadingDeg,
                label: `${loggedInVehicle.driver_name} (${loggedInVehicle.code})`,
                color: driverColor,
              }}
              height={440}
            />
          </div>
        </div>
      )}

      {/* GAMEPLAY-STYLE ZOOMED-IN LIVE STREET NAVIGATION WINDOW (Requirement 4) */}
      {navWindowOpen && driverRoute && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(12, 16, 14, 0.85)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 9998,
            padding: 18,
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: 1220,
              width: '100%',
              maxHeight: '95vh',
              overflowY: 'auto',
              margin: 0,
              padding: 20,
              border: '2px solid #10b981',
              boxShadow: '0 25px 70px rgba(0,0,0,0.7)',
            }}
          >
            {/* Top HUD Header */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: 12,
                paddingBottom: 12,
                borderBottom: '1px solid var(--border-color)',
                marginBottom: 12,
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span
                    style={{
                      padding: '4px 11px',
                      borderRadius: 6,
                      background: '#15803d',
                      color: '#ffffff',
                      fontWeight: 800,
                      fontSize: 12.5,
                    }}
                  >
                    🎮 WASD / ARROW KEYS STREET DRIVE · {loggedInVehicle.code}
                  </span>
                  <strong style={{ fontSize: 16 }}>
                    {upcomingTurnInstruction.text}
                  </strong>
                </div>
                <div className="mono" style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                  Bike GPS: <strong>{currentBikeCoord[1].toFixed(5)}°N, {currentBikeCoord[0].toFixed(5)}°E</strong> ·
                  Lane Position: <strong>{lateralOffsetM === 0 ? 'Center Lane' : lateralOffsetM < 0 ? `${Math.abs(lateralOffsetM).toFixed(1)}m Left Lane` : `${lateralOffsetM.toFixed(1)}m Right Lane`} (Road-Boundary Locked)</strong>
                  {nextUndeliveredStopInfo && (
                    <span>
                      {' '}
                      · Next Stop:{' '}
                      <strong style={{ color: driverColor }}>
                        {nextUndeliveredStopInfo.stop.customer_code} ({nextUndeliveredStopInfo.stop.customer_name}) — {nextUndeliveredStopInfo.distM}m
                      </strong>
                    </span>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  className="btn btn-emerald"
                  onClick={handleCompleteJourneyAtDepot}
                >
                  🏁 Finish Journey at Depot
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setAutoCruise(false);
                    setNavWindowOpen(false);
                    if (onChangeSection) onChangeSection('manifest');
                  }}
                >
                  Minimize Window ✕
                </button>
              </div>
            </div>

            {/* IMMEDIATE POPUP MODAL WHEN DRIVER REACHES CUSTOMER STOP (Requirement 9) */}
            {haltedStopForDelivery && (
              <div
                style={{
                  position: 'fixed',
                  inset: 0,
                  background: 'rgba(10, 15, 12, 0.72)',
                  backdropFilter: 'blur(4px)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 10050,
                  padding: 16,
                }}
              >
                <div
                  className="card"
                  style={{
                    maxWidth: 540,
                    width: '100%',
                    margin: 0,
                    padding: 24,
                    border: '2.5px solid #10b981',
                    background: 'var(--bg-surface)',
                    boxShadow: '0 24px 64px rgba(0, 0, 0, 0.55)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                    <span
                      style={{
                        padding: '4px 10px',
                        borderRadius: 999,
                        background: '#dcfce7',
                        color: '#065f46',
                        fontWeight: 800,
                        fontSize: 11.5,
                      }}
                    >
                      📍 REACHED CUSTOMER STOP #{haltedStopForDelivery.seq}
                    </span>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      Forward movement locked until response
                    </span>
                  </div>

                  <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text-primary)' }}>
                    {haltedStopForDelivery.customer_code} · {haltedStopForDelivery.customer_name}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
                    Order ID: <strong className="mono">{haltedStopForDelivery.external_ref}</strong> · Weight:{' '}
                    <strong className="mono">{haltedStopForDelivery.demand_units} kg</strong> · Priority:{' '}
                    <strong>{haltedStopForDelivery.priority}</strong>
                  </div>

                  <div
                    style={{
                      marginTop: 14,
                      padding: '12px 14px',
                      borderRadius: 8,
                      background: 'var(--bg-stone-header)',
                      border: '1px solid var(--border-color)',
                      fontSize: 12.5,
                    }}
                  >
                    <div>
                      <strong>Delivery Address:</strong> {haltedStopForDelivery.address_text || 'Vadodara'}
                    </div>
                    {haltedStopForDelivery.delivery_instructions && (
                      <div style={{ marginTop: 4, color: 'var(--text-secondary)' }}>
                        <strong>Gate / Unloading Note:</strong> &ldquo;{haltedStopForDelivery.delivery_instructions}&rdquo;
                      </div>
                    )}
                  </div>

                  <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-primary)', marginTop: 16, marginBottom: 10 }}>
                    Please record the delivery outcome to unlock the vehicle and proceed to the next stop:
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        className="btn btn-emerald"
                        style={{ flex: 1, padding: '11px 16px', fontSize: 13.5, fontWeight: 800 }}
                        onClick={() => handleMarkStopDelivered(haltedStopForDelivery, false)}
                      >
                        ✅ Mark as Delivered (Continue Manual WASD)
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary"
                        style={{ padding: '11px 14px', fontSize: 12.5, fontWeight: 700 }}
                        onClick={() => handleMarkStopDelivered(haltedStopForDelivery, true)}
                      >
                        ✅ Delivered & Resume Auto-Cruise ▶
                      </button>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleMarkCustomerNotAvailable(haltedStopForDelivery, false)}
                      style={{
                        width: '100%',
                        padding: '10px 16px',
                        borderRadius: 8,
                        border: '1.5px solid #dc2626',
                        background: '#fef2f2',
                        color: '#991b1b',
                        fontWeight: 700,
                        fontSize: 13,
                        cursor: 'pointer',
                      }}
                    >
                      🚪 Customer Not Available (Log Attempt & Move Ahead)
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Arcade D-Pad (WASD / Arrow Keys) + Variable Auto-Cruise Speed Bar (1x, 2x, 4x, 8x) */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: 12,
                padding: '12px 16px',
                borderRadius: 10,
                background: '#161816',
                color: '#f7f4ed',
                marginBottom: 12,
              }}
            >
              {/* Left: WASD / Arrow Keys Gameplay Controls */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11.5, fontWeight: 800, color: '#e5a93c', marginRight: 4 }}>
                  DRIVE (WASD / ARROWS):
                </span>

                <button
                  type="button"
                  onClick={() => persistBikePosition(navWaypointIdx - 1, lateralOffsetM * 0.85, true)}
                  disabled={navWaypointIdx <= 0}
                  style={{
                    padding: '7px 11px',
                    borderRadius: 6,
                    border: '1px solid #444',
                    background: '#262925',
                    color: '#fff',
                    fontWeight: 700,
                    fontSize: 12,
                    cursor: navWaypointIdx <= 0 ? 'not-allowed' : 'pointer',
                  }}
                >
                  ⬇ S / Back
                </button>

                <button
                  type="button"
                  onClick={() =>
                    persistBikePosition(navWaypointIdx + 1, Math.max(-7.5, lateralOffsetM - 2.5), true)
                  }
                  style={{
                    padding: '7px 12px',
                    borderRadius: 6,
                    border:
                      upcomingTurnInstruction.dir === 'LEFT'
                        ? '2px solid #6ee7b7'
                        : '1px solid #444',
                    background:
                      upcomingTurnInstruction.dir === 'LEFT' ? '#15803d' : '#262925',
                    color: '#fff',
                    fontWeight: 700,
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  ⬅ A / Steer Left
                </button>

                <button
                  type="button"
                  onClick={() => persistBikePosition(navWaypointIdx + 1, lateralOffsetM * 0.85, true)}
                  disabled={navWaypointIdx >= roadLockedWaypoints.length - 1}
                  style={{
                    padding: '8px 16px',
                    borderRadius: 6,
                    border: '2px solid #6ee7b7',
                    background: '#15803d',
                    color: '#ffffff',
                    fontWeight: 800,
                    fontSize: 12.5,
                    cursor: 'pointer',
                  }}
                >
                  ⬆ W / Forward
                </button>

                <button
                  type="button"
                  onClick={() =>
                    persistBikePosition(navWaypointIdx + 1, Math.min(7.5, lateralOffsetM + 2.5), true)
                  }
                  style={{
                    padding: '7px 12px',
                    borderRadius: 6,
                    border:
                      upcomingTurnInstruction.dir === 'RIGHT'
                        ? '2px solid #6ee7b7'
                        : '1px solid #444',
                    background:
                      upcomingTurnInstruction.dir === 'RIGHT' ? '#15803d' : '#262925',
                    color: '#fff',
                    fontWeight: 700,
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                >
                  ➡ D / Steer Right
                </button>

                <button
                  type="button"
                  onClick={handleJumpToNextStop}
                  style={{
                    padding: '7px 11px',
                    borderRadius: 6,
                    border: '1px solid #e5a93c',
                    background: '#262925',
                    color: '#e5a93c',
                    fontWeight: 700,
                    fontSize: 11.5,
                    cursor: 'pointer',
                  }}
                >
                  ⏭ Next Stop
                </button>
              </div>

              {/* Right: Auto-Cruise Toggle + Speed Multiplier Selector (1x, 2x, 4x, 8x) */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <button
                  type="button"
                  onClick={() => {
                    setHaltedStopForDelivery(null);
                    setAutoCruise((prev) => !prev);
                  }}
                  style={{
                    padding: '8px 14px',
                    borderRadius: 6,
                    border: '1.5px solid #60a5fa',
                    background: autoCruise ? '#1d4ed8' : '#262925',
                    color: '#ffffff',
                    fontWeight: 800,
                    fontSize: 12.5,
                    cursor: 'pointer',
                  }}
                >
                  {autoCruise ? '⏸ Pause Auto-Cruise' : '▶ Auto-Cruise (Auto-Stops at Customers)'}
                </button>

                <div
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    background: '#262925',
                    borderRadius: 6,
                    border: '1px solid #444',
                    overflow: 'hidden',
                  }}
                  title="Adjust Auto-Cruise Speed for fast demonstration"
                >
                  <span style={{ fontSize: 11, color: '#a3a69f', padding: '0 8px', fontWeight: 600 }}>
                    Speed:
                  </span>
                  {([1, 2, 4, 8] as (1 | 2 | 4 | 8)[]).map((mult) => (
                    <button
                      key={mult}
                      type="button"
                      onClick={() => setCruiseSpeedMult(mult)}
                      className="mono"
                      style={{
                        padding: '6px 9px',
                        fontSize: 11.5,
                        fontWeight: cruiseSpeedMult === mult ? 800 : 500,
                        border: 'none',
                        background: cruiseSpeedMult === mult ? '#10b981' : 'transparent',
                        color: cruiseSpeedMult === mult ? '#064e3b' : '#e4e2dd',
                        cursor: 'pointer',
                      }}
                    >
                      {mult}×
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Zoomed-In Street Map Following the Bike Marker */}
            <InteractiveMap
              nodes={roadNodes}
              edges={roadEdges}
              depot={depot}
              orders={orders}
              vehicles={vehicles}
              routes={[driverRoute]}
              selectedVehicleIds={[driverRoute.vehicle_id]}
              legFilterMode={driverLegMode}
              onLegFilterModeChange={setDriverLegMode}
              driverBikeMarker={{
                lat: currentBikeCoord[1],
                lon: currentBikeCoord[0],
                label: `🏍️ ${loggedInVehicle.driver_name} (${loggedInVehicle.code})`,
                color: driverColor,
              }}
              followBike={true}
              initialZoom={16.3}
              height={460}
            />
          </div>
        </div>
      )}
    </div>
  );
};

/**
 * PORTAL 3: CUSTOMER ORDER TRACKING PORTAL WITH CUTE PASTEL THEME & DEDICATED SECTIONS
 */
export const CustomerTrackingPortalView: React.FC<{
  depot: DepotDto | null;
  orders: OrderDto[];
  vehicles: VehicleDto[];
  activePlan: PlanDto | null;
  roadNodes: RoadNodeDto[];
  roadEdges: RoadEdgeDto[];
  activeSection?: CustomerNavSection;
  onChangeSection?: (sec: CustomerNavSection) => void;
}> = ({
  depot,
  orders,
  vehicles,
  activePlan,
  roadNodes,
  roadEdges,
  activeSection = 'overview',
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(
    orders[0]?.id || null
  );

  const normalizedRoutes = useMemo(
    () => normalizeAndUncrossRoutes(activePlan?.routes || [], depot),
    [activePlan?.routes, depot]
  );

  const driverJourneys = apiClient.getDriverJourneys();

  const trackedOrder = useMemo(() => {
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      const found = orders.find(
        (o, idx) =>
          o.id.toLowerCase() === q ||
          o.external_ref.toLowerCase().includes(q) ||
          (o.customer_code || deriveCustomerCode(o.external_ref, idx + 1)).toLowerCase() === q ||
          o.customer_name.toLowerCase().includes(q)
      );
      if (found) return found;
    }
    return orders.find((o) => o.id === selectedOrderId) || orders[0] || null;
  }, [orders, searchQuery, selectedOrderId]);

  const trackedOrderInfo = useMemo(() => {
    if (!trackedOrder) return null;
    const statusInfo = computeOrderOperationalStatus(
      trackedOrder,
      activePlan ? { ...activePlan, routes: normalizedRoutes } : null,
      vehicles,
      driverJourneys
    );
    let assignedRoute: RouteDto | null = null;
    let assignedStop: any = null;
    for (const r of normalizedRoutes) {
      const st = (r.stops || []).find(
        (s: any) => s.order_id === trackedOrder.id || s.external_ref === trackedOrder.external_ref
      );
      if (st) {
        assignedRoute = r;
        assignedStop = st;
        break;
      }
    }
    const assignedVehicle = assignedRoute
      ? vehicles.find(
          (v) => v.id === assignedRoute!.vehicle_id || v.code === assignedRoute!.vehicle_code
        ) || null
      : null;
    const journey = assignedRoute ? driverJourneys[assignedRoute.vehicle_id] : null;

    return {
      statusInfo,
      assignedRoute,
      assignedStop,
      assignedVehicle,
      journey,
    };
  }, [trackedOrder, activePlan, normalizedRoutes, vehicles, driverJourneys]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Cute Welcoming Hero Card */}
      <div
        className="card"
        style={{
          background: 'linear-gradient(135deg, #fff1f2 0%, #fdf2f8 50%, #f0fdf4 100%)',
          border: '1.5px solid #fecdd3',
          padding: '24px 28px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 14 }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 800, color: '#e11d48', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              ✨ Route.it Customer Care & Live Parcel Tracker
            </div>
            <div className="card-title" style={{ fontSize: 22, color: '#4c1d34', marginTop: 2 }}>
              🎁 Track Your Delivery in Real Time
            </div>
            <div className="card-subtitle" style={{ color: '#7c4a5e', marginBottom: 0 }}>
              Enter your Order ID or choose your parcel below to see live rider movement, delivery ETA, and parcel status.
            </div>
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              className="form-input mono"
              style={{
                width: 280,
                fontWeight: 600,
                borderRadius: 999,
                padding: '9px 16px',
                border: '1.5px solid #f43f5e',
                background: 'var(--bg-surface)',
              }}
              placeholder="Search Order ID (e.g. ORD-VAD-01, C1)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                type="button"
                className="btn btn-secondary"
                style={{ borderRadius: 999 }}
                onClick={() => setSearchQuery('')}
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Cute Pastel Order Selector Pills */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 16 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#881337', alignSelf: 'center', marginRight: 4 }}>
            Your Active Parcels:
          </span>
          {orders.map((o, idx) => {
            const code = o.customer_code || deriveCustomerCode(o.external_ref, idx + 1);
            const active = trackedOrder?.id === o.id;
            const isDeliv = o.status === 'DELIVERED';
            return (
              <button
                key={o.id}
                type="button"
                onClick={() => {
                  setSelectedOrderId(o.id);
                  setSearchQuery(o.external_ref);
                }}
                className="mono"
                style={{
                  padding: '6px 13px',
                  borderRadius: 999,
                  fontSize: 12,
                  fontWeight: active ? 700 : 600,
                  border: '1.5px solid',
                  borderColor: active ? '#e11d48' : isDeliv ? '#34d399' : '#fbcfe8',
                  background: active
                    ? 'linear-gradient(135deg, #e11d48 0%, #be123c 100%)'
                    : isDeliv
                    ? '#ecfdf5'
                    : '#ffffff',
                  color: active ? '#ffffff' : isDeliv ? '#065f46' : '#831843',
                  cursor: 'pointer',
                  boxShadow: active ? '0 3px 10px rgba(225, 29, 72, 0.25)' : 'none',
                  transition: 'all 0.18s ease',
                }}
              >
                {isDeliv ? '✓ ' : '📦 '}
                {code} · {o.customer_name.split(' ')[0]}
              </button>
            );
          })}
        </div>
      </div>

      {trackedOrder && trackedOrderInfo && activeSection === 'map' ? (
        <div className="card">
          <div className="card-title">
            🗺️ Live Delivery Map for {trackedOrder.customer_name} ({trackedOrder.external_ref})
          </div>
          <div className="card-subtitle">
            Watch your delivery rider (🏍️) travel from {depot?.name || 'Central Hub'} directly to your doorstep.
          </div>
          <InteractiveMap
            nodes={roadNodes}
            edges={roadEdges}
            depot={depot}
            orders={[trackedOrder]}
            vehicles={vehicles}
            routes={trackedOrderInfo.assignedRoute ? [trackedOrderInfo.assignedRoute] : []}
            selectedVehicleIds={
              trackedOrderInfo.assignedRoute ? [trackedOrderInfo.assignedRoute.vehicle_id] : []
            }
            driverBikeMarker={
              trackedOrderInfo.journey?.inTransit
                ? {
                    lat: trackedOrderInfo.journey.lat,
                    lon: trackedOrderInfo.journey.lon,
                    label: `🏍️ Your Rider (${trackedOrderInfo.assignedVehicle?.driver_name || trackedOrderInfo.assignedRoute?.vehicle_code})`,
                  }
                : null
            }
            height={500}
          />
        </div>
      ) : trackedOrder && trackedOrderInfo && activeSection === 'receipt' ? (
        <div className="card" style={{ maxWidth: 740, margin: '0 auto', width: '100%' }}>
          <div className="card-title" style={{ fontSize: 19, color: '#831843' }}>
            🧾 Official Delivery Receipt & Consignment Schedule
          </div>
          <div className="card-subtitle">
            Verified shipment details for {trackedOrder.customer_name}
          </div>
          <table className="data-table">
            <tbody>
              <tr>
                <td><strong>Order Reference ID</strong></td>
                <td className="mono"><strong>{trackedOrder.external_ref}</strong></td>
              </tr>
              <tr>
                <td><strong>Customer Name</strong></td>
                <td>{trackedOrder.customer_name}</td>
              </tr>
              <tr>
                <td><strong>Delivery Address</strong></td>
                <td>{trackedOrder.address_text}</td>
              </tr>
              <tr>
                <td><strong>Special Gate Instructions</strong></td>
                <td>{trackedOrder.delivery_instructions || 'Standard doorstep handover'}</td>
              </tr>
              <tr>
                <td><strong>Parcel Weight</strong></td>
                <td className="mono">{trackedOrder.demand_units} kg</td>
              </tr>
              <tr>
                <td><strong>Promised Delivery Date</strong></td>
                <td className="mono">{trackedOrder.promised_date || 'Current Shift'}</td>
              </tr>
              <tr>
                <td><strong>Assigned Rider & Vehicle</strong></td>
                <td>
                  {trackedOrderInfo.assignedVehicle
                    ? `👤 ${trackedOrderInfo.assignedVehicle.driver_name} (${trackedOrderInfo.assignedVehicle.code})`
                    : 'Awaiting Vehicle Assignment at Hub'}
                </td>
              </tr>
              <tr>
                <td><strong>Live Delivery Status</strong></td>
                <td>
                  <span className={`badge ${trackedOrderInfo.statusInfo.badgeClass}`}>
                    {trackedOrderInfo.statusInfo.label}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        trackedOrder &&
        trackedOrderInfo && (
          <div className="grid-2" style={{ alignItems: 'start' }}>
            <div className="card">
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: 10,
                }}
              >
                <div>
                  <div className="card-title" style={{ fontSize: 18 }}>
                    📦 {trackedOrder.customer_name}
                  </div>
                  <div className="card-subtitle" style={{ marginBottom: 0 }}>
                    Order ID: <code className="mono">{trackedOrder.external_ref}</code> · Parcel Weight:{' '}
                    <strong>{trackedOrder.demand_units} kg</strong>
                  </div>
                </div>
                <span
                  className={`badge ${trackedOrderInfo.statusInfo.badgeClass}`}
                  style={{ fontSize: 13, padding: '6px 14px' }}
                >
                  {trackedOrderInfo.statusInfo.label}
                </span>
              </div>

              {/* Cute 4-Step Visual Progress Stepper */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, 1fr)',
                  gap: 10,
                  margin: '20px 0',
                  padding: '14px',
                  borderRadius: 14,
                  background: '#fff1f2',
                  border: '1px solid #fecdd3',
                }}
              >
                {[
                  { icon: '📝', label: 'Order Confirmed', done: true },
                  {
                    icon: '🏢',
                    label: 'At Central Hub',
                    done: trackedOrder.status !== 'CANCELLED',
                  },
                  {
                    icon: '🛵',
                    label: 'Out for Delivery',
                    done:
                      trackedOrderInfo.statusInfo.isInTransit ||
                      trackedOrder.status === 'DELIVERED',
                  },
                  {
                    icon: '🎁',
                    label: 'Delivered!',
                    done: trackedOrder.status === 'DELIVERED',
                  },
                ].map((st, i) => (
                  <div
                    key={i}
                    style={{
                      padding: '10px 8px',
                      borderRadius: 10,
                      background: st.done ? '#ecfdf5' : '#ffffff',
                      border: `1.5px solid ${st.done ? '#10b981' : '#f4d6d1'}`,
                      color: st.done ? '#065f46' : '#9c7282',
                      fontWeight: st.done ? 700 : 500,
                      fontSize: 12,
                      textAlign: 'center',
                    }}
                  >
                    <div style={{ fontSize: 18, marginBottom: 3 }}>{st.icon}</div>
                    <div>
                      {st.done ? '✓ ' : ''}
                      {st.label}
                    </div>
                  </div>
                ))}
              </div>

              <table className="data-table">
                <tbody>
                  <tr>
                    <td><strong>Delivery Address</strong></td>
                    <td>{trackedOrder.address_text}</td>
                  </tr>
                  <tr>
                    <td><strong>Promised Delivery Date</strong></td>
                    <td className="mono">
                      {trackedOrder.promised_date || 'Today (Active Shift)'}
                      {trackedOrderInfo.statusInfo.isLate && (
                        <span className="badge badge-danger" style={{ marginLeft: 8 }}>
                          ⚠ Past Deadline / Late
                        </span>
                      )}
                    </td>
                  </tr>
                  <tr>
                    <td><strong>Your Delivery Rider</strong></td>
                    <td>
                      {trackedOrderInfo.assignedVehicle ? (
                        <span>
                          👤 <strong>{trackedOrderInfo.assignedVehicle.driver_name}</strong> · Vehicle{' '}
                          <strong className="mono">{trackedOrderInfo.assignedVehicle.code}</strong>
                        </span>
                      ) : trackedOrderInfo.assignedRoute ? (
                        <strong className="mono">{trackedOrderInfo.assignedRoute.vehicle_code}</strong>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>
                          Being prepared at {depot?.name || 'Central Hub'}
                        </span>
                      )}
                    </td>
                  </tr>
                  <tr>
                    <td><strong>Estimated Arrival (ETA)</strong></td>
                    <td className="mono">
                      {trackedOrder.status === 'DELIVERED' ? (
                        <strong style={{ color: '#059669' }}>✓ Successfully Delivered</strong>
                      ) : trackedOrderInfo.assignedStop ? (
                        formatSecondsToClockIST(trackedOrderInfo.assignedStop.arrival_utc_s)
                      ) : (
                        `${formatSecondsToClockIST(trackedOrder.window_open_utc_s)} – ${formatSecondsToClockIST(
                          trackedOrder.window_close_utc_s
                        )}`
                      )}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="card">
              <div className="card-title">🛵 Live Rider & Route Map</div>
              <div className="card-subtitle">
                Shows your delivery pin, route from the hub, and live rider position when Out for Delivery.
              </div>
              <InteractiveMap
                nodes={roadNodes}
                edges={roadEdges}
                depot={depot}
                orders={[trackedOrder]}
                vehicles={vehicles}
                routes={trackedOrderInfo.assignedRoute ? [trackedOrderInfo.assignedRoute] : []}
                selectedVehicleIds={
                  trackedOrderInfo.assignedRoute ? [trackedOrderInfo.assignedRoute.vehicle_id] : []
                }
                driverBikeMarker={
                  trackedOrderInfo.journey?.inTransit
                    ? {
                        lat: trackedOrderInfo.journey.lat,
                        lon: trackedOrderInfo.journey.lon,
                        label: `🏍️ Your Rider (${trackedOrderInfo.assignedVehicle?.driver_name || trackedOrderInfo.assignedRoute?.vehicle_code})`,
                      }
                    : null
                }
                height={420}
              />
            </div>
          </div>
        )
      )}
    </div>
  );
};
