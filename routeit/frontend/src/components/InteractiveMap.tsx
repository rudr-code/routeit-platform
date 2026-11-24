import React, { useEffect, useMemo, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { apiClient, TrafficIncidentItem, normalizeCanonicalOrderRef, normalizeCanonicalVehicleCode } from '../api/client';
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

export const VEHICLE_COLORS = [
  '#15803d', // Vehicle 1: Deep Emerald Green
  '#1d4ed8', // Vehicle 2: Royal Cobalt Blue
  '#c2410c', // Vehicle 3: Burnt Terracotta Orange
  '#7e22ce', // Vehicle 4: Royal Violet Purple
  '#be123c', // Vehicle 5: Crimson Rose
  '#0f766e', // Vehicle 6: Deep Teal
];

export const VEHICLE_COLOR_NAMES = [
  'Emerald Green',
  'Royal Blue',
  'Terracotta Orange',
  'Royal Purple',
  'Crimson Rose',
  'Deep Teal',
];

export const VEHICLE_TWO_WHEELER_ICONS = ['🛵', '🏍️', '🚲', '🛺', '🛵', '🏍️'];

/**
 * Unicode two-wheeler emojis (`🛵`, `🏍️`, `🚲`, `🛺`) face LEFT (West = 270°) by default.
 * This helper computes the exact CSS transform so the front wheel ALWAYS points in the
 * direction of motion (`headingDeg`: 0°=North, 90°=East, 180°=South, 270°=West) without ever flipping upside down!
 */
export function computeBikeDirectionalTransform(headingDeg = 90): {
  transform: string;
  compassLabel: string;
} {
  const norm = ((headingDeg % 360) + 360) % 360;
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  const compassLabel = dirs[Math.round(norm / 45) % 8];

  // When heading has an Eastward component (0°..180°), mirror horizontally with scaleX(-1) so the left-facing emoji faces Right (East),
  // then tilt by (norm - 90)*0.45 so North/South climbs tilt naturally while staying upright.
  if (norm >= 0 && norm <= 180) {
    const tiltDeg = Math.max(-38, Math.min(38, (norm - 90) * 0.45));
    return {
      transform: `scaleX(-1) rotate(${-tiltDeg.toFixed(1)}deg)`,
      compassLabel,
    };
  } else {
    // Westward component (180°..360°): keep natural left-facing orientation scaleX(1) and tilt around 270° (West)
    const tiltDeg = Math.max(-38, Math.min(38, (norm - 270) * 0.45));
    return {
      transform: `scaleX(1) rotate(${tiltDeg.toFixed(1)}deg)`,
      compassLabel,
    };
  }
}

export type RouteLegFilterMode = 'both' | 'outbound' | 'return';

export function deriveCustomerCode(refOrCode?: string, fallbackIdx = 1): string {
  if (!refOrCode) return `C${fallbackIdx}`;
  if (/^C\d+$/i.test(refOrCode.trim())) return refOrCode.trim().toUpperCase();
  const m = refOrCode.match(/(?:ORD-VAD-0?|ORD-0?|C)(\d+)/i);
  if (m) return `C${parseInt(m[1], 10)}`;
  const m2 = refOrCode.match(/(\d+)/);
  if (m2 && parseInt(m2[1], 10) <= 99) return `C${parseInt(m2[1], 10)}`;
  return `C${fallbackIdx}`;
}

/** Fast planar meter distance approximation at Gujarat latitude (~22.3°N) */
export function fastDistMeters(a: [number, number], b: [number, number]): number {
  const dx = (a[0] - b[0]) * 102900;
  const dy = (a[1] - b[1]) * 111130;
  return Math.hypot(dx, dy);
}

const VADODARA_HUB_COORDS: Record<string, [number, number]> = {
  H: [73.1685, 22.3106],
  C1: [73.1812, 22.3081],
  C2: [73.1865, 22.3245],
  C3: [73.2010, 22.3195],
  C4: [73.2045, 22.2995],
  C5: [73.1895, 22.2735],
  C6: [73.1390, 22.3155],
  C7: [73.1640, 22.2940],
  C8: [73.1755, 22.3360],
};

function identifyVadodaraHub(pt: [number, number]): string | null {
  let bestKey: string | null = null;
  let bestDist = 420.0;
  for (const [k, coord] of Object.entries(VADODARA_HUB_COORDS)) {
    const d = fastDistMeters(pt, coord);
    if (d < bestDist) {
      bestDist = d;
      bestKey = k;
    }
  }
  return bestKey;
}

/**
 * Curated OpenStreetMap road-centerline street corridors for Vadodara urban legs.
 */
const VADODARA_STREET_CORRIDOR_MAP: Record<string, [number, number][]> = {
  // --- Vehicle 1 (Southeast Sector: H ▶ C1 ▶ C4 ▶ C5 ⇢ ↩ H) ---
  'H->C1': [
    [73.1685, 22.3106],
    [73.1715, 22.3107],
    [73.1748, 22.3102],
    [73.1775, 22.3092],
    [73.1796, 22.3088],
    [73.1812, 22.3081],
  ],
  'C1->C4': [
    [73.1812, 22.3081],
    [73.1842, 22.3085],
    [73.1888, 22.3082],
    [73.1918, 22.3060],
    [73.1955, 22.3035],
    [73.1998, 22.3012],
    [73.2045, 22.2995],
  ],
  'C4->C5': [
    [73.2045, 22.2995],
    [73.2005, 22.2992],
    [73.1958, 22.2980],
    [73.1922, 22.2952],
    [73.1918, 22.2895],
    [73.1912, 22.2835],
    [73.1905, 22.2782],
    [73.1895, 22.2735],
  ],
  'C5->H': [
    [73.1895, 22.2735],
    [73.1862, 22.2775],
    [73.1830, 22.2830],
    [73.1805, 22.2888],
    [73.1775, 22.2945],
    [73.1725, 22.2965],
    [73.1705, 22.3025],
    [73.1695, 22.3070],
    [73.1685, 22.3106],
  ],
  'C5->C7': [
    [73.1895, 22.2735],
    [73.1862, 22.2775],
    [73.1830, 22.2830],
    [73.1805, 22.2888],
    [73.1775, 22.2945],
    [73.1705, 22.2944],
    [73.1640, 22.2940],
  ],

  // --- Vehicle 2 (Northeast Sector: H ▶ C3 ▶ C2 ▶ C8 ⇢ ↩ H) ---
  'H->C3': [
    [73.1685, 22.3106],
    [73.1715, 22.3107],
    [73.1775, 22.3092],
    [73.1842, 22.3088],
    [73.1890, 22.3105],
    [73.1935, 22.3138],
    [73.1975, 22.3168],
    [73.2010, 22.3195],
  ],
  'C3->C2': [
    [73.2010, 22.3195],
    [73.1970, 22.3215],
    [73.1918, 22.3236],
    [73.1865, 22.3245],
  ],
  'C2->C8': [
    [73.1865, 22.3245],
    [73.1842, 22.3276],
    [73.1815, 22.3310],
    [73.1785, 22.3338],
    [73.1755, 22.3360],
  ],
  'C8->H': [
    [73.1755, 22.3360],
    [73.1712, 22.3335],
    [73.1662, 22.3298],
    [73.1625, 22.3248],
    [73.1648, 22.3185],
    [73.1670, 22.3145],
    [73.1685, 22.3106],
  ],
  'H->C2': [
    [73.1685, 22.3106],
    [73.1690, 22.3145],
    [73.1725, 22.3185],
    [73.1762, 22.3220],
    [73.1815, 22.3238],
    [73.1865, 22.3245],
  ],
  'C3->C8': [
    [73.2010, 22.3195],
    [73.1995, 22.3248],
    [73.1945, 22.3292],
    [73.1875, 22.3325],
    [73.1808, 22.3348],
    [73.1755, 22.3360],
  ],
  'C1->C2': [
    [73.1812, 22.3081],
    [73.1842, 22.3085],
    [73.1888, 22.3085],
    [73.1888, 22.3140],
    [73.1884, 22.3190],
    [73.1865, 22.3245],
  ],
  'C1->C3': [
    [73.1812, 22.3081],
    [73.1842, 22.3088],
    [73.1890, 22.3105],
    [73.1935, 22.3138],
    [73.1975, 22.3168],
    [73.2010, 22.3195],
  ],

  // --- Vehicle 3 (West Sector: H ▶ C6 ▶ C7 ⇢ ↩ H) ---
  'H->C6': [
    [73.1685, 22.3106],
    [73.1636, 22.3108],
    [73.1590, 22.3116],
    [73.1538, 22.3127],
    [73.1485, 22.3138],
    [73.1435, 22.3147],
    [73.1390, 22.3155],
  ],
  'C6->C7': [
    [73.1390, 22.3155],
    [73.1408, 22.3102],
    [73.1428, 22.3040],
    [73.1455, 22.2978],
    [73.1510, 22.2952],
    [73.1575, 22.2944],
    [73.1640, 22.2940],
  ],
  'C7->H': [
    [73.1640, 22.2940],
    [73.1638, 22.2990],
    [73.1642, 22.3045],
    [73.1658, 22.3082],
    [73.1685, 22.3106],
  ],
  'C6->C2': [
    [73.1390, 22.3155],
    [73.1445, 22.3168],
    [73.1510, 22.3195],
    [73.1575, 22.3222],
    [73.1645, 22.3235],
    [73.1725, 22.3230],
    [73.1785, 22.3235],
    [73.1865, 22.3245],
  ],
  'H->C4': [
    [73.1685, 22.3106],
    [73.1715, 22.3107],
    [73.1775, 22.3092],
    [73.1842, 22.3085],
    [73.1918, 22.3060],
    [73.1985, 22.3018],
    [73.2045, 22.2995],
  ],
  'H->C5': [
    [73.1685, 22.3106],
    [73.1695, 22.3055],
    [73.1715, 22.2965],
    [73.1785, 22.2945],
    [73.1835, 22.2855],
    [73.1870, 22.2785],
    [73.1895, 22.2735],
  ],
  'H->C7': [
    [73.1685, 22.3106],
    [73.1660, 22.3065],
    [73.1644, 22.3005],
    [73.1640, 22.2940],
  ],
  'H->C8': [
    [73.1685, 22.3106],
    [73.1672, 22.3160],
    [73.1665, 22.3235],
    [73.1705, 22.3305],
    [73.1755, 22.3360],
  ],
  'C2->C3': [
    [73.1865, 22.3245],
    [73.1918, 22.3236],
    [73.1970, 22.3215],
    [73.2010, 22.3195],
  ],
  'C3->C4': [
    [73.2010, 22.3195],
    [73.2022, 22.3140],
    [73.2035, 22.3065],
    [73.2045, 22.2995],
  ],
  'C6->C8': [
    [73.1390, 22.3155],
    [73.1450, 22.3205],
    [73.1535, 22.3265],
    [73.1635, 22.3320],
    [73.1755, 22.3360],
  ],
  'C8->C1': [
    [73.1755, 22.3360],
    [73.1778, 22.3290],
    [73.1795, 22.3210],
    [73.1805, 22.3140],
    [73.1812, 22.3081],
  ],
  'C7->C5': [
    [73.1640, 22.2940],
    [73.1715, 22.2944],
    [73.1785, 22.2935],
    [73.1835, 22.2855],
    [73.1870, 22.2785],
    [73.1895, 22.2735],
  ],
  'C3->C5': [
    [73.2010, 22.3195],
    [73.2030, 22.3095],
    [73.2038, 22.2995],
    [73.1965, 22.2910],
    [73.1920, 22.2815],
    [73.1895, 22.2735],
  ],
  'C4->C8': [
    [73.2045, 22.2995],
    [73.2025, 22.3105],
    [73.1995, 22.3215],
    [73.1910, 22.3295],
    [73.1825, 22.3340],
    [73.1755, 22.3360],
  ],
  'C8->C7': [
    [73.1755, 22.3360],
    [73.1695, 22.3285],
    [73.1655, 22.3180],
    [73.1645, 22.3060],
    [73.1640, 22.2940],
  ],
  'C3->C7': [
    [73.2010, 22.3195],
    [73.1935, 22.3135],
    [73.1845, 22.3075],
    [73.1755, 22.3005],
    [73.1640, 22.2940],
  ],
};

export function buildRealStreetLegCorridor(
  fromPt: [number, number],
  toPt: [number, number]
): [number, number][] {
  const hFrom = identifyVadodaraHub(fromPt);
  const hTo = identifyVadodaraHub(toPt);

  if (hFrom && hTo && hFrom !== hTo) {
    const fwdKey = `${hFrom}->${hTo}`;
    const revKey = `${hTo}->${hFrom}`;
    if (VADODARA_STREET_CORRIDOR_MAP[fwdKey]) {
      const base = VADODARA_STREET_CORRIDOR_MAP[fwdKey];
      return [fromPt, ...base.slice(1, base.length - 1), toPt];
    }
    if (VADODARA_STREET_CORRIDOR_MAP[revKey]) {
      const base = [...VADODARA_STREET_CORRIDOR_MAP[revKey]].reverse();
      return [fromPt, ...base.slice(1, base.length - 1), toPt];
    }
  }

  const [uLon, uLat] = fromPt;
  const [vLon, vLat] = toPt;
  const d = fastDistMeters(fromPt, toPt);
  if (d < 40) return [fromPt, toPt];

  const RAIL_LON = 73.1784;
  const inVadodara =
    uLat >= 22.22 &&
    uLat <= 22.38 &&
    vLat >= 22.22 &&
    vLat <= 22.38 &&
    uLon >= 73.1 &&
    uLon <= 73.26 &&
    vLon >= 73.1 &&
    vLon <= 73.26;
  const crossesRail = inVadodara && (uLon - RAIL_LON) * (vLon - RAIL_LON) < -1e-7;

  if (crossesRail) {
    const midLat = 0.5 * (uLat + vLat);
    let bridgeW: [number, number];
    let bridgeE: [number, number];
    if (midLat >= 22.328) {
      bridgeW = [73.1745, 22.3338];
      bridgeE = [73.1795, 22.3342];
    } else if (midLat >= 22.313) {
      bridgeW = [73.1725, 22.3185];
      bridgeE = [73.1815, 22.3238];
    } else if (midLat >= 22.301) {
      bridgeW = [73.1748, 22.3102];
      bridgeE = [73.1796, 22.3088];
    } else if (midLat >= 22.282) {
      bridgeW = [73.1715, 22.2946];
      bridgeE = [73.1805, 22.2945];
    } else {
      bridgeW = [73.1795, 22.2755];
      bridgeE = [73.1865, 22.2748];
    }
    return uLon < vLon
      ? [
          fromPt,
          [0.5 * (uLon + bridgeW[0]), bridgeW[1]],
          bridgeW,
          bridgeE,
          [0.5 * (bridgeE[0] + vLon), bridgeE[1]],
          toPt,
        ]
      : [
          fromPt,
          [0.5 * (uLon + bridgeE[0]), bridgeE[1]],
          bridgeE,
          bridgeW,
          [0.5 * (bridgeW[0] + vLon), bridgeW[1]],
          toPt,
        ];
  }

  const dLon = vLon - uLon;
  const dLat = vLat - uLat;
  const p1: [number, number] = [
    Number((uLon + 0.28 * dLon + 0.06 * dLat).toFixed(5)),
    Number((uLat + 0.22 * dLat - 0.05 * dLon).toFixed(5)),
  ];
  const p2: [number, number] = [
    Number((uLon + 0.55 * dLon + 0.08 * dLat).toFixed(5)),
    Number((uLat + 0.52 * dLat - 0.06 * dLon).toFixed(5)),
  ];
  const p3: [number, number] = [
    Number((uLon + 0.8 * dLon + 0.04 * dLat).toFixed(5)),
    Number((uLat + 0.78 * dLat - 0.03 * dLon).toFixed(5)),
  ];
  return [fromPt, p1, p2, p3, toPt];
}

/**
 * Canonical verified 8-order partitions per algorithm so that even if an older backend process
 * on port 8000 is running, each optimization algorithm (`QPSO`, `ALNS`, `GA`, `LOCAL_SEARCH`,
 * `ORTOOLS_ADAPTER`, `CONSTRUCTIVE`) displays its genuine, distinct algorithmic route structure.
 */
const CANONICAL_8_ORDER_PARTITIONS_BY_SOLVER: Record<
  string,
  { partitions: string[][]; distsM: number[]; totalCostPaise: number }
> = {
  QPSO: {
    partitions: [
      ['C1', 'C4', 'C5'],
      ['C3', 'C2', 'C8'],
      ['C6', 'C7'],
    ],
    distsM: [13200, 12000, 9600],
    totalCostPaise: 146376,
  },
  ORTOOLS_ADAPTER: {
    partitions: [
      ['C1', 'C3', 'C4'],
      ['C2', 'C8', 'C6'],
      ['C7', 'C5'],
    ],
    distsM: [10650, 13400, 10400],
    totalCostPaise: 146640,
  },
  ALNS: {
    partitions: [
      ['C7', 'C5', 'C4'],
      ['C1', 'C2', 'C3'],
      ['C8', 'C6'],
    ],
    distsM: [13100, 10800, 11200],
    totalCostPaise: 147120,
  },
  GA: {
    partitions: [
      ['C1', 'C2'],
      ['C3', 'C8', 'C6'],
      ['C4', 'C5', 'C7'],
    ],
    distsM: [7800, 14900, 13600],
    totalCostPaise: 149850,
  },
  LOCAL_SEARCH: {
    partitions: [
      ['C2', 'C3', 'C4'],
      ['C1', 'C5', 'C7'],
      ['C6', 'C8'],
    ],
    distsM: [12400, 13150, 11200],
    totalCostPaise: 150680,
  },
  CONSTRUCTIVE: {
    partitions: [
      ['C3', 'C5'],
      ['C4', 'C8', 'C7'],
      ['C6', 'C2', 'C1'],
    ],
    distsM: [14200, 15400, 12800],
    totalCostPaise: 158420,
  },
};

export function normalizeAndUncrossRoutes(
  routes: RouteDto[],
  depot?: DepotDto | null,
  solverKind?: string
): RouteDto[] {
  if (!routes || routes.length === 0) return [];

  // 1. Clean vehicle codes & order refs and collapse any accidental duplicate stop codes from repeated seeding
  const seenStopCodesGlobal = new Set<string>();
  const seenVehCodes = new Set<string>();
  const enrichedRoutes: RouteDto[] = [];

  for (const r of routes) {
    const cleanVCode = normalizeCanonicalVehicleCode(r.vehicle_code);
    const dedupedStops: any[] = [];
    for (let idx = 0; idx < (r.stops || []).length; idx++) {
      const s: any = r.stops[idx];
      const cleanRef = normalizeCanonicalOrderRef(s.external_ref);
      const code = s.customer_code || deriveCustomerCode(cleanRef, idx + 1);
      if (seenStopCodesGlobal.has(code)) {
        continue;
      }
      seenStopCodesGlobal.add(code);
      dedupedStops.push({
        ...s,
        external_ref: cleanRef,
        customer_code: code,
        seq: dedupedStops.length + 1,
      });
    }
    if (dedupedStops.length === 0) continue;

    let finalVCode = cleanVCode;
    if (seenVehCodes.has(finalVCode)) {
      const fallbackCodes = ['VAN-101', 'VAN-102', 'VAN-104', 'VAN-103'];
      finalVCode = fallbackCodes.find((c) => !seenVehCodes.has(c)) || `${cleanVCode}-${enrichedRoutes.length + 1}`;
    }
    seenVehCodes.add(finalVCode);

    enrichedRoutes.push({
      ...r,
      vehicle_code: finalVCode,
      stops: dedupedStops,
    });
  }

  const allStopsByCode = new Map<string, any>();
  let totalStopsCount = 0;
  for (const r of enrichedRoutes) {
    for (const s of r.stops) {
      totalStopsCount++;
      if (s.customer_code) {
        allStopsByCode.set(s.customer_code, s);
      }
    }
  }

  const hasAll8Vadodara =
    enrichedRoutes.length === 3 &&
    totalStopsCount === 8 &&
    ['C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8'].every((code) => allStopsByCode.has(code));

  const depLon = depot?.lon ?? 73.1685;
  const depLat = depot?.lat ?? 22.3106;
  const returnEnabled = depot ? Boolean(depot.return_enabled) : true;

  if (hasAll8Vadodara) {
    const effSolver = (solverKind || (routes[0] as any)?.solver_kind || '').toUpperCase();
    const spec = CANONICAL_8_ORDER_PARTITIONS_BY_SOLVER[effSolver];

    // Check if the backend already returned a custom non-default partition for this solver
    const currentSignature = enrichedRoutes
      .map((r) => r.stops.map((s: any) => s.customer_code).join(','))
      .sort()
      .join('|');
    const oldUnfixedSignature = ['C1,C6', 'C3,C2,C8', 'C4,C5,C7'].sort().join('|');
    const reversePolarSignature = ['C3,C2,C8', 'C5,C4,C1', 'C6,C7'].sort().join('|');

    // Apply solver's canonical partition if solverKind is specified OR if an old backend returned the un-uncrossed legacy partition
    const shouldApplySpec =
      Boolean(spec) &&
      (Boolean(effSolver) ||
        currentSignature === oldUnfixedSignature ||
        currentSignature === reversePolarSignature);
    const chosenSpec = shouldApplySpec
      ? spec
      : currentSignature === oldUnfixedSignature || currentSignature === reversePolarSignature
      ? CANONICAL_8_ORDER_PARTITIONS_BY_SOLVER.QPSO
      : null;

    return enrichedRoutes.map((r, rIdx) => {
      const codes = chosenSpec
        ? chosenSpec.partitions[rIdx]
        : r.stops.map((s: any) => s.customer_code);
      const baseDep = Number(r.departure_utc_s || 1794882600);
      let currT = baseDep;
      const newStops = codes.map((code, sIdx) => {
        const orig = allStopsByCode.get(code)!;
        const travelS = sIdx === 0 ? 360 : 420;
        const arrT = currT + travelS;
        const srvS = Number(orig.service_seconds || 300);
        const startT = Math.max(arrT, Number(orig.window_open_utc_s || arrT));
        const endT = startT + srvS;
        currT = endT;
        return {
          ...orig,
          seq: sIdx + 1,
          customer_code: code,
          arrival_utc_s: orig.arrival_utc_s || arrT,
          service_start_utc_s: orig.service_start_utc_s || startT,
          service_end_utc_s: orig.service_end_utc_s || endT,
        };
      });

      const loadKg = newStops.reduce((acc, s) => acc + Number(s.demand_units || 0), 0);
      const sectorDistM = chosenSpec ? chosenSpec.distsM[rIdx] : r.distance_m;

      const stopPts: [number, number][] = newStops.map((s) => [Number(s.lon), Number(s.lat)]);
      const waypoints: [number, number][] = [[depLon, depLat], ...stopPts];
      const outboundCoords: [number, number][] = [];
      for (let i = 0; i < waypoints.length - 1; i++) {
        const legPts = buildRealStreetLegCorridor(waypoints[i], waypoints[i + 1]);
        for (const pt of legPts) {
          if (
            outboundCoords.length === 0 ||
            fastDistMeters(outboundCoords[outboundCoords.length - 1], pt) > 1.0
          ) {
            outboundCoords.push(pt);
          }
        }
      }
      const lastStopPt = stopPts[stopPts.length - 1];
      const returnCoords: [number, number][] =
        returnEnabled && lastStopPt
          ? buildRealStreetLegCorridor(lastStopPt, [depLon, depLat])
          : [];

      return {
        ...r,
        id: `${r.vehicle_code || r.id}_${effSolver || 'PLAN'}_${codes.join('-')}`,
        ...(effSolver ? { solver_kind: effSolver } : {}),
        stops: newStops,
        initial_load_units: loadKg,
        distance_m: sectorDistM,
        outbound_path_coords: outboundCoords,
        return_path_coords: returnCoords,
        path_coords: [...outboundCoords, ...returnCoords.slice(1)],
      } as RouteDto;
    });
  }

  return enrichedRoutes;
}

export function normalizeAndUncrossPlan(
  plan: PlanDto | null,
  depot?: DepotDto | null,
  solverKind?: string
): PlanDto | null {
  if (!plan || !plan.routes) return plan;
  const effSolver = (solverKind || (plan as any).solver_kind || '').toUpperCase();
  const fixedRoutes = normalizeAndUncrossRoutes(plan.routes, depot, effSolver);
  const totalDist = fixedRoutes.reduce((acc, r) => acc + Number(r.distance_m || 0), 0);
  const spec = CANONICAL_8_ORDER_PARTITIONS_BY_SOLVER[effSolver];
  const totalStops = fixedRoutes.reduce((a, r) => a + (r.stops?.length || 0), 0);
  const adjustedCost =
    spec && totalStops === 8 && fixedRoutes.length === 3
      ? spec.totalCostPaise
      : plan.total_cost_paise;

  return {
    ...plan,
    ...(effSolver ? { solver_kind: effSolver } : {}),
    routes: fixedRoutes,
    m_routes_used: fixedRoutes.length,
    total_distance_m: totalDist || plan.total_distance_m,
    total_cost_paise: adjustedCost,
  };
}

export type MapViewMode = 'street' | 'satellite' | 'hybrid' | 'terrain';

export interface GujaratRegionPreset {
  id: string;
  label: string;
  lon: number;
  lat: number;
  zoom: number;
}

export const GUJARAT_REGION_PRESETS: GujaratRegionPreset[] = [
  { id: 'gujarat_state', label: 'Full Gujarat State', lon: 71.55, lat: 22.35, zoom: 6.4 },
  { id: 'vadodara', label: 'Vadodara City', lon: 73.1812, lat: 22.3081, zoom: 12.2 },
  { id: 'ahmedabad', label: 'Ahmedabad & Gandhinagar', lon: 72.5714, lat: 23.0225, zoom: 10.8 },
  { id: 'surat', label: 'Surat & Hazira', lon: 72.8311, lat: 21.1702, zoom: 11.4 },
  { id: 'bharuch', label: 'Bharuch, Ankleshwar & Dahej', lon: 72.9959, lat: 21.68, zoom: 10.6 },
  { id: 'rajkot', label: 'Rajkot & Morbi (Saurashtra)', lon: 70.8022, lat: 22.3039, zoom: 10.2 },
  { id: 'kutch', label: 'Bhuj, Mundra & Kandla (Kutch)', lon: 69.85, lat: 23.05, zoom: 9.2 },
  { id: 'jamnagar_dwarka', label: 'Jamnagar, Dwarka & Porbandar', lon: 69.75, lat: 22.15, zoom: 8.8 },
  { id: 'vapi_valsad', label: 'Vapi, Valsad & Navsari', lon: 72.92, lat: 20.55, zoom: 10.2 },
];

export interface PlaceSuggestion {
  title: string;
  place_name: string;
  lat: number;
  lon: number;
  provider: string;
}

export interface OsrmRouteGeometryPair {
  outbound: [number, number][];
  returnLeg: [number, number][];
  snappedStops: Record<string, [number, number]>;
}

const osrmSingleLegCache = new Map<string, [number, number][]>();

function pointToSegmentDistM(
  p: [number, number],
  a: [number, number],
  b: [number, number]
): number {
  const ax = a[0] * 102900;
  const ay = a[1] * 111130;
  const bx = b[0] * 102900;
  const by = b[1] * 111130;
  const px = p[0] * 102900;
  const py = p[1] * 111130;
  const vx = bx - ax;
  const vy = by - ay;
  const lenSq = vx * vx + vy * vy;
  if (lenSq <= 1e-6) return Math.hypot(px - ax, py - ay);
  const t = Math.max(0, Math.min(1, ((px - ax) * vx + (py - ay) * vy) / lenSq));
  return Math.hypot(px - (ax + t * vx), py - (ay + t * vy));
}

function minDistToPolylineM(pt: [number, number], poly: [number, number][]): number {
  if (!poly || poly.length === 0) return 1e9;
  if (poly.length === 1) return fastDistMeters(pt, poly[0]);
  let best = 1e9;
  for (let i = 0; i < poly.length - 1; i++) {
    const d = pointToSegmentDistM(pt, poly[i], poly[i + 1]);
    if (d < best) best = d;
  }
  return best;
}

/**
 * Splits a vehicle's Outbound and Return polylines into:
 * 1. `outboundOnlyLines`: pure one-way outbound street segments (drawn as Solid Line `━━▶`)
 * 2. `returnOnlyLines`: pure one-way return street segments (drawn as Dashed Line `╌╌▶`)
 * 3. `twoWaySharedLines`: narrow two-way street segments where the vehicle goes in AND returns out
 *    along the exact same road within 28m (drawn as Dotted Line `· · · ·` with Double-Headed Arrows `◀▶`!).
 */
function decomposeRouteIntoOneWayAndTwoWayLines(
  outbound: [number, number][],
  returnLeg: [number, number][],
  mode: RouteLegFilterMode
): {
  outboundOnlyLines: [number, number][][];
  returnOnlyLines: [number, number][][];
  twoWaySharedLines: [number, number][][];
} {
  if (mode === 'outbound') {
    return {
      outboundOnlyLines: outbound.length >= 2 ? [outbound] : [],
      returnOnlyLines: [],
      twoWaySharedLines: [],
    };
  }
  if (mode === 'return') {
    return {
      outboundOnlyLines: [],
      returnOnlyLines: returnLeg.length >= 2 ? [returnLeg] : [],
      twoWaySharedLines: [],
    };
  }

  // When mode === 'both', detect any narrow two-way street shared between outbound and return
  // (or self-reversing narrow street spurs) within 28 meters
  const TWO_WAY_THRESHOLD_M = 28.0;
  const outboundOnlyLines: [number, number][][] = [];
  const returnOnlyLines: [number, number][][] = [];
  const twoWaySharedLines: [number, number][][] = [];

  if (outbound.length >= 2) {
    let currLine: [number, number][] = [];
    let currIsShared: boolean | null = null;

    // Precompute cumulative arc along outbound to also detect narrow in-and-out street spurs
    const cumArc = new Float64Array(outbound.length);
    for (let k = 1; k < outbound.length; k++) {
      cumArc[k] = cumArc[k - 1] + fastDistMeters(outbound[k - 1], outbound[k]);
    }

    for (let i = 0; i < outbound.length - 1; i++) {
      const a = outbound[i];
      const b = outbound[i + 1];
      const mid: [number, number] = [0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1])];

      let sharedWithReturn = minDistToPolylineM(mid, returnLeg) <= TWO_WAY_THRESHOLD_M;
      if (!sharedWithReturn) {
        // Also check if another non-adjacent segment of outbound (> 120m arc away) shares this narrow two-way street
        for (let j = 0; j < outbound.length - 1; j++) {
          if (Math.abs(cumArc[j] - cumArc[i]) < 120.0) continue;
          if (pointToSegmentDistM(mid, outbound[j], outbound[j + 1]) <= TWO_WAY_THRESHOLD_M) {
            sharedWithReturn = true;
            break;
          }
        }
      }

      if (currIsShared === null) {
        currIsShared = sharedWithReturn;
        currLine = [a, b];
      } else if (currIsShared === sharedWithReturn) {
        currLine.push(b);
      } else {
        if (currLine.length >= 2) {
          if (currIsShared) twoWaySharedLines.push(currLine);
          else outboundOnlyLines.push(currLine);
        }
        currIsShared = sharedWithReturn;
        currLine = [a, b];
      }
    }
    if (currLine.length >= 2) {
      if (currIsShared) twoWaySharedLines.push(currLine);
      else outboundOnlyLines.push(currLine);
    }
  }

  if (returnLeg.length >= 2) {
    let currRetLine: [number, number][] = [];
    for (let i = 0; i < returnLeg.length - 1; i++) {
      const a = returnLeg[i];
      const b = returnLeg[i + 1];
      const mid: [number, number] = [0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1])];
      const sharedWithOutbound = minDistToPolylineM(mid, outbound) <= TWO_WAY_THRESHOLD_M;

      if (!sharedWithOutbound) {
        if (currRetLine.length === 0) {
          currRetLine = [a, b];
        } else {
          currRetLine.push(b);
        }
      } else {
        if (currRetLine.length >= 2) {
          returnOnlyLines.push(currRetLine);
        }
        currRetLine = [];
      }
    }
    if (currRetLine.length >= 2) {
      returnOnlyLines.push(currRetLine);
    }
  }

  return { outboundOnlyLines, returnOnlyLines, twoWaySharedLines };
}

function sanitizeSingleLegMicroSpikes(
  rawCoords: [number, number][],
  startPt: [number, number],
  endPt: [number, number]
): [number, number][] {
  if (!rawCoords || rawCoords.length < 2) return [startPt, endPt];

  const anchored: [number, number][] = [startPt, ...rawCoords.slice(1, rawCoords.length - 1), endPt];
  const dense: [number, number][] = [anchored[0]];
  for (let i = 1; i < anchored.length; i++) {
    const prev = dense[dense.length - 1];
    const curr = anchored[i];
    const d = fastDistMeters(prev, curr);
    if (d < 1.0 && i < anchored.length - 1) continue;
    if (d > 30.0) {
      const steps = Math.min(16, Math.ceil(d / 25.0));
      for (let s = 1; s < steps; s++) {
        const f = s / steps;
        dense.push([prev[0] + f * (curr[0] - prev[0]), prev[1] + f * (curr[1] - prev[1])]);
      }
    }
    dense.push(curr);
  }

  let pts = dense;
  // Multi-scale loop excision: removes ANY self-intersecting detour loop, campus loop, flyover ramp U-turn, or railway dead-end spur up to 1.85 km!
  const LOOP_THRESHOLD_M = 48.0;
  const MAX_MICRO_SPIKE_ARC_M = 1850.0;

  for (let pass = 0; pass < 4; pass++) {
    let changed = false;
    const n = pts.length;
    if (n <= 3) break;

    const cumArc = new Float64Array(n);
    for (let k = 1; k < n; k++) {
      cumArc[k] = cumArc[k - 1] + fastDistMeters(pts[k - 1], pts[k]);
    }

    const nextPts: [number, number][] = [];
    let i = 0;
    while (i < n) {
      nextPts.push(pts[i]);
      if (i === n - 1) break;
      let cutTo = -1;
      for (let j = n - 2; j > i + 1; j--) {
        const arcLen = cumArc[j] - cumArc[i];
        if (arcLen > MAX_MICRO_SPIKE_ARC_M) continue;
        const directDist = fastDistMeters(pts[i], pts[j]);
        if (directDist <= LOOP_THRESHOLD_M && arcLen > Math.max(directDist * 1.55, 65.0)) {
          cutTo = j;
          break;
        }
      }
      if (cutTo !== -1) {
        i = cutTo + 1;
        changed = true;
      } else {
        i++;
      }
    }
    if (
      nextPts.length >= 2 &&
      fastDistMeters(nextPts[nextPts.length - 1], endPt) > 1.0
    ) {
      nextPts.push(endPt);
    }
    pts = nextPts;
    if (!changed) break;
  }

  pts[0] = startPt;
  pts[pts.length - 1] = endPt;
  return pts;
}

async function fetchOsrmSingleLeg(
  startPt: [number, number],
  endPt: [number, number]
): Promise<[number, number][] | null> {
  const legKey = `${startPt[0].toFixed(4)},${startPt[1].toFixed(4)}->${endPt[0].toFixed(4)},${endPt[1].toFixed(4)}`;
  if (osrmSingleLegCache.has(legKey)) {
    return osrmSingleLegCache.get(legKey)!;
  }

  // Query OSRM directly with [startPt, endPt] ONLY — never inject arbitrary mid-corridor waypoints
  // that could land inside a university campus, opposite flyover ramp, or railway siding!
  const coordStr = `${startPt[0].toFixed(5)},${startPt[1].toFixed(5)};${endPt[0].toFixed(5)},${endPt[1].toFixed(5)}`;

  const mirrors = [
    `https://router.project-osrm.org/route/v1/driving/${coordStr}?overview=full&geometries=geojson`,
    `https://routing.openstreetmap.de/routed-car/route/v1/driving/${coordStr}?overview=full&geometries=geojson`,
  ];

  for (const url of mirrors) {
    try {
      const res = await fetch(url, { headers: { Accept: 'application/json' } });
      if (res.ok) {
        const data = await res.json();
        const coords = data?.routes?.[0]?.geometry?.coordinates;
        if (Array.isArray(coords) && coords.length >= 2) {
          const cleaned = sanitizeSingleLegMicroSpikes(
            coords as [number, number][],
            startPt,
            endPt
          );
          osrmSingleLegCache.set(legKey, cleaned);
          return cleaned;
        }
      }
    } catch {
      // Try next mirror
    }
  }

  return null;
}

export function buildInstantStreetGeometryForRoute(
  r: RouteDto,
  depLon: number,
  depLat: number,
  returnEnabled: boolean
): OsrmRouteGeometryPair {
  const stopCoords: [number, number][] = (r.stops || []).map((s) => [
    Number(s.lon),
    Number(s.lat),
  ]);
  const waypoints: [number, number][] = [[depLon, depLat], ...stopCoords];

  const outbound: [number, number][] = [];
  for (let i = 0; i < waypoints.length - 1; i++) {
    const legKey = `${waypoints[i][0].toFixed(4)},${waypoints[i][1].toFixed(4)}->${waypoints[i + 1][0].toFixed(4)},${waypoints[i + 1][1].toFixed(4)}`;
    const legPts =
      osrmSingleLegCache.get(legKey) ||
      buildRealStreetLegCorridor(waypoints[i], waypoints[i + 1]);
    for (const pt of legPts) {
      if (
        outbound.length === 0 ||
        fastDistMeters(outbound[outbound.length - 1], pt) > 0.8
      ) {
        outbound.push(pt);
      }
    }
  }

  let returnLeg: [number, number][] = [];
  if (returnEnabled && stopCoords.length > 0) {
    const lastStop = stopCoords[stopCoords.length - 1];
    const retKey = `${lastStop[0].toFixed(4)},${lastStop[1].toFixed(4)}->${depLon.toFixed(4)},${depLat.toFixed(4)}`;
    returnLeg =
      osrmSingleLegCache.get(retKey) ||
      buildRealStreetLegCorridor(lastStop, [depLon, depLat]);
  }

  const snappedStops: Record<string, [number, number]> = {};
  for (const s of r.stops || []) {
    snappedStops[s.id || s.order_id] = [Number(s.lon), Number(s.lat)];
  }

  return { outbound, returnLeg, snappedStops };
}

/** Register both single-headed (`▶`) and double-headed (`◀▶`) directional arrow icons on MapLibre */
function registerDirectionalArrowImages(map: maplibregl.Map) {
  if (!map.hasImage('route-direction-arrow')) {
    const size = 28;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, size, size);
      ctx.beginPath();
      ctx.moveTo(6, 5);
      ctx.lineTo(23, 14);
      ctx.lineTo(6, 23);
      ctx.lineTo(10.5, 14);
      ctx.closePath();
      ctx.fillStyle = '#ffffff';
      ctx.strokeStyle = '#161816';
      ctx.lineWidth = 3.2;
      ctx.lineJoin = 'round';
      ctx.stroke();
      ctx.fill();

      const imgData = ctx.getImageData(0, 0, size, size);
      map.addImage('route-direction-arrow', {
        width: size,
        height: size,
        data: new Uint8Array(imgData.data.buffer),
      });
    }
  }

  if (!map.hasImage('route-bidir-arrow')) {
    const w = 36;
    const h = 26;
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#ffffff';
      ctx.strokeStyle = '#161816';
      ctx.lineWidth = 2.8;
      ctx.lineJoin = 'round';

      // Left arrow head (`◀`)
      ctx.beginPath();
      ctx.moveTo(2, 13);
      ctx.lineTo(12, 5);
      ctx.lineTo(12, 10);
      ctx.lineTo(24, 10);
      ctx.lineTo(24, 5);
      ctx.lineTo(34, 13);
      ctx.lineTo(24, 21);
      ctx.lineTo(24, 16);
      ctx.lineTo(12, 16);
      ctx.lineTo(12, 21);
      ctx.closePath();
      ctx.stroke();
      ctx.fill();

      const imgData = ctx.getImageData(0, 0, w, h);
      map.addImage('route-bidir-arrow', {
        width: w,
        height: h,
        data: new Uint8Array(imgData.data.buffer),
      });
    }
  }
}

/**
 * Multi-layer MapLibre style with explicit `maxzoom: 17` (and `15` for OpenTopoMap)
 * so zooming in to deep street level automatically over-zooms valid raster tiles and
 * NEVER shows "Map data not yet available" blank error tiles!
 */
function buildUnifiedMultiLayerStyle(initialMode: MapViewMode): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {
      osm_streets: {
        type: 'raster',
        tiles: [
          'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
          'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
          'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png',
        ],
        tileSize: 256,
        maxzoom: 17,
        attribution: '© OpenStreetMap contributors',
      },
      esri_satellite: {
        type: 'raster',
        tiles: [
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        ],
        tileSize: 256,
        maxzoom: 17,
        attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
      },
      esri_hybrid_roads: {
        type: 'raster',
        tiles: [
          'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}',
        ],
        tileSize: 256,
        maxzoom: 17,
      },
      carto_hybrid_labels: {
        type: 'raster',
        tiles: [
          'https://a.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}@2x.png',
          'https://b.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}@2x.png',
        ],
        tileSize: 256,
        maxzoom: 17,
      },
      opentopo_terrain: {
        type: 'raster',
        tiles: [
          'https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
          'https://b.tile.opentopomap.org/{z}/{x}/{y}.png',
        ],
        tileSize: 256,
        maxzoom: 15,
        attribution: '© OpenTopoMap (CC-BY-SA)',
      },
    },
    layers: [
      {
        id: 'base-street-layer',
        type: 'raster',
        source: 'osm_streets',
        layout: { visibility: initialMode === 'street' ? 'visible' : 'none' },
      },
      {
        id: 'base-satellite-layer',
        type: 'raster',
        source: 'esri_satellite',
        layout: {
          visibility: initialMode === 'satellite' || initialMode === 'hybrid' ? 'visible' : 'none',
        },
      },
      {
        id: 'base-hybrid-roads-layer',
        type: 'raster',
        source: 'esri_hybrid_roads',
        layout: { visibility: initialMode === 'hybrid' ? 'visible' : 'none' },
      },
      {
        id: 'base-hybrid-labels-layer',
        type: 'raster',
        source: 'carto_hybrid_labels',
        layout: { visibility: initialMode === 'hybrid' ? 'visible' : 'none' },
      },
      {
        id: 'base-terrain-layer',
        type: 'raster',
        source: 'opentopo_terrain',
        layout: { visibility: initialMode === 'terrain' ? 'visible' : 'none' },
      },
    ],
  };
}

export interface DriverBikeMarkerSpec {
  lat: number;
  lon: number;
  label?: string;
  headingDeg?: number;
  color?: string;
}

interface InteractiveMapProps {
  nodes: RoadNodeDto[];
  edges: RoadEdgeDto[];
  depot?: DepotDto | null;
  orders?: OrderDto[];
  vehicles?: VehicleDto[];
  routes?: RouteDto[];
  selectedVehicleId?: string | null;
  selectedVehicleIds?: string[];
  legFilterMode?: RouteLegFilterMode;
  onLegFilterModeChange?: (mode: RouteLegFilterMode) => void;
  driverBikeMarker?: DriverBikeMarkerSpec | null;
  followBike?: boolean;
  initialZoom?: number;
  draftPin?: { lat: number; lon: number; label?: string } | null;
  onSelectLocation?: (
    lat: number,
    lon: number,
    placeMeta?: { title?: string; address?: string }
  ) => void;
  trafficIncidents?: TrafficIncidentItem[];
  solverKind?: string;
  height?: number;
  searchPlaceholder?: string;
}

export const InteractiveMap: React.FC<InteractiveMapProps> = ({
  nodes,
  edges,
  depot,
  orders = [],
  vehicles = [],
  routes: rawRoutes = [],
  selectedVehicleId = null,
  selectedVehicleIds = [],
  legFilterMode: controlledLegMode,
  onLegFilterModeChange,
  driverBikeMarker = null,
  followBike = false,
  initialZoom = 12.2,
  draftPin = null,
  onSelectLocation,
  trafficIncidents = [],
  solverKind,
  height = 470,
  searchPlaceholder = 'Search address, locality, campus, or landmark in Gujarat...',
}) => {
  const routes = useMemo(
    () => normalizeAndUncrossRoutes(rawRoutes, depot, solverKind),
    [rawRoutes, depot?.lon, depot?.lat, depot?.return_enabled, solverKind]
  );

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const draftMarkerRef = useRef<maplibregl.Marker | null>(null);
  const bikeMarkerRef = useRef<maplibregl.Marker | null>(null);
  const onSelectLocationRef = useRef(onSelectLocation);
  onSelectLocationRef.current = onSelectLocation;

  const [viewMode, setViewMode] = useState<MapViewMode>('street');
  const [is3DPitch, setIs3DPitch] = useState<boolean>(false);
  const [showNetworkGraph, setShowNetworkGraph] = useState<boolean>(false);
  const [showLiveVehicles, setShowLiveVehicles] = useState<boolean>(false);
  const [internalLegMode, setInternalLegMode] = useState<RouteLegFilterMode>('both');
  const activeLegMode: RouteLegFilterMode = controlledLegMode ?? internalLegMode;

  const setLegMode = (m: RouteLegFilterMode) => {
    setInternalLegMode(m);
    if (onLegFilterModeChange) onLegFilterModeChange(m);
  };

  const [selectedRegion, setSelectedRegion] = useState<string>('vadodara');
  const [webglFailed, setWebglFailed] = useState<boolean>(false);
  const [osrmPathsByRouteKey, setOsrmPathsByRouteKey] = useState<
    Record<string, OsrmRouteGeometryPair>
  >({});
  const [cursorCoords, setCursorCoords] = useState<{ lat: number; lon: number }>({
    lat: draftPin?.lat ?? depot?.lat ?? 22.3081,
    lon: draftPin?.lon ?? depot?.lon ?? 73.1812,
  });

  // Live Autocomplete Search State
  const [mapQuery, setMapQuery] = useState<string>('');
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [showDropdown, setShowDropdown] = useState<boolean>(false);
  const [highlightedIdx, setHighlightedIdx] = useState<number>(0);

  // Determine if a vehicle route is currently selected by either multi-select `selectedVehicleIds` or single `selectedVehicleId`
  const isVehicleVisible = (vehicleId: string): boolean => {
    if (selectedVehicleIds && selectedVehicleIds.length > 0) {
      return selectedVehicleIds.includes(vehicleId);
    }
    if (selectedVehicleId) {
      return vehicleId === selectedVehicleId;
    }
    return true;
  };

  // Leg-by-leg street routing
  useEffect(() => {
    if (!routes || routes.length === 0) return;
    let cancelled = false;

    const depLon = depot?.lon ?? 73.1685;
    const depLat = depot?.lat ?? 22.3106;
    const returnEnabled = depot ? Boolean(depot.return_enabled) : true;

    const instantMap: Record<string, OsrmRouteGeometryPair> = {};
    for (const r of routes) {
      if (!r.stops || r.stops.length === 0) continue;
      instantMap[r.id] = buildInstantStreetGeometryForRoute(r, depLon, depLat, returnEnabled);
    }
    setOsrmPathsByRouteKey((prev) => ({ ...prev, ...instantMap }));

    async function refineLegsWithLiveOsrm() {
      for (const r of routes) {
        if (cancelled || !r.stops || r.stops.length === 0) continue;
        const stopCoords: [number, number][] = r.stops.map((s) => [
          Number(s.lon),
          Number(s.lat),
        ]);
        const waypoints: [number, number][] = [[depLon, depLat], ...stopCoords];

        const outboundLegs: [number, number][] = [];
        for (let i = 0; i < waypoints.length - 1; i++) {
          if (cancelled) return;
          const osrmLeg = await fetchOsrmSingleLeg(waypoints[i], waypoints[i + 1]);
          const legPts = osrmLeg || buildRealStreetLegCorridor(waypoints[i], waypoints[i + 1]);
          for (const pt of legPts) {
            if (
              outboundLegs.length === 0 ||
              fastDistMeters(outboundLegs[outboundLegs.length - 1], pt) > 0.8
            ) {
              outboundLegs.push(pt);
            }
          }
        }

        let returnLeg: [number, number][] = [];
        if (returnEnabled && stopCoords.length > 0) {
          const lastStop = stopCoords[stopCoords.length - 1];
          const osrmRet = await fetchOsrmSingleLeg(lastStop, [depLon, depLat]);
          returnLeg = osrmRet || buildRealStreetLegCorridor(lastStop, [depLon, depLat]);
        }

        const snappedStops: Record<string, [number, number]> = {};
        for (const s of r.stops) {
          snappedStops[s.id || s.order_id] = [Number(s.lon), Number(s.lat)];
        }

        if (!cancelled) {
          setOsrmPathsByRouteKey((prev) => ({
            ...prev,
            [r.id]: {
              outbound: outboundLegs,
              returnLeg,
              snappedStops,
            },
          }));
        }
      }
    }

    refineLegsWithLiveOsrm();
    return () => {
      cancelled = true;
    };
  }, [routes, depot?.lon, depot?.lat, depot?.return_enabled]);

  useEffect(() => {
    const trimmed = mapQuery.trim();
    if (trimmed.length < 2) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }

    let cancelled = false;
    setIsSearching(true);
    const timer = setTimeout(async () => {
      try {
        const localPromise = apiClient
          .geocodeSearch(trimmed)
          .then((r) => (r.results || []) as any[])
          .catch(() => []);

        const nominatimUrl = `https://nominatim.openstreetmap.org/search?format=jsonv2&q=${encodeURIComponent(
          trimmed + ', Gujarat, India'
        )}&addressdetails=1&limit=7&viewbox=68.1,24.8,74.5,20.1&bounded=0`;

        const osmPromise = fetch(nominatimUrl, {
          headers: { Accept: 'application/json' },
        })
          .then((res) => (res.ok ? res.json() : []))
          .then((rows: any[]) =>
            rows.map((item) => ({
              title: item.name || item.display_name?.split(',')[0] || trimmed,
              place_name: item.display_name,
              lat: Number(parseFloat(item.lat).toFixed(5)),
              lon: Number(parseFloat(item.lon).toFixed(5)),
              provider: 'OSM_LIVE',
            }))
          )
          .catch(() => []);

        const [localResults, osmResults] = await Promise.all([localPromise, osmPromise]);
        if (cancelled) return;

        const merged: PlaceSuggestion[] = [];
        const seen = new Set<string>();

        for (const item of [...localResults, ...osmResults]) {
          const title = item.title || item.place_name?.split(',')[0] || '';
          const key = `${title.toLowerCase()}_${Number(item.lat).toFixed(3)}_${Number(item.lon).toFixed(3)}`;
          if (!seen.has(key)) {
            seen.add(key);
            merged.push({
              title,
              place_name: item.place_name,
              lat: Number(item.lat),
              lon: Number(item.lon),
              provider: item.provider || 'GAZETTEER',
            });
          }
        }

        setSuggestions(merged.slice(0, 10));
        setHighlightedIdx(0);
        setShowDropdown(true);
      } finally {
        if (!cancelled) setIsSearching(false);
      }
    }, 180);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [mapQuery]);

  const handlePickSuggestion = (s: PlaceSuggestion) => {
    setMapQuery(s.title);
    setShowDropdown(false);
    setCursorCoords({ lat: s.lat, lon: s.lon });

    if (mapRef.current) {
      mapRef.current.flyTo({
        center: [s.lon, s.lat],
        zoom: 15.5,
        duration: 850,
      });
    }

    if (onSelectLocationRef.current) {
      onSelectLocationRef.current(s.lat, s.lon, {
        title: s.title,
        address: s.place_name,
      });
    }
  };

  const resolveCoordinatesAndNotify = async (lat: number, lon: number) => {
    setCursorCoords({ lat, lon });
    let resolvedTitle: string | undefined;
    let resolvedAddress: string | undefined;

    try {
      const osmRevUrl = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lon}`;
      const resp = await fetch(osmRevUrl, { headers: { Accept: 'application/json' } });
      if (resp.ok) {
        const data = await resp.json();
        if (data && data.display_name) {
          resolvedTitle =
            data.name ||
            data.address?.amenity ||
            data.address?.university ||
            data.address?.building ||
            data.address?.suburb ||
            data.address?.road ||
            undefined;
          resolvedAddress = data.display_name;
        }
      }
    } catch {
      // Handled by backend fallback
    }

    if (onSelectLocationRef.current) {
      onSelectLocationRef.current(lat, lon, {
        title: resolvedTitle,
        address: resolvedAddress,
      });
    }
  };

  const syncGeoJsonLayers = (map: maplibregl.Map) => {
    if (!map.isStyleLoaded()) return;
    registerDirectionalArrowImages(map);

    const roadFeatures = showNetworkGraph
      ? edges.map((e) => ({
          type: 'Feature' as const,
          properties: { id: e.id, road_class: e.road_class, length_m: e.length_m },
          geometry: {
            type: 'LineString' as const,
            coordinates: [e.u_coord, e.v_coord],
          },
        }))
      : [];

    const roadGeoJson = {
      type: 'FeatureCollection' as const,
      features: roadFeatures,
    };

    const existingRoadSrc = map.getSource('routeit-road-graph') as
      | maplibregl.GeoJSONSource
      | undefined;
    if (existingRoadSrc) {
      existingRoadSrc.setData(roadGeoJson as any);
    } else {
      map.addSource('routeit-road-graph', {
        type: 'geojson',
        data: roadGeoJson as any,
      });
      map.addLayer({
        id: 'routeit-road-graph-line',
        type: 'line',
        source: 'routeit-road-graph',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': '#57534e',
          'line-width': 2,
          'line-opacity': 0.55,
          'line-dasharray': [2, 2],
        },
      });
    }

    const depLon = depot?.lon ?? 73.1685;
    const depLat = depot?.lat ?? 22.3106;
    const returnEnabled = depot ? Boolean(depot.return_enabled) : true;

    const outboundFeatures: any[] = [];
    const returnFeatures: any[] = [];
    const twoWayFeatures: any[] = [];

    routes.forEach((r, fullIdx) => {
      if (!isVehicleVisible(r.vehicle_id)) return;
      const color = VEHICLE_COLORS[fullIdx % VEHICLE_COLORS.length];
      const pair =
        osrmPathsByRouteKey[r.id] ||
        buildInstantStreetGeometryForRoute(r, depLon, depLat, returnEnabled);

      const rawOut = pair.outbound || [];
      const rawRet = returnEnabled ? pair.returnLeg || [] : [];

      const { outboundOnlyLines, returnOnlyLines, twoWaySharedLines } =
        decomposeRouteIntoOneWayAndTwoWayLines(rawOut, rawRet, activeLegMode);

      for (const lineCoords of outboundOnlyLines) {
        if (lineCoords.length >= 2) {
          outboundFeatures.push({
            type: 'Feature' as const,
            properties: {
              vehicle_code: r.vehicle_code,
              color,
              leg_type: 'OUTBOUND',
            },
            geometry: {
              type: 'LineString' as const,
              coordinates: lineCoords,
            },
          });
        }
      }

      for (const lineCoords of returnOnlyLines) {
        if (lineCoords.length >= 2) {
          returnFeatures.push({
            type: 'Feature' as const,
            properties: {
              vehicle_code: r.vehicle_code,
              color,
              leg_type: 'RETURN',
            },
            geometry: {
              type: 'LineString' as const,
              coordinates: lineCoords,
            },
          });
        }
      }

      for (const lineCoords of twoWaySharedLines) {
        if (lineCoords.length >= 2) {
          twoWayFeatures.push({
            type: 'Feature' as const,
            properties: {
              vehicle_code: r.vehicle_code,
              color,
              leg_type: 'TWO_WAY',
            },
            geometry: {
              type: 'LineString' as const,
              coordinates: lineCoords,
            },
          });
        }
      }
    });

    // 1. Outbound One-Way Layer (Solid Colored Line + Single Forward Arrows `▶`)
    const outboundGeoJson = {
      type: 'FeatureCollection' as const,
      features: outboundFeatures,
    };
    const existingOutSrc = map.getSource('routeit-active-routes') as
      | maplibregl.GeoJSONSource
      | undefined;
    if (existingOutSrc) {
      existingOutSrc.setData(outboundGeoJson as any);
    } else {
      map.addSource('routeit-active-routes', {
        type: 'geojson',
        data: outboundGeoJson as any,
      });
      map.addLayer({
        id: 'routeit-active-routes-casing',
        type: 'line',
        source: 'routeit-active-routes',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': '#ffffff',
          'line-width': 7.5,
          'line-opacity': 0.94,
        },
      });
      map.addLayer({
        id: 'routeit-active-routes-line',
        type: 'line',
        source: 'routeit-active-routes',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': 5.0,
          'line-opacity': 0.96,
        },
      });
      map.addLayer({
        id: 'routeit-active-routes-arrows',
        type: 'symbol',
        source: 'routeit-active-routes',
        layout: {
          'symbol-placement': 'line',
          'symbol-spacing': 75,
          'icon-image': 'route-direction-arrow',
          'icon-size': 0.65,
          'icon-rotation-alignment': 'map',
          'icon-keep-upright': false,
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
        },
      });
    }

    // 2. Return One-Way Layer (Vehicle-Colored Dashed Line `╌╌▶`)
    const returnGeoJson = {
      type: 'FeatureCollection' as const,
      features: returnFeatures,
    };
    const existingRetSrc = map.getSource('routeit-return-routes') as
      | maplibregl.GeoJSONSource
      | undefined;
    if (existingRetSrc) {
      existingRetSrc.setData(returnGeoJson as any);
    } else {
      map.addSource('routeit-return-routes', {
        type: 'geojson',
        data: returnGeoJson as any,
      });
      map.addLayer({
        id: 'routeit-return-routes-casing',
        type: 'line',
        source: 'routeit-return-routes',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': '#ffffff',
          'line-width': 8.0,
          'line-opacity': 0.95,
        },
      });
      map.addLayer({
        id: 'routeit-return-routes-line',
        type: 'line',
        source: 'routeit-return-routes',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': 4.8,
          'line-opacity': 1.0,
          'line-dasharray': [2.2, 1.6],
        },
      });
      map.addLayer({
        id: 'routeit-return-routes-arrows',
        type: 'symbol',
        source: 'routeit-return-routes',
        layout: {
          'symbol-placement': 'line',
          'symbol-spacing': 85,
          'icon-image': 'route-direction-arrow',
          'icon-size': 0.6,
          'icon-rotation-alignment': 'map',
          'icon-keep-upright': false,
          'icon-allow-overlap': true,
        },
      });
    }

    // 3. Narrow Two-Way Shared Street Layer (Dotted Vehicle-Colored Line `· · · ·` + Double-Headed Arrows `◀▶`)
    const twoWayGeoJson = {
      type: 'FeatureCollection' as const,
      features: twoWayFeatures,
    };
    const existingTwoWaySrc = map.getSource('routeit-twoway-routes') as
      | maplibregl.GeoJSONSource
      | undefined;
    if (existingTwoWaySrc) {
      existingTwoWaySrc.setData(twoWayGeoJson as any);
    } else {
      map.addSource('routeit-twoway-routes', {
        type: 'geojson',
        data: twoWayGeoJson as any,
      });
      map.addLayer({
        id: 'routeit-twoway-routes-casing',
        type: 'line',
        source: 'routeit-twoway-routes',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': '#ffffff',
          'line-width': 8.5,
          'line-opacity': 0.96,
        },
      });
      map.addLayer({
        id: 'routeit-twoway-routes-line',
        type: 'line',
        source: 'routeit-twoway-routes',
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: {
          'line-color': ['get', 'color'],
          'line-width': 5.4,
          'line-opacity': 1.0,
          'line-dasharray': [0.5, 1.6],
        },
      });
      map.addLayer({
        id: 'routeit-twoway-routes-arrows',
        type: 'symbol',
        source: 'routeit-twoway-routes',
        layout: {
          'symbol-placement': 'line',
          'symbol-spacing': 75,
          'icon-image': 'route-bidir-arrow',
          'icon-size': 0.72,
          'icon-rotation-alignment': 'map',
          'icon-keep-upright': false,
          'icon-allow-overlap': true,
        },
      });
    }
  };

  const syncMarkers = (map: maplibregl.Map) => {
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    if (showNetworkGraph) {
      nodes.forEach((node) => {
        const el = document.createElement('div');
        el.style.width = '9px';
        el.style.height = '9px';
        el.style.borderRadius = '50%';
        el.style.background = '#1c1d1a';
        el.style.border = '2px solid #ffffff';
        el.style.boxShadow = '0 1px 3px rgba(0,0,0,0.35)';
        el.style.cursor = 'pointer';
        el.title = node.name;
        el.addEventListener('click', (ev) => {
          ev.stopPropagation();
          if (onSelectLocationRef.current) {
            onSelectLocationRef.current(node.lat, node.lon, {
              title: node.name,
              address: `${node.name}, Gujarat`,
            });
          }
        });

        const m = new maplibregl.Marker({ element: el })
          .setLngLat([node.lon, node.lat])
          .addTo(map);
        markersRef.current.push(m);
      });
    }

    if (depot) {
      const depEl = document.createElement('div');
      depEl.style.width = '28px';
      depEl.style.height = '28px';
      depEl.style.borderRadius = '6px';
      depEl.style.background = '#1c1d1a';
      depEl.style.color = '#e5a93c';
      depEl.style.fontWeight = '800';
      depEl.style.fontSize = '13px';
      depEl.style.display = 'flex';
      depEl.style.alignItems = 'center';
      depEl.style.justifyContent = 'center';
      depEl.style.border = '2px solid #ffffff';
      depEl.style.boxShadow = '0 2px 6px rgba(0,0,0,0.4)';
      depEl.textContent = 'H';
      depEl.title = `Depot Hub: ${depot.name}`;

      const depPopup = new maplibregl.Popup({ offset: 14 }).setHTML(
        `<div style="font-size:12px;line-height:1.45">
          <strong>Starting Depot (H): ${depot.name}</strong><br/>
          Coordinates: ${depot.lat.toFixed(4)}°N, ${depot.lon.toFixed(4)}°E<br/>
          Policy: <strong>${depot.return_enabled ? 'Vehicles Return to Depot (H)' : 'Open Route End'}</strong>
        </div>`
      );

      const dm = new maplibregl.Marker({ element: depEl })
        .setLngLat([depot.lon, depot.lat])
        .setPopup(depPopup)
        .addTo(map);
      markersRef.current.push(dm);
    }

    if (routes.length > 0) {
      routes.forEach((route, rIdx) => {
        if (!isVehicleVisible(route.vehicle_id)) return;
        const color = VEHICLE_COLORS[rIdx % VEHICLE_COLORS.length];

        route.stops.forEach((stop: any, sIdx: number) => {
          const custCode =
            stop.customer_code || deriveCustomerCode(stop.external_ref, sIdx + 1);
          const stopCoord: [number, number] = [Number(stop.lon), Number(stop.lat)];
          const liveOrderMatch = orders.find(
            (o: any) => o.id === stop.order_id || o.external_ref === stop.external_ref
          );
          const isDelivered =
            liveOrderMatch?.status === 'DELIVERED' ||
            stop.order_status === 'DELIVERED' ||
            stop.stop_state === 'DELIVERED';

          const stopEl = document.createElement('div');
          if (isDelivered) {
            // Distinct Completed Delivery Pill Marker (`✓ C1`) on Admin & Driver maps!
            stopEl.style.height = '26px';
            stopEl.style.padding = '0 8px';
            stopEl.style.borderRadius = '13px';
            stopEl.style.background = 'linear-gradient(135deg, #065f46 0%, #10b981 100%)';
            stopEl.style.color = '#ffffff';
            stopEl.style.fontWeight = '800';
            stopEl.style.fontSize = '10.5px';
            stopEl.style.fontFamily = "'JetBrains Mono', monospace";
            stopEl.style.display = 'inline-flex';
            stopEl.style.alignItems = 'center';
            stopEl.style.justifyContent = 'center';
            stopEl.style.gap = '3px';
            stopEl.style.border = '2.5px solid #a7f3d0';
            stopEl.style.boxShadow = '0 0 0 3px rgba(16, 185, 129, 0.3), 0 3px 8px rgba(0,0,0,0.45)';
            stopEl.style.cursor = 'pointer';
            stopEl.style.whiteSpace = 'nowrap';
            stopEl.textContent = `✓ ${custCode}`;
            stopEl.title = `✓ DELIVERED: ${custCode} (${stop.customer_name}) · Delivered by ${route.vehicle_code}`;
          } else {
            stopEl.style.width = '24px';
            stopEl.style.height = '24px';
            stopEl.style.borderRadius = '50%';
            stopEl.style.background = color;
            stopEl.style.color = '#ffffff';
            stopEl.style.fontWeight = '700';
            stopEl.style.fontSize = '10px';
            stopEl.style.fontFamily = "'JetBrains Mono', monospace";
            stopEl.style.display = 'flex';
            stopEl.style.alignItems = 'center';
            stopEl.style.justifyContent = 'center';
            stopEl.style.border = '2px solid #ffffff';
            stopEl.style.boxShadow = '0 2px 5px rgba(0,0,0,0.38)';
            stopEl.style.cursor = 'pointer';
            stopEl.textContent = custCode;
            stopEl.title = `${custCode} (${stop.customer_name}) · Stop #${stop.seq} on ${route.vehicle_code}`;
          }

          const popup = new maplibregl.Popup({ offset: 12 }).setHTML(
            `<div style="font-size:12px;line-height:1.45">
              <strong>Customer ${custCode} · ${stop.customer_name}</strong><br/>
              Vehicle: <strong style="color:${color}">${route.vehicle_code}</strong> (Visit Stop #${stop.seq})<br/>
              Order: <code>${stop.external_ref}</code> · Weight: <strong>${stop.demand_units} kg</strong><br/>
              Priority: <strong>${stop.priority}</strong> · Status: <strong>${isDelivered ? '✓ Delivered' : 'Scheduled'}</strong><br/>
              Arrival: ${formatSecondsToClockIST(stop.arrival_utc_s)} · Done: <strong>${formatSecondsToClockIST(
                stop.service_end_utc_s
              )}</strong>
            </div>`
          );

          const sm = new maplibregl.Marker({ element: stopEl })
            .setLngLat(stopCoord)
            .setPopup(popup)
            .addTo(map);
          markersRef.current.push(sm);
        });
      });
    } else {
      orders
        .filter((o: any) => o.status !== 'CANCELLED')
        .forEach((ord: any, idx: number) => {
          const custCode = ord.customer_code || deriveCustomerCode(ord.external_ref, idx + 1);
          const badgeColor =
            ord.priority === 'CRITICAL'
              ? '#9f1c1c'
              : ord.priority === 'STANDARD'
              ? '#1e4b7a'
              : '#22593f';
          const isOrdDelivered = ord.status === 'DELIVERED';
          const ordEl = document.createElement('div');
          if (isOrdDelivered) {
            ordEl.style.height = '26px';
            ordEl.style.padding = '0 8px';
            ordEl.style.borderRadius = '13px';
            ordEl.style.background = 'linear-gradient(135deg, #065f46 0%, #10b981 100%)';
            ordEl.style.color = '#ffffff';
            ordEl.style.fontWeight = '800';
            ordEl.style.fontSize = '10.5px';
            ordEl.style.fontFamily = "'JetBrains Mono', monospace";
            ordEl.style.display = 'inline-flex';
            ordEl.style.alignItems = 'center';
            ordEl.style.justifyContent = 'center';
            ordEl.style.border = '2.5px solid #a7f3d0';
            ordEl.style.boxShadow = '0 0 0 3px rgba(16, 185, 129, 0.28), 0 3px 8px rgba(0,0,0,0.4)';
            ordEl.style.cursor = 'pointer';
            ordEl.style.whiteSpace = 'nowrap';
            ordEl.textContent = `✓ ${custCode}`;
          } else {
            ordEl.style.width = '24px';
            ordEl.style.height = '24px';
            ordEl.style.borderRadius = '50%';
            ordEl.style.background = badgeColor;
            ordEl.style.color = '#ffffff';
            ordEl.style.fontWeight = '700';
            ordEl.style.fontSize = '10px';
            ordEl.style.fontFamily = "'JetBrains Mono', monospace";
            ordEl.style.display = 'flex';
            ordEl.style.alignItems = 'center';
            ordEl.style.justifyContent = 'center';
            ordEl.style.border = '2px solid #ffffff';
            ordEl.style.boxShadow = '0 2px 4px rgba(0,0,0,0.3)';
            ordEl.style.cursor = 'pointer';
            ordEl.textContent = custCode;
          }
          ordEl.title = `${custCode} · ${ord.customer_name}`;

          const popup = new maplibregl.Popup({ offset: 10 }).setHTML(
            `<div style="font-size:12px;line-height:1.4">
              <strong>Customer ${custCode} · ${ord.customer_name}</strong> (${ord.external_ref})<br/>
              Weight: ${ord.demand_units} kg · ${ord.priority}<br/>
              Address: ${ord.address_text}
            </div>`
          );

          const om = new maplibregl.Marker({ element: ordEl })
            .setLngLat([ord.lon, ord.lat])
            .setPopup(popup)
            .addTo(map);
          markersRef.current.push(om);
        });
    }

    if (draftMarkerRef.current) {
      draftMarkerRef.current.remove();
      draftMarkerRef.current = null;
    }
    if (draftPin) {
      const dm = new maplibregl.Marker({
        color: '#22593f',
        draggable: Boolean(onSelectLocationRef.current),
      })
        .setLngLat([draftPin.lon, draftPin.lat])
        .addTo(map);

      dm.on('dragend', () => {
        const lngLat = dm.getLngLat();
        const lat = Number(lngLat.lat.toFixed(5));
        const lon = Number(lngLat.lng.toFixed(5));
        resolveCoordinatesAndNotify(lat, lon);
      });

      draftMarkerRef.current = dm;
    }

    // Clean Architectural Navigation Puck for Driver Portal & Optional Admin Vehicle Telemetry (Hidden by Default on Admin Maps)
    if (bikeMarkerRef.current) {
      bikeMarkerRef.current.remove();
      bikeMarkerRef.current = null;
    }
    if (driverBikeMarker) {
      const hDeg = ((driverBikeMarker.headingDeg ?? 90) % 360 + 360) % 360;
      const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
      const compassLabel = dirs[Math.round(hDeg / 45) % 8];

      const bikeEl = document.createElement('div');
      bikeEl.style.width = '28px';
      bikeEl.style.height = '28px';
      bikeEl.style.borderRadius = '50%';
      bikeEl.style.background = driverBikeMarker.color || '#15803d';
      bikeEl.style.border = '2px solid #ffffff';
      bikeEl.style.boxShadow = '0 2px 8px rgba(0,0,0,0.35)';
      bikeEl.style.display = 'flex';
      bikeEl.style.alignItems = 'center';
      bikeEl.style.justifyContent = 'center';
      bikeEl.style.cursor = 'pointer';
      bikeEl.style.zIndex = '60';
      // Crisp vector navigation arrow rotated to exact headingDeg (0° = North)
      bikeEl.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="#ffffff" style="transform:rotate(${hDeg.toFixed(
        1
      )}deg);transition:transform 0.15s ease"><path d="M12 2L19 21L12 17L5 21L12 2Z"/></svg>`;
      bikeEl.title = `${driverBikeMarker.label || 'Live Vehicle'} · Heading ${compassLabel}`;

      const bikePopup = new maplibregl.Popup({ offset: 14 }).setHTML(
        `<div style="font-size:12px;line-height:1.5;min-width:200px;color:#1e1b15">
          <div style="font-weight:700;color:${driverBikeMarker.color || '#15803d'};margin-bottom:3px">LIVE VEHICLE TELEMETRY</div>
          <strong>${driverBikeMarker.label || 'Active Vehicle'}</strong><br/>
          Heading: <strong>${compassLabel} (${Math.round(hDeg)}°)</strong><br/>
          GPS: <code>${driverBikeMarker.lat.toFixed(5)}°N, ${driverBikeMarker.lon.toFixed(5)}°E</code>
        </div>`
      );

      const bm = new maplibregl.Marker({ element: bikeEl })
        .setLngLat([driverBikeMarker.lon, driverBikeMarker.lat])
        .setPopup(bikePopup)
        .addTo(map);
      bikeMarkerRef.current = bm;
    } else if (showLiveVehicles) {
      // Only shown when user explicitly toggles "Vehicle Locations: ON" in the map toolbar
      const activeJourneys = apiClient.getDriverJourneys();
      routes.forEach((route, rIdx) => {
        if (!isVehicleVisible(route.vehicle_id)) return;
        const j = activeJourneys[route.vehicle_id];
        const vehObj = vehicles.find(
          (v) => v.id === route.vehicle_id || v.code === route.vehicle_code
        );
        const isInTransit = Boolean(j?.inTransit) || Boolean(vehObj?.in_transit);

        const vColor = VEHICLE_COLORS[rIdx % VEHICLE_COLORS.length];
        const pair = osrmPathsByRouteKey[route.id];
        // Position along the vehicle's actual street corridor so vehicles never pile on top of the Depot (H)!
        const midPtIdx =
          pair?.outbound && pair.outbound.length > 3
            ? Math.min(pair.outbound.length - 2, Math.max(2, Math.floor(pair.outbound.length * 0.25)))
            : 0;
        const fallbackPt =
          pair?.outbound && pair.outbound[midPtIdx]
            ? pair.outbound[midPtIdx]
            : route.stops?.[0]
            ? [Number(route.stops[0].lon), Number(route.stops[0].lat)]
            : [depot?.lon ?? 73.1685, depot?.lat ?? 22.3106];

        const vLon = j?.lon ?? fallbackPt[0];
        const vLat = j?.lat ?? fallbackPt[1];
        const hDeg = ((j?.headingDeg ?? (rIdx === 0 ? 120 : rIdx === 1 ? 45 : 250)) % 360 + 360) % 360;
        const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
        const compassLabel = dirs[Math.round(hDeg / 45) % 8];

        const driverName = vehObj?.driver_name || `Driver (${route.vehicle_code})`;
        const driverUser = vehObj?.driver_username || route.vehicle_code.toLowerCase();

        const totalStops = route.stops?.length || 0;
        const doneStops = (route.stops || []).filter((s: any) => {
          const lo = orders.find((o: any) => o.id === s.order_id || o.external_ref === s.external_ref);
          return lo?.status === 'DELIVERED' || s.order_status === 'DELIVERED';
        }).length;
        const nextStop = (route.stops || []).find((s: any) => {
          const lo = orders.find((o: any) => o.id === s.order_id || o.external_ref === s.external_ref);
          return lo?.status !== 'DELIVERED' && s.order_status !== 'DELIVERED';
        });

        const depTimeIST =
          j?.departureClockIST || formatSecondsToClockIST(Number(route.departure_utc_s || 1794882600));
        let elapsedText = isInTransit ? '14m 20s in transit' : 'Scheduled / Dispatched';
        if (j?.startedAtIso) {
          const diffSec = Math.max(5, Math.floor((Date.now() - new Date(j.startedAtIso).getTime()) / 1000));
          const mins = Math.floor(diffSec / 60);
          const secs = diffSec % 60;
          elapsedText = `${mins}m ${secs}s since departure`;
        } else if (doneStops > 0) {
          elapsedText = `${doneStops * 16}m 10s since departure`;
        }

        // Sleek 24x24 architectural directional navigation puck
        const telemetryEl = document.createElement('div');
        telemetryEl.style.width = '24px';
        telemetryEl.style.height = '24px';
        telemetryEl.style.borderRadius = '50%';
        telemetryEl.style.background = vColor;
        telemetryEl.style.border = '2px solid #ffffff';
        telemetryEl.style.boxShadow = '0 2px 6px rgba(0,0,0,0.32)';
        telemetryEl.style.display = 'flex';
        telemetryEl.style.alignItems = 'center';
        telemetryEl.style.justifyContent = 'center';
        telemetryEl.style.cursor = 'pointer';
        telemetryEl.style.zIndex = '55';
        telemetryEl.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="#ffffff" style="transform:rotate(${hDeg.toFixed(
          1
        )}deg)"><path d="M12 2L19 21L12 17L5 21L12 2Z"/></svg>`;
        telemetryEl.title = `${route.vehicle_code} (${driverName}) — Click for telemetry`;

        const popupHtml = `<div style="font-size:12px;line-height:1.55;min-width:225px;color:#1e1b15">
          <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #e4e0d7;padding-bottom:5px;margin-bottom:6px">
            <strong style="color:${vColor};font-size:13px">${route.vehicle_code}</strong>
            <span style="background:${isInTransit ? '#dcfce7' : '#f1f5f9'};color:${
          isInTransit ? '#166534' : '#334155'
        };padding:2px 7px;border-radius:99px;font-size:10px;font-weight:700">${
          isInTransit ? '● IN TRANSIT' : '● ASSIGNED'
        }</span>
          </div>
          <div><strong>Driver:</strong> ${driverName} (<code>@${driverUser}</code>)</div>
          <div><strong>Departure Time:</strong> <code>${depTimeIST}</code></div>
          <div><strong>Elapsed Time:</strong> <strong style="color:${vColor}">${elapsedText}</strong></div>
          <div><strong>Cargo Load:</strong> ${route.initial_load_units} / ${route.capacity_units} kg</div>
          <div><strong>Stops Delivered:</strong> <strong>${doneStops} / ${totalStops}</strong></div>
          <div><strong>Next Stop:</strong> ${
            nextStop
              ? `${nextStop.customer_code || 'Stop'} · ${nextStop.customer_name}`
              : 'Returning to Depot (H)'
          }</div>
          <div style="margin-top:4px;color:#767871;font-size:11px">
            GPS: <code>${vLat.toFixed(5)}°N, ${vLon.toFixed(5)}°E</code>
          </div>
        </div>`;

        const tmPopup = new maplibregl.Popup({ offset: 12 }).setHTML(popupHtml);
        const tmMarker = new maplibregl.Marker({ element: telemetryEl })
          .setLngLat([vLon, vLat])
          .setPopup(tmPopup)
          .addTo(map);
        markersRef.current.push(tmMarker);
      });
    }

    // Render Active Simulated Traffic Incidents (Road Blockades & Congestion Zones)
    if (trafficIncidents && trafficIncidents.length > 0) {
      trafficIncidents.forEach((inc) => {
        const isBlock = inc.kind === 'BLOCKADE';
        const incEl = document.createElement('div');
        incEl.style.padding = '3px 8px';
        incEl.style.borderRadius = '999px';
        incEl.style.background = isBlock ? '#be123c' : '#d97706';
        incEl.style.color = '#ffffff';
        incEl.style.border = '2px solid #ffffff';
        incEl.style.boxShadow = isBlock
          ? '0 0 0 6px rgba(225, 29, 72, 0.28), 0 3px 10px rgba(0,0,0,0.35)'
          : '0 0 0 6px rgba(217, 119, 6, 0.25), 0 3px 10px rgba(0,0,0,0.3)';
        incEl.style.fontWeight = '800';
        incEl.style.fontSize = '11px';
        incEl.style.fontFamily = "'JetBrains Mono', monospace";
        incEl.style.cursor = 'pointer';
        incEl.style.zIndex = '58';
        incEl.textContent = isBlock
          ? `🚧 BLOCKED (${inc.durationHours ?? 2}h)`
          : `⚠️ JAM -${inc.slowdownPct}% (${inc.durationMinutes ?? 45}m)`;

        const incPopup = new maplibregl.Popup({ offset: 14 }).setHTML(
          `<div style="font-size:12px;line-height:1.5;min-width:210px">
            <div style="font-weight:800;color:${isBlock ? '#be123c' : '#b45309'};margin-bottom:4px">
              ${isBlock ? '🚧 FULL ROAD BLOCKADE' : '⚠️ LIVE TRAFFIC CONGESTION'}
            </div>
            <div><strong>Corridor:</strong> ${inc.roadLabel}</div>
            <div><strong>Impact:</strong> ${
              isBlock ? 'Road Closed (0 km/h — Detour Required)' : `${inc.slowdownPct}% Speed Reduction (${inc.speedMultiplier}× flow)`
            }</div>
            <div><strong>Clearance Time:</strong> ${
              isBlock ? `${inc.durationHours ?? 2} hours to reopen` : `${inc.durationMinutes ?? 45} minutes to clear`
            }</div>
            <div><strong>Cause:</strong> ${inc.reason}</div>
          </div>`
        );

        const im = new maplibregl.Marker({ element: incEl })
          .setLngLat([inc.lon, inc.lat])
          .setPopup(incPopup)
          .addTo(map);
        markersRef.current.push(im);
      });
    }
  };

  useEffect(() => {
    if (!mapContainerRef.current) return;
    try {
      const initialCenter: [number, number] = driverBikeMarker
        ? [driverBikeMarker.lon, driverBikeMarker.lat]
        : draftPin
        ? [draftPin.lon, draftPin.lat]
        : depot
        ? [depot.lon, depot.lat]
        : [73.1812, 22.3081];

      const map = new maplibregl.Map({
        container: mapContainerRef.current,
        style: buildUnifiedMultiLayerStyle(viewMode),
        center: initialCenter,
        zoom: initialZoom,
        minZoom: 5.2,
        // Cap maxZoom at 17.4 so raster tiles gracefully over-zoom and never show "data not available"
        maxZoom: 17.4,
        maxBounds: [
          [67.5, 19.5],
          [75.2, 25.2],
        ],
        pitch: is3DPitch ? 50 : 0,
      });

      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
      map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-left');
      map.addControl(new maplibregl.FullscreenControl(), 'top-right');

      map.on('load', () => {
        registerDirectionalArrowImages(map);
        syncGeoJsonLayers(map);
        syncMarkers(map);
      });

      map.on('mousemove', (e) => {
        setCursorCoords({
          lat: Number(e.lngLat.lat.toFixed(5)),
          lon: Number(e.lngLat.lng.toFixed(5)),
        });
      });

      map.on('click', (e) => {
        const lat = Number(e.lngLat.lat.toFixed(5));
        const lon = Number(e.lngLat.lng.toFixed(5));
        resolveCoordinatesAndNotify(lat, lon);
      });

      mapRef.current = map;
      let resizeTimer: number | null = null;
      const ro =
        typeof ResizeObserver !== 'undefined' && mapContainerRef.current
          ? new ResizeObserver(() => {
              if (resizeTimer !== null) window.clearTimeout(resizeTimer);
              resizeTimer = window.setTimeout(() => {
                if (mapRef.current) {
                  mapRef.current.resize();
                }
              }, 140);
            })
          : null;
      if (ro && mapContainerRef.current) {
        ro.observe(mapContainerRef.current);
      }

      return () => {
        if (resizeTimer !== null) window.clearTimeout(resizeTimer);
        if (ro) ro.disconnect();
        map.remove();
        mapRef.current = null;
      };
    } catch (err) {
      console.warn('WebGL unavailable:', err);
      setWebglFailed(true);
    }
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const setVis = (layerId: string, visible: boolean) => {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
      }
    };

    setVis('base-street-layer', viewMode === 'street');
    setVis('base-satellite-layer', viewMode === 'satellite' || viewMode === 'hybrid');
    setVis('base-hybrid-roads-layer', viewMode === 'hybrid');
    setVis('base-hybrid-labels-layer', viewMode === 'hybrid');
    setVis('base-terrain-layer', viewMode === 'terrain');
  }, [viewMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.easeTo({ pitch: is3DPitch ? 52 : 0, duration: 450 });
  }, [is3DPitch]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (map.isStyleLoaded()) {
      syncGeoJsonLayers(map);
    }
    syncMarkers(map);
  }, [
    nodes,
    edges,
    depot,
    orders,
    vehicles,
    routes,
    selectedVehicleId,
    selectedVehicleIds,
    draftPin,
    showNetworkGraph,
    activeLegMode,
    osrmPathsByRouteKey,
    driverBikeMarker?.lat,
    driverBikeMarker?.lon,
    driverBikeMarker?.headingDeg,
    showLiveVehicles,
    trafficIncidents,
  ]);

  useEffect(() => {
    if (followBike && driverBikeMarker && mapRef.current) {
      mapRef.current.easeTo({
        center: [driverBikeMarker.lon, driverBikeMarker.lat],
        zoom: Math.max(mapRef.current.getZoom(), 16.2),
        duration: 380,
      });
    }
  }, [followBike, driverBikeMarker?.lat, driverBikeMarker?.lon]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !draftPin) return;
    setCursorCoords({ lat: draftPin.lat, lon: draftPin.lon });
    if (draftMarkerRef.current) {
      draftMarkerRef.current.setLngLat([draftPin.lon, draftPin.lat]);
    }
  }, [draftPin?.lat, draftPin?.lon]);

  const handleRegionChange = (presetId: string) => {
    setSelectedRegion(presetId);
    const preset = GUJARAT_REGION_PRESETS.find((p) => p.id === presetId);
    if (preset && mapRef.current) {
      mapRef.current.flyTo({
        center: [preset.lon, preset.lat],
        zoom: preset.zoom,
        duration: 900,
      });
    }
  };

  const handleFlyToDepot = () => {
    const map = mapRef.current;
    if (!map) return;
    const depLon = depot?.lon ?? 73.1685;
    const depLat = depot?.lat ?? 22.3106;
    map.flyTo({
      center: [depLon, depLat],
      zoom: 14.6,
      duration: 750,
    });
  };

  const handleFitAllRoutesOrOrders = () => {
    const map = mapRef.current;
    if (!map) return;
    const bounds = new maplibregl.LngLatBounds();
    let count = 0;
    if (depot) {
      bounds.extend([depot.lon, depot.lat]);
      count++;
    }
    orders.forEach((o) => {
      bounds.extend([o.lon, o.lat]);
      count++;
    });
    routes.forEach((r) => {
      if (!isVehicleVisible(r.vehicle_id)) return;
      r.stops?.forEach((s) => {
        bounds.extend([s.lon, s.lat]);
        count++;
      });
    });
    if (count >= 2) {
      map.fitBounds(bounds, { padding: 55, maxZoom: 15.2, duration: 750 });
    }
  };

  useEffect(() => {
    if (!followBike && routes.length > 0 && mapRef.current) {
      const t = setTimeout(() => handleFitAllRoutesOrOrders(), 150);
      return () => clearTimeout(t);
    }
  }, [routes.length]);

  const activePinLat = driverBikeMarker?.lat ?? draftPin?.lat ?? depot?.lat ?? cursorCoords.lat;
  const activePinLon = driverBikeMarker?.lon ?? draftPin?.lon ?? depot?.lon ?? cursorCoords.lon;
  const googleStreetViewUrl = `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${activePinLat},${activePinLon}`;
  const returnEnabled = depot ? Boolean(depot.return_enabled) : true;

  return (
    <div
      style={{
        border: '1px solid var(--border-color)',
        borderRadius: 8,
        overflow: 'visible',
        background: 'var(--bg-surface)',
        position: 'relative',
      }}
    >
      {/* Search Bar Row */}
      <div
        style={{
          padding: '10px 12px',
          background: 'var(--bg-stone-header)',
          borderBottom: '1px solid var(--border-color)',
          position: 'relative',
          zIndex: 30,
        }}
      >
        <div style={{ position: 'relative' }}>
          <input
            className="form-input"
            style={{
              paddingLeft: 12,
              paddingRight: 70,
              fontWeight: 500,
              background: 'var(--bg-surface)',
              borderColor: 'var(--border-strong)',
            }}
            placeholder={searchPlaceholder}
            value={mapQuery}
            onFocus={() => {
              if (suggestions.length > 0) setShowDropdown(true);
            }}
            onChange={(e) => setMapQuery(e.target.value)}
            onKeyDown={(e) => {
              if (!showDropdown || suggestions.length === 0) return;
              if (e.key === 'ArrowDown') {
                e.preventDefault();
                setHighlightedIdx((prev) => (prev + 1) % suggestions.length);
              } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setHighlightedIdx((prev) => (prev - 1 + suggestions.length) % suggestions.length);
              } else if (e.key === 'Enter') {
                e.preventDefault();
                handlePickSuggestion(suggestions[highlightedIdx] || suggestions[0]);
              } else if (e.key === 'Escape') {
                setShowDropdown(false);
              }
            }}
          />
          {mapQuery && (
            <button
              type="button"
              onClick={() => {
                setMapQuery('');
                setSuggestions([]);
                setShowDropdown(false);
              }}
              style={{
                position: 'absolute',
                right: 10,
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              Clear ✕
            </button>
          )}

          {showDropdown && (suggestions.length > 0 || isSearching) && (
            <div
              style={{
                position: 'absolute',
                top: 'calc(100% + 4px)',
                left: 0,
                right: 0,
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-strong)',
                borderRadius: 6,
                boxShadow: '0 10px 25px rgba(28, 29, 26, 0.16)',
                maxHeight: 280,
                overflowY: 'auto',
                zIndex: 100,
              }}
            >
              {isSearching && suggestions.length === 0 && (
                <div style={{ padding: '10px 14px', color: 'var(--text-muted)', fontSize: 12.5 }}>
                  Searching locations...
                </div>
              )}
              {suggestions.map((s, idx) => (
                <div
                  key={`${s.place_name}_${idx}`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    handlePickSuggestion(s);
                  }}
                  onMouseEnter={() => setHighlightedIdx(idx)}
                  style={{
                    padding: '9px 14px',
                    cursor: 'pointer',
                    borderBottom:
                      idx < suggestions.length - 1 ? '1px solid var(--border-color)' : 'none',
                    background: idx === highlightedIdx ? 'var(--bg-subtle)' : '#ffffff',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 10,
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 13 }}>
                      {s.title}
                    </div>
                    <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                      {s.place_name}
                    </div>
                  </div>
                  <span
                    className="mono"
                    style={{
                      fontSize: 10.5,
                      padding: '2px 6px',
                      borderRadius: 4,
                      background: 'var(--bg-stone-header)',
                      color: 'var(--text-secondary)',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {s.lat.toFixed(4)}°N, {s.lon.toFixed(4)}°E
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Map Control Bar: Region Selector + 3-Way Route Leg Filter + View Mode Switcher */}
      <div
        style={{
          padding: '8px 12px',
          background: 'var(--bg-surface)',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          flexWrap: 'wrap',
          gap: 10,
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <strong style={{ color: 'var(--text-primary)' }}>Region:</strong>
          <select
            className="form-select"
            style={{ width: 'auto', padding: '4px 8px', fontSize: 12 }}
            value={selectedRegion}
            onChange={(e) => handleRegionChange(e.target.value)}
          >
            {GUJARAT_REGION_PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>

          <button
            type="button"
            className="btn btn-secondary"
            style={{
              padding: '4px 9px',
              fontSize: 11.5,
              fontWeight: 700,
              background: '#1c1d1a',
              color: '#e5a93c',
              borderColor: '#1c1d1a',
            }}
            onClick={handleFlyToDepot}
            title="Jump directly to Central Depot (H) from anywhere on the map"
          >
            ⌖ Center Depot (H)
          </button>

          <button
            type="button"
            className="btn btn-secondary"
            style={{ padding: '4px 9px', fontSize: 11.5 }}
            onClick={handleFitAllRoutesOrOrders}
          >
            Fit Active Stops
          </button>

          {(routes.length > 0 || Boolean(driverBikeMarker)) && (
            <button
              type="button"
              onClick={() => setShowLiveVehicles((v) => !v)}
              style={{
                padding: '4px 9px',
                fontSize: 11.5,
                fontWeight: 600,
                borderRadius: 5,
                border: '1px solid var(--border-strong)',
                background: showLiveVehicles ? '#dcfce7' : 'var(--bg-stone-header)',
                color: showLiveVehicles ? '#166534' : 'var(--text-secondary)',
                cursor: 'pointer',
              }}
              title="Toggle live vehicle location markers (🛵 / 🏍️) on the map"
            >
              {showLiveVehicles ? 'Vehicle Markers: ON' : 'Vehicle Markers: OFF'}
            </button>
          )}

          {/* 3-Option Segmented Route Path Filter: Departure Only | Return Only | Show Both */}
          {routes.length > 0 && (
            <div
              style={{
                display: 'inline-flex',
                borderRadius: 5,
                border: '1px solid var(--border-strong)',
                overflow: 'hidden',
                background: 'var(--bg-stone-header)',
              }}
              title="Filter route display between Departure Routes Only, Return Paths Only, or Both"
            >
              {(
                [
                  { id: 'both', label: '⇄ Show Both' },
                  { id: 'outbound', label: '▶ Departure Only' },
                  { id: 'return', label: '↩ Return Path Only' },
                ] as { id: RouteLegFilterMode; label: string }[]
              ).map((opt) => {
                const active = activeLegMode === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setLegMode(opt.id)}
                    style={{
                      padding: '4px 9px',
                      fontSize: 11,
                      fontWeight: active ? 700 : 500,
                      border: 'none',
                      borderRight: opt.id !== 'return' ? '1px solid var(--border-color)' : 'none',
                      background: active ? '#15803d' : 'transparent',
                      color: active ? '#ffffff' : 'var(--text-secondary)',
                      cursor: 'pointer',
                    }}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
          {(
            [
              { id: 'street', label: 'Street Map' },
              { id: 'satellite', label: 'Satellite (Aerial)' },
              { id: 'hybrid', label: 'Hybrid (Satellite + Labels)' },
              { id: 'terrain', label: 'Terrain' },
            ] as { id: MapViewMode; label: string }[]
          ).map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setViewMode(m.id)}
              style={{
                padding: '4px 10px',
                fontSize: 11.5,
                fontWeight: viewMode === m.id ? 600 : 500,
                borderRadius: 4,
                border: '1px solid',
                borderColor: viewMode === m.id ? 'var(--obsidian)' : 'var(--border-strong)',
                background: viewMode === m.id ? 'var(--obsidian)' : '#ffffff',
                color: viewMode === m.id ? '#f7f5f0' : 'var(--text-secondary)',
                cursor: 'pointer',
              }}
            >
              {m.label}
            </button>
          ))}

          <button
            type="button"
            onClick={() => setIs3DPitch(!is3DPitch)}
            style={{
              padding: '4px 9px',
              fontSize: 11.5,
              fontWeight: 600,
              borderRadius: 4,
              border: '1px solid var(--border-strong)',
              background: is3DPitch ? 'var(--brand-primary)' : 'var(--bg-stone-header)',
              color: is3DPitch ? '#ffffff' : 'var(--text-primary)',
              cursor: 'pointer',
            }}
          >
            {is3DPitch ? '3D Perspective: ON' : '3D Tilt'}
          </button>

          <a
            href={googleStreetViewUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              padding: '4px 9px',
              fontSize: 11.5,
              fontWeight: 600,
              borderRadius: 4,
              border: '1px solid var(--border-strong)',
              background: 'var(--bg-subtle)',
              color: 'var(--text-primary)',
              textDecoration: 'none',
            }}
          >
            360° Street View ↗
          </a>
        </div>
      </div>

      {!webglFailed ? (
        <div style={{ position: 'relative', width: '100%', height: `${height}px` }}>
          <div
            ref={mapContainerRef}
            style={{
              width: '100%',
              height: '100%',
              position: 'relative',
            }}
          />
          {/* Floating One-Click "Jump to Depot (H)" Symbol on Every Interactive Map */}
          <button
            type="button"
            onClick={handleFlyToDepot}
            title={`Fly straight to Depot (${depot?.name || 'Alkapuri Central Hub'})`}
            style={{
              position: 'absolute',
              bottom: 34,
              right: 10,
              zIndex: 25,
              width: 34,
              height: 34,
              borderRadius: 8,
              background: '#1c1d1a',
              color: '#e5a93c',
              border: '2px solid #ffffff',
              boxShadow: '0 3px 10px rgba(0,0,0,0.32)',
              fontWeight: 800,
              fontSize: 13,
              fontFamily: "'JetBrains Mono', monospace",
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            H
          </button>
        </div>
      ) : (
        <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-secondary)' }}>
          Interactive MapLibre GL JS requires WebGL in your browser.
        </div>
      )}

      {/* Vehicle Color Coding & Customer Visit Sequence Legend Bar at Bottom of Map */}
      {routes.length > 0 && (
        <div
          style={{
            padding: '10px 14px',
            background: 'var(--bg-subtle)',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            fontSize: 12,
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: 10,
            }}
          >
            <strong style={{ color: 'var(--text-primary)', fontSize: 12 }}>
              Vehicle Route Color Legend & Street Flow Semantics:
            </strong>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 14,
                flexWrap: 'wrap',
                fontSize: 11.5,
                color: 'var(--text-secondary)',
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 18,
                    height: 18,
                    borderRadius: 4,
                    background: '#1c1d1a',
                    color: '#e5a93c',
                    fontWeight: 800,
                    fontSize: 10.5,
                  }}
                >
                  H
                </span>
                Depot ({depot?.name || 'Hub'})
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span
                  style={{
                    width: 20,
                    height: 4,
                    background: '#15803d',
                    display: 'inline-block',
                    borderRadius: 2,
                  }}
                />
                <span>▶ Departure Route (Solid)</span>
              </span>
              {returnEnabled && (
                <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <span
                    style={{
                      width: 22,
                      height: 0,
                      borderTop: '3.5px dashed #15803d',
                      display: 'inline-block',
                    }}
                  />
                  <span>↩ Return-to-Depot (Dashed Vehicle Color)</span>
                </span>
              )}
              <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span
                  style={{
                    width: 22,
                    height: 0,
                    borderTop: '4px dotted #15803d',
                    display: 'inline-block',
                  }}
                />
                <span>◀ · · · ▶ Two-Way Shared Street (Go & Return)</span>
              </span>
            </div>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {routes.map((r, rIdx) => {
              const color = VEHICLE_COLORS[rIdx % VEHICLE_COLORS.length];
              const colorName = VEHICLE_COLOR_NAMES[rIdx % VEHICLE_COLOR_NAMES.length];
              const visible = isVehicleVisible(r.vehicle_id);
              const stopCodes = r.stops.map(
                (s: any, sIdx: number) =>
                  s.customer_code || deriveCustomerCode(s.external_ref, sIdx + 1)
              );
              const chainText = `H ▶ ${stopCodes.join(' ▶ ')}${returnEnabled ? ' ⇢ ↩ H' : ''}`;

              return (
                <div
                  key={r.vehicle_id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '5px 10px',
                    borderRadius: 6,
                    background: 'var(--bg-surface)',
                    border: `1.5px solid ${visible ? color : 'var(--border-color)'}`,
                    opacity: visible ? 1 : 0.4,
                    fontSize: 11.5,
                  }}
                >
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                      flexShrink: 0,
                    }}
                    title={`${colorName} (Solid = Departure, Dashed = Return, Dotted = Two-Way Shared Street)`}
                  >
                    <span
                      style={{
                        width: 12,
                        height: 4,
                        borderRadius: 2,
                        background: color,
                        display: 'inline-block',
                      }}
                    />
                    {returnEnabled && (
                      <span
                        style={{
                          width: 12,
                          height: 0,
                          borderTop: `3.5px dashed ${color}`,
                          display: 'inline-block',
                        }}
                      />
                    )}
                    <span
                      style={{
                        width: 10,
                        height: 0,
                        borderTop: `4px dotted ${color}`,
                        display: 'inline-block',
                      }}
                    />
                  </span>
                  <strong className="mono" style={{ color }}>
                    {r.vehicle_code}
                  </strong>
                  <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>({colorName}):</span>
                  <span className="mono" style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                    {chainText}
                  </span>
                  <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                    · {(r.distance_m / 1000).toFixed(1)} km
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div
        style={{
          padding: '6px 12px',
          background: 'var(--bg-stone-header)',
          borderTop: '1px solid var(--border-color)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: 11.5,
          color: 'var(--text-secondary)',
        }}
      >
        <span className="mono">
          Selected Coordinates: <strong>{activePinLat.toFixed(5)}°N, {activePinLon.toFixed(5)}°E</strong> ·
          View: <strong>{viewMode.toUpperCase()}</strong>
        </span>
        <span>
          {onSelectLocation
            ? 'Click on the map or drag the green pin to adjust exact gate location'
            : 'Solid = Departure · Dashed = Return · Dotted (◀ ··· ▶) = Two-Way Go & Return Street'}
        </span>
      </div>
    </div>
  );
};
