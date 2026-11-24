import React, { useEffect, useState } from 'react';
import { apiClient } from './api/client';
import { InteractiveMap, VEHICLE_COLORS, VEHICLE_COLOR_NAMES, deriveCustomerCode, normalizeAndUncrossPlan } from './components/InteractiveMap';
import { MultiVehicleSelectDropdown } from './components/MultiVehicleSelectDropdown';
import {
  AlgorithmPerformanceLabView,
  PlatformSettingsModal,
  TrafficLiveSimulationView,
} from './components/AdvancedAnalyticsAndSimViews';
import {
  CustomerNavSection,
  CustomerTrackingPortalView,
  DriverDetailsModal,
  DriverNavSection,
  DriverPortalView,
  UniversalConfirmModal,
  computeOrderOperationalStatus,
  isPromisedDateOverdue,
} from './components/DriverAndCustomerPortals';
import {
  CostProfileDto,
  CustomerDto,
  DepotDto,
  formatDurationSeconds,
  formatPaiseToINR,
  formatSecondsToClockIST,
  OrderDto,
  PlanDto,
  RoadEdgeDto,
  RoadNodeDto,
  TrafficScenarioDto,
  VehicleDto,
} from './types/api';

type NavTab =
  | 'dashboard'
  | 'depot'
  | 'orders'
  | 'fleet'
  | 'planning'
  | 'results'
  | 'replan'
  | 'benchmarks';

const BASE_MORNING_UTC_S = 1794882600; // 2026-11-17 08:00:00 IST (02:30 UTC)
const SHIFT_START_MIDNIGHT_IST_UTC_S = BASE_MORNING_UTC_S - 8 * 3600; // 00:00 IST in UTC seconds

function clockHHMMToUtcSeconds(hhmm: string, dayOffset = 0): number {
  const parts = hhmm.split(':');
  const hrs = parseInt(parts[0] || '8', 10);
  const mins = parseInt(parts[1] || '0', 10);
  return SHIFT_START_MIDNIGHT_IST_UTC_S + dayOffset * 86400 + hrs * 3600 + mins * 60;
}

function utcSecondsToClockHHMM(utcS: number): string {
  const secFromMidnight = (((utcS - SHIFT_START_MIDNIGHT_IST_UTC_S) % 86400) + 86400) % 86400;
  const hrs = Math.floor(secFromMidnight / 3600);
  const mins = Math.floor((secFromMidnight % 3600) / 60);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
}

/* Bespoke Classical Geometric SVG Icons for Expandable/Collapsible Sidebar */
const NavIcon: React.FC<{ tab: NavTab }> = ({ tab }) => {
  switch (tab) {
    case 'dashboard':
      return (
        <svg className="nav-icon-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.65">
          <rect x="2.5" y="2.5" width="6.2" height="6.2" rx="1.3" />
          <rect x="11.3" y="2.5" width="6.2" height="6.2" rx="1.3" />
          <rect x="2.5" y="11.3" width="6.2" height="6.2" rx="1.3" />
          <rect x="11.3" y="11.3" width="6.2" height="6.2" rx="1.3" />
        </svg>
      );
    case 'planning':
      return (
        <svg className="nav-icon-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.65">
          <circle cx="5" cy="5.5" r="2.2" />
          <path d="M7.2 5.5H17" strokeLinecap="round" />
          <circle cx="14.5" cy="10" r="2.2" />
          <path d="M3 10H12.3" strokeLinecap="round" />
          <circle cx="7.5" cy="14.5" r="2.2" />
          <path d="M9.7 14.5H17" strokeLinecap="round" />
        </svg>
      );
    case 'results':
      return (
        <svg className="nav-icon-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.65">
          <circle cx="4.5" cy="15.5" r="2" />
          <circle cx="15.5" cy="4.5" r="2" />
          <path d="M6.5 15.5H11.5C13.2 15.5 14.5 14.2 14.5 12.5V9.5C14.5 7.8 13.2 6.5 11.5 6.5H8.5C6.8 6.5 5.5 5.2 5.5 3.5" strokeLinecap="round" />
        </svg>
      );
    case 'replan':
      return (
        <svg className="nav-icon-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.65">
          <path d="M10 3L16.5 15.5H3.5L10 3Z" strokeLinejoin="round" />
          <path d="M6.3 10.2H13.7" />
          <path d="M5 12.8H15" />
          <path d="M2 16H18" strokeLinecap="round" />
        </svg>
      );
    case 'orders':
      return (
        <svg className="nav-icon-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.65">
          <path d="M10 2.3L16.8 6.1V13.9L10 17.7L3.2 13.9V6.1L10 2.3Z" strokeLinejoin="round" />
          <path d="M3.2 6.1L10 9.9L16.8 6.1" />
          <path d="M10 9.9V17.7" />
        </svg>
      );
    case 'fleet':
      return (
        <svg className="nav-icon-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.65">
          <rect x="2" y="5" width="10.5" height="8.5" rx="1.2" />
          <path d="M12.5 7.5H15.8L18 10.3V13.5H12.5V7.5Z" strokeLinejoin="round" />
          <circle cx="5.5" cy="14.8" r="1.8" />
          <circle cx="15" cy="14.8" r="1.8" />
        </svg>
      );
    case 'depot':
      return (
        <svg className="nav-icon-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.65">
          <path d="M10 17.5C10 17.5 15.8 12.6 15.8 8.1C15.8 4.9 13.2 2.3 10 2.3C6.8 2.3 4.2 4.9 4.2 8.1C4.2 12.6 10 17.5 10 17.5Z" />
          <circle cx="10" cy="8.1" r="2.2" />
        </svg>
      );
    case 'benchmarks':
      return (
        <svg className="nav-icon-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.65">
          <path d="M3 16.5H17" strokeLinecap="round" />
          <rect x="4.5" y="9.5" width="2.6" height="7" rx="0.6" />
          <rect x="8.7" y="5.5" width="2.6" height="11" rx="0.6" />
          <rect x="12.9" y="3.5" width="2.6" height="13" rx="0.6" />
        </svg>
      );
  }
};

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NavTab>('dashboard');
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(false);
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    try {
      return typeof window !== 'undefined' && window.localStorage.getItem('routeit_dark_mode') === '1';
    } catch {
      return false;
    }
  });
  const [showSettingsModal, setShowSettingsModal] = useState<boolean>(false);

  const handleToggleDarkMode = (dark: boolean) => {
    setDarkMode(dark);
    try {
      if (typeof window !== 'undefined') {
        window.localStorage.setItem('routeit_dark_mode', dark ? '1' : '0');
      }
    } catch {
      // Ignore storage error
    }
  };
  const [showLoadPopover, setShowLoadPopover] = useState<boolean>(false);
  const [loadHoverX, setLoadHoverX] = useState<number>(160);
  const [hoveredLoadTier, setHoveredLoadTier] = useState<string>('ALL');
  const [showPiePopover, setShowPiePopover] = useState<boolean>(false);
  const [hoveredPieSlice, setHoveredPieSlice] = useState<string>('ALL');
  const [loading, setLoading] = useState<boolean>(false);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [successBanner, setSuccessBanner] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage((curr) => (curr === msg ? null : curr));
    }, 4400);
  };

  // Domain Data
  const [summary, setSummary] = useState<any>(null);
  const [roadNodes, setRoadNodes] = useState<RoadNodeDto[]>([]);
  const [roadEdges, setRoadEdges] = useState<RoadEdgeDto[]>([]);
  const [depots, setDepots] = useState<DepotDto[]>([]);
  const [customers, setCustomers] = useState<CustomerDto[]>([]);
  const [orders, setOrders] = useState<OrderDto[]>([]);
  const [vehicles, setVehicles] = useState<VehicleDto[]>([]);
  const [costProfiles, setCostProfiles] = useState<CostProfileDto[]>([]);
  const [trafficScenarios, setTrafficScenarios] = useState<TrafficScenarioDto[]>([]);

  // Active Planning & Result State
  const [validationReport, setValidationReport] = useState<any>(null);
  const [activePlanningRequestId, setActivePlanningRequestId] = useState<string | null>(null);
  const [activeShiftId, setActiveShiftId] = useState<string | null>(null);
  const [activeRunResult, setActiveRunResult] = useState<any>(null);
  const [activePlan, setActivePlan] = useState<PlanDto | null>(null);
  const [selectedVehicleFilter, setSelectedVehicleFilter] = useState<string | null>(null);
  const [selectedVehicleIdsOverview, setSelectedVehicleIdsOverview] = useState<string[]>([]);
  const [selectedVehicleIdsResults, setSelectedVehicleIdsResults] = useState<string[]>([]);
  const [replanOutput, setReplanOutput] = useState<any>(null);

  // 3-Portal Switcher & Dedicated Portal Sidebar Navigation State
  const [portalMode, setPortalMode] = useState<'admin' | 'driver' | 'customer'>('admin');
  const [driverNavSection, setDriverNavSection] = useState<DriverNavSection>('manifest');
  const [customerNavSection, setCustomerNavSection] = useState<CustomerNavSection>('overview');
  const [preselectedDriverVehicle, setPreselectedDriverVehicle] = useState<VehicleDto | null>(null);
  const [inspectingDriverVehicle, setInspectingDriverVehicle] = useState<VehicleDto | null>(null);

  // Route Planning Order Selection & Re-Optimize State
  const [selectedOrderIdsForPlanning, setSelectedOrderIdsForPlanning] = useState<string[]>([]);
  const [reoptimizingRunId, setReoptimizingRunId] = useState<string | null>(null);
  const [selectedDispatchRunId, setSelectedDispatchRunId] = useState<string>('');

  // Universal Confirmation & Past-Deadline Warning Modal State
  const [confirmModal, setConfirmModal] = useState<{
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
    onConfirm: () => void;
  } | null>(null);

  // Benchmark Dataset & Result State
  const [benchmarkDatasetMode, setBenchmarkDatasetMode] = useState<'RECENT_RUN' | 'LIVE_WORKSPACE' | 'STANDARD_PILOT'>('LIVE_WORKSPACE');
  const [selectedBenchmarkRunId, setSelectedBenchmarkRunId] = useState<string>('');
  const [benchmarkBudget, setBenchmarkBudget] = useState<number>(100);
  const [benchmarkReport, setBenchmarkReport] = useState<any>(null);

  // Depot Form State (Single Depot Replacement — User enters Depot Name manually)
  const [depotName, setDepotName] = useState('');
  const [depotLat, setDepotLat] = useState(22.3106);
  const [depotLon, setDepotLon] = useState(73.1685);
  const [depotOpenHHMM, setDepotOpenHHMM] = useState('07:30');
  const [depotCloseHHMM, setDepotCloseHHMM] = useState('20:30');
  const [depotReturnEnabled, setDepotReturnEnabled] = useState(true);

  // Customer & Order Form State (User enters Customer Name manually; cleared on submit!)
  const [custName, setCustName] = useState('');
  const [custLat, setCustLat] = useState(22.3081);
  const [custLon, setCustLon] = useState(73.1812);
  const [custAddress, setCustAddress] = useState('');
  const [custInstructions, setCustInstructions] = useState('');
  const [locationVerified, setLocationVerified] = useState<boolean>(false);

  const [selectedCustomerId, setSelectedCustomerId] = useState('');
  const [orderRef, setOrderRef] = useState('');
  const [orderWeightKg, setOrderWeightKg] = useState<string>('');
  const [orderServiceMinutes, setOrderServiceMinutes] = useState<string>('10');
  const [promisedDate, setPromisedDate] = useState<string>('');
  const [hasFixedTimeWindow, setHasFixedTimeWindow] = useState<boolean>(false);
  const [slotOpenHHMM, setSlotOpenHHMM] = useState<string>('10:00');
  const [slotCloseHHMM, setSlotCloseHHMM] = useState<string>('12:00');
  const [orderWinType, setOrderWinType] = useState<'HARD' | 'SOFT'>('HARD');
  const [orderPriority, setOrderPriority] = useState<'CRITICAL' | 'STANDARD' | 'FLEXIBLE'>('STANDARD');

  // Edit Order Drawer State
  const [editingOrder, setEditingOrder] = useState<any | null>(null);
  const [editWeightKg, setEditWeightKg] = useState<number>(15);
  const [editServiceMinutes, setEditServiceMinutes] = useState<number>(10);
  const [editStatus, setEditStatus] = useState<string>('NEW');
  const [editPriority, setEditPriority] = useState<'CRITICAL' | 'STANDARD' | 'FLEXIBLE'>('STANDARD');
  const [editWinType, setEditWinType] = useState<'HARD' | 'SOFT'>('HARD');
  const [editSlotOpenHHMM, setEditSlotOpenHHMM] = useState<string>('10:00');
  const [editSlotCloseHHMM, setEditSlotCloseHHMM] = useState<string>('12:00');
  const [editPromisedDate, setEditPromisedDate] = useState<string>('');
  const [editAddress, setEditAddress] = useState<string>('');
  const [editInstructions, setEditInstructions] = useState<string>('');

  // Fleet & Tariff Form State (Cleared immediately on submit!)
  const [vehCode, setVehCode] = useState('');
  const [vehCapacityKg, setVehCapacityKg] = useState<string>('');
  const [vehActivationINR, setVehActivationINR] = useState<string>('');
  const [vehDriverName, setVehDriverName] = useState<string>('');
  const [vehDriverUsername, setVehDriverUsername] = useState<string>('');
  const [vehDriverPassword, setVehDriverPassword] = useState<string>('');
  const [showVehicleDriverStep, setShowVehicleDriverStep] = useState<boolean>(false);

  const [tariffName, setTariffName] = useState('');
  const [tariffPerKmINR, setTariffPerKmINR] = useState<string>('8');
  const [tariffPerHourINR, setTariffPerHourINR] = useState<string>('100');
  const [tariffCritSlaINR, setTariffCritSlaINR] = useState<string>('10');
  const [tariffStdSlaINR, setTariffStdSlaINR] = useState<string>('5');
  const [tariffFlexSlaINR, setTariffFlexSlaINR] = useState<string>('2');

  // Planning Configuration State
  const [planningMode, setPlanningMode] = useState<'COMPLETE' | 'PARTIAL'>('COMPLETE');
  const [fleetMode, setFleetMode] = useState<'AUTO' | 'TARGET'>('AUTO');
  const [targetFleetSize, setTargetFleetSize] = useState<number>(3);
  const [optProfile, setOptProfile] = useState<'COST_FOCUSED' | 'BALANCED' | 'DRIVER_PRODUCTIVITY'>('COST_FOCUSED');
  const [maxExtraCostINR, setMaxExtraCostINR] = useState<number>(250);
  const [solverKind, setSolverKind] = useState<string>('QPSO');
  const [showAdvancedControls, setShowAdvancedControls] = useState<boolean>(false);
  const [maxEvaluations, setMaxEvaluations] = useState<number>(160);
  const [qpsoParticles, setQpsoParticles] = useState<number>(12);
  const [qpsoGenerations, setQpsoGenerations] = useState<number>(15);
  const [qpsoAlphaMax, setQpsoAlphaMax] = useState<number>(1.0);
  const [qpsoAlphaMin, setQpsoAlphaMin] = useState<number>(0.5);
  const [partialSplitMode, setPartialSplitMode] = useState<'EXACT_TINY' | 'BOUNDED_PRACTICAL'>('EXACT_TINY');
  const [randomSeed, setRandomSeed] = useState<number>(42);

  // Replanning Simulation Controls
  const [replanElapsedMin, setReplanElapsedMin] = useState<number>(20);
  const [replanCongestedEdge, setReplanCongestedEdge] = useState<string>('E_N_SAYAJIGUNJ_TO_N_FATEHGUNJ');
  const [replanSpeedMultiplier, setReplanSpeedMultiplier] = useState<number>(0.35);

  const refreshAllData = async () => {
    try {
      const [sum, net, deps, custs, ords, vehs, cps, tss] = await Promise.all([
        apiClient.getDashboardSummary(),
        apiClient.getRoadNetwork(),
        apiClient.listDepots(),
        apiClient.listCustomers(),
        apiClient.listOrders(),
        apiClient.listVehicles(),
        apiClient.listCostProfiles(),
        apiClient.listTrafficScenarios(),
      ]);
      setSummary(sum);
      setRoadNodes(net.nodes || []);
      setRoadEdges(net.edges || []);
      setDepots(deps);
      setCustomers(custs);
      setOrders(ords);
      setVehicles(vehs);
      setSelectedOrderIdsForPlanning((prev) => {
        const eligibleIds = ords
          .filter((o: any) => o.status !== 'CANCELLED' && o.status !== 'DELIVERED' && o.status !== 'RETURNED')
          .map((o: any) => o.id);
        if (prev.length === 0) return eligibleIds;
        const kept = prev.filter((id) => eligibleIds.includes(id));
        return kept.length > 0 ? kept : eligibleIds;
      });
      setCostProfiles(cps);
      setTrafficScenarios(tss);
      if (sum?.recent_runs?.length) {
        if (!selectedBenchmarkRunId) {
          setSelectedBenchmarkRunId(sum.recent_runs[0].id);
        }
        const latestWithPlan = sum.recent_runs.find((r: any) => r.plan_id);
        if (latestWithPlan && !activePlan) {
          try {
            const latestRes = await apiClient.getOptimizationRunResult(latestWithPlan.id);
            if (latestRes?.plan) {
              setActivePlan(normalizeAndUncrossPlan(latestRes.plan, deps[0], latestWithPlan.solver_kind));
              setSelectedDispatchRunId(latestWithPlan.id);
            }
          } catch {
            // Ignore initial plan preload error
          }
        }
      }
    } catch (err: any) {
      setErrorBanner(err.message || 'Failed to load operational data');
    }
  };

  useEffect(() => {
    refreshAllData();
  }, []);

  const handleLoadPilotScenario = async () => {
    // Requirement 5: If the Vadodara Sample Shift dataset is already loaded, block duplicate loading and show a popup!
    const alreadyHasVadodaraOrders =
      orders.length >= 6 &&
      orders.some((o: any) => /^ORD-VAD-/i.test(String(o.external_ref || '')));
    const alreadyHasVadodaraVehicles =
      vehicles.length >= 4 &&
      vehicles.some((v: any) => /^VAN-10[1-4]$/i.test(String(v.code || '')));

    if (alreadyHasVadodaraOrders && alreadyHasVadodaraVehicles) {
      setConfirmModal({
        title: 'ℹ This Dataset Is Already Loaded',
        message:
          'The Vadodara Sample Shift dataset (Alkapuri Hub · 4 Fleet Vehicles · 8 Customer Orders) is already loaded in your active workspace. Duplicate loading is blocked so duplicate orders, vehicles, and drivers are never created. If you want to wipe and reload fresh data, click "Open Settings to Reset" below.',
        confirmLabel: 'OK, Keep Current Dataset',
        cancelLabel: '⚙️ Open Settings to Reset',
        danger: false,
        onConfirm: () => {
          setConfirmModal(null);
        },
      });
      return;
    }

    setLoading(true);
    setErrorBanner(null);
    try {
      await apiClient.seedVadodaraPilot();
      await refreshAllData();
      showToast('✓ Loaded sample shift data (1 Active Depot, 4 Fleet Vehicles, 8 Delivery Orders).');
    } catch (err: any) {
      setErrorBanner(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleResetAllPlatformData = async () => {
    setLoading(true);
    setErrorBanner(null);
    try {
      await apiClient.resetPlatformData();
      setActivePlan(null);
      setActiveRunResult(null);
      setValidationReport(null);
      setBenchmarkReport(null);
      setReplanOutput(null);
      setSelectedDispatchRunId('');
      await refreshAllData();
      showToast('🗑️ All platform operational data has been reset to a clean state!');
    } catch (err: any) {
      setErrorBanner(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Pin selection for Customer: ONLY updates coordinates & street address, NEVER overwrites Customer Name!
  const handleMapPinPickForCustomer = async (
    lat: number,
    lon: number,
    placeMeta?: { title?: string; address?: string }
  ) => {
    setCustLat(lat);
    setCustLon(lon);
    if (placeMeta?.address) {
      setCustAddress(placeMeta.address);
    }
    try {
      const rev = await apiClient.geocodeReverse(lat, lon);
      setLocationVerified(Boolean(rev.in_depot_scc));
      if (!placeMeta?.address && rev.address_text) {
        setCustAddress(rev.address_text);
      }
    } catch (err: any) {
      setErrorBanner(err.message);
    }
  };

  const handleCreateCustomerAndConfirm = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorBanner(null);
    if (!custName.trim() || !custAddress.trim()) {
      setErrorBanner('Please enter both the Customer / Consignee Name and the Delivery Address.');
      return;
    }
    try {
      const created = await apiClient.createCustomer({
        name: custName.trim(),
        lat: custLat,
        lon: custLon,
        address_text: custAddress.trim(),
        delivery_instructions: custInstructions.trim(),
        confirmed: true,
      });
      await refreshAllData();
      setSelectedCustomerId(created.id);
      setCustName('');
      setCustAddress('');
      setCustInstructions('');
      setLocationVerified(false);
      showToast(`✓ Customer "${created.name}" confirmed and added to directory!`);
    } catch (err: any) {
      setErrorBanner(err.message);
    }
  };

  const handleCreateOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorBanner(null);
    if (!selectedCustomerId) {
      setErrorBanner('Please select a confirmed customer from the dropdown first.');
      return;
    }
    const weightVal = parseInt(orderWeightKg, 10);
    if (!weightVal || weightVal <= 0) {
      setErrorBanner('Please enter a valid positive Order Weight (in kg).');
      return;
    }
    const srvMins = parseInt(orderServiceMinutes || '10', 10);
    if (isNaN(srvMins) || srvMins < 0) {
      setErrorBanner('Please enter valid unloading duration in minutes.');
      return;
    }

    let wOpen = BASE_MORNING_UTC_S;
    let wClose = BASE_MORNING_UTC_S + 12 * 3600;
    let effectiveWinType: 'HARD' | 'SOFT' = 'SOFT';

    if (hasFixedTimeWindow) {
      wOpen = clockHHMMToUtcSeconds(slotOpenHHMM);
      wClose = clockHHMMToUtcSeconds(slotCloseHHMM);
      if (wClose <= wOpen) {
        setErrorBanner('Time Window Close time must be later than Window Open time (e.g. 10:00 to 12:00).');
        return;
      }
      effectiveWinType = orderWinType;
    }

    if (!promisedDate) {
      setErrorBanner('Please select a Promised Delivery Date (Order Deadline).');
      return;
    }

    const refToUse = orderRef.trim() || `ORD-${Math.floor(1000 + Math.random() * 9000)}`;
    const overdue = isPromisedDateOverdue(promisedDate);

    const executeCreateOrder = async () => {
      try {
        const created = await apiClient.createOrder({
          customer_id: selectedCustomerId,
          external_ref: refToUse,
          demand_units: weightVal,
          service_seconds: srvMins * 60,
          // Give overdue CRITICAL orders earliest window priority so solver dispatches them first!
          window_open_utc_s: overdue && orderPriority === 'CRITICAL' ? BASE_MORNING_UTC_S : wOpen,
          window_close_utc_s: overdue && orderPriority === 'CRITICAL' ? Math.min(wClose, BASE_MORNING_UTC_S + 5400) : wClose,
          window_type: effectiveWinType,
          priority: orderPriority,
          promised_date: promisedDate,
          is_overdue: overdue,
          has_fixed_time_window: hasFixedTimeWindow,
        });
        await refreshAllData();
        setSelectedOrderIdsForPlanning((prev) =>
          prev.includes(created.id) ? prev : [...prev, created.id]
        );
        setOrderRef('');
        setOrderWeightKg('');
        setOrderServiceMinutes('10');
        setPromisedDate('');
        setHasFixedTimeWindow(false);
        showToast(
          overdue
            ? `✓ Past-deadline order "${created.external_ref}" added (${orderPriority === 'CRITICAL' ? 'Assigned HIGHEST Dispatch Priority' : 'Marked Overdue'})!`
            : `✓ Order "${created.external_ref}" (${weightVal} kg) created and validated!`
        );
      } catch (err: any) {
        setErrorBanner(err.message);
      }
    };

    if (overdue) {
      setConfirmModal({
        title: '⚠ Promised Deadline Date Has Already Passed',
        message: `The promised delivery deadline date (${promisedDate}) has already passed. Do you still want to add this order? ${
          orderPriority === 'CRITICAL'
            ? 'Because this order is marked CRITICAL with a passed deadline, it will automatically be given HIGHEST priority in route planning.'
            : 'It will be flagged as Past Deadline / Late.'
        }`,
        confirmLabel: 'Yes, Add Past-Deadline Order',
        cancelLabel: 'Change Deadline Date',
        danger: false,
        onConfirm: () => {
          setConfirmModal(null);
          executeCreateOrder();
        },
      });
      return;
    }

    await executeCreateOrder();
  };

  const handleOpenEditOrder = (ord: any) => {
    setEditingOrder(ord);
    setEditWeightKg(ord.demand_units);
    setEditServiceMinutes(Math.round((ord.service_seconds || 300) / 60));
    setEditStatus(ord.status || 'NEW');
    setEditPriority(ord.priority);
    setEditPromisedDate(ord.promised_date || '');
    setEditWinType(ord.window_type);
    setEditSlotOpenHHMM(utcSecondsToClockHHMM(ord.window_open_utc_s));
    setEditSlotCloseHHMM(utcSecondsToClockHHMM(ord.window_close_utc_s));
    setEditAddress(ord.address_text || '');
    setEditInstructions(ord.delivery_instructions || '');
  };

  const handleSaveEditedOrder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingOrder) return;
    setErrorBanner(null);
    const wOpen = clockHHMMToUtcSeconds(editSlotOpenHHMM);
    const wClose = clockHHMMToUtcSeconds(editSlotCloseHHMM);
    if (wClose <= wOpen) {
      setErrorBanner('Slot end time must be after slot start time.');
      return;
    }
    const overdue = isPromisedDateOverdue(editPromisedDate);

    const performUpdate = async () => {
      try {
        await apiClient.updateOrder(editingOrder.id, {
          demand_units: Number(editWeightKg),
          service_seconds: Number(editServiceMinutes) * 60,
          window_open_utc_s: wOpen,
          window_close_utc_s: wClose,
          window_type: editWinType,
          priority: editPriority,
          status: editStatus,
          promised_date: editPromisedDate,
          is_overdue: overdue,
          address_text: editAddress,
          delivery_instructions: editInstructions,
        });
        setEditingOrder(null);
        await refreshAllData();
        showToast(`✓ Order ${editingOrder.external_ref} updated (${editStatus}).`);
      } catch (err: any) {
        setErrorBanner(err.message);
      }
    };

    if (overdue && editPromisedDate !== (editingOrder.promised_date || '')) {
      setConfirmModal({
        title: '⚠ Promised Deadline Date Has Already Passed',
        message: `The updated promised deadline date (${editPromisedDate}) has already passed. Do you still want to save this deadline?`,
        confirmLabel: 'Yes, Save Past-Deadline Date',
        cancelLabel: 'Pick Another Date',
        danger: false,
        onConfirm: () => {
          setConfirmModal(null);
          performUpdate();
        },
      });
      return;
    }

    await performUpdate();
  };

  const handleCreateVehicle = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorBanner(null);
    if (depots.length === 0) {
      setErrorBanner('Please configure a central depot in the Depot tab before adding vehicles.');
      return;
    }
    const capKg = parseInt(vehCapacityKg, 10);
    const actInr = parseFloat(vehActivationINR || '0');
    if (!vehCode.trim() || !capKg || capKg <= 0 || isNaN(actInr) || actInr < 0) {
      setErrorBanner('Please enter Vehicle Code/Plate, Load Capacity (kg), and Dispatch Base Cost (₹).');
      return;
    }
    try {
      const cleanCode = vehCode.trim();
      const defaultUser = cleanCode.toLowerCase().replace(/[^a-z0-9]/g, '');
      const created = await apiClient.createVehicle({
        depot_id: depots[0].id,
        code: cleanCode,
        capacity_units: capKg,
        activation_cost_paise: Math.round(actInr * 100),
        available: true,
        driver_name: vehDriverName.trim() || `Driver (${cleanCode})`,
        driver_username: vehDriverUsername.trim() || defaultUser,
        driver_password: vehDriverPassword.trim() || 'pass123',
      });
      await refreshAllData();
      setVehCode('');
      setVehCapacityKg('');
      setVehActivationINR('');
      setVehDriverName('');
      setVehDriverUsername('');
      setVehDriverPassword('');
      setShowVehicleDriverStep(false);
      showToast(`✓ Vehicle "${created.code}" (${capKg} kg) & Driver "${created.driver_name}" registered!`);
    } catch (err: any) {
      setErrorBanner(err.message);
    }
  };

  const handleCreateTariffProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorBanner(null);
    const kmPaise = Math.round(parseFloat(tariffPerKmINR || '8') * 100);
    const hrPaise = Math.round(parseFloat(tariffPerHourINR || '100') * 100);
    const critPaise = Math.round(parseFloat(tariffCritSlaINR || '10') * 100);
    const stdPaise = Math.round(parseFloat(tariffStdSlaINR || '5') * 100);
    const flexPaise = Math.round(parseFloat(tariffFlexSlaINR || '2') * 100);
    try {
      await apiClient.createCostProfile({
        name: tariffName.trim() || `Fleet Tariff (₹${tariffPerKmINR}/km, ₹${tariffPerHourINR}/hr)`,
        distance_rate_paise_per_km: { n: kmPaise, d: 1 },
        time_rate_paise_per_hour: { n: hrPaise, d: 1 },
        critical_sla_paise_per_min: { n: critPaise, d: 1 },
        standard_sla_paise_per_min: { n: stdPaise, d: 1 },
        flexible_sla_paise_per_min: { n: flexPaise, d: 1 },
      });
      setTariffName('');
      await refreshAllData();
      showToast('✓ Operating cost tariff saved and set as active!');
    } catch (err: any) {
      setErrorBanner(err.message);
    }
  };

  const handleValidateAndRunOptimization = async (
    runImmediately: boolean,
    overrideConfig?: {
      planningMode?: 'COMPLETE' | 'PARTIAL';
      fleetMode?: 'AUTO' | 'TARGET';
      targetFleetSize?: number;
    }
  ) => {
    setErrorBanner(null);
    setSuccessBanner(null);
    const effPlanningMode = overrideConfig?.planningMode ?? planningMode;
    const effFleetMode = overrideConfig?.fleetMode ?? fleetMode;
    const effTargetSize = overrideConfig?.targetFleetSize ?? targetFleetSize;

    if (overrideConfig?.planningMode) setPlanningMode(overrideConfig.planningMode);
    if (overrideConfig?.fleetMode) setFleetMode(overrideConfig.fleetMode);
    if (overrideConfig?.targetFleetSize !== undefined) setTargetFleetSize(overrideConfig.targetFleetSize);

    const eligiblePool = orders.filter((o: any) => o.status !== 'CANCELLED' && o.status !== 'DELIVERED' && o.status !== 'RETURNED');
    const chosenPool = eligiblePool.filter((o: any) => selectedOrderIdsForPlanning.includes(o.id));
    const rawActiveOrders = chosenPool.length > 0 ? chosenPool : eligiblePool;
    // Sort overdue CRITICAL orders first so solver gives them highest dispatch priority!
    const activeOrdersList = [...rawActiveOrders].sort((a: any, b: any) => {
      const aOverCrit = (Boolean(a.is_overdue) || isPromisedDateOverdue(a.promised_date)) && a.priority === 'CRITICAL' ? 0 : 1;
      const bOverCrit = (Boolean(b.is_overdue) || isPromisedDateOverdue(b.promised_date)) && b.priority === 'CRITICAL' ? 0 : 1;
      return aOverCrit - bOverCrit;
    });
    const availableVehiclesList = vehicles.filter((v) => v.available);

    if (depots.length === 0 || activeOrdersList.length === 0 || availableVehiclesList.length === 0) {
      setErrorBanner(
        'An active depot, at least one available vehicle, and at least one pending delivery order are required. Click "Load Sample Shift Data" in the top bar if starting fresh.'
      );
      return;
    }

    setLoading(true);
    try {
      let cpId = costProfiles[0]?.id;
      if (!cpId) {
        const createdCp = await apiClient.createCostProfile({
          name: 'Default Fleet Tariff (₹8/km, ₹100/hr)',
          distance_rate_paise_per_km: { n: 800, d: 1 },
          time_rate_paise_per_hour: { n: 10000, d: 1 },
          critical_sla_paise_per_min: { n: 1000, d: 1 },
          standard_sla_paise_per_min: { n: 500, d: 1 },
          flexible_sla_paise_per_min: { n: 200, d: 1 },
        });
        cpId = createdCp.id;
      }

      let tsId = trafficScenarios[0]?.id;
      if (!tsId) {
        const createdTs = await apiClient.createTrafficScenario({
          name: 'Gujarat Standard Peak Traffic Profile',
          kind: 'TIME_PROFILE',
          revision: 1,
        });
        tsId = createdTs.id;
      }

      const prResp = await apiClient.createPlanningRequest({
        shift_id: activeShiftId || undefined,
        depot_id: depots[0].id,
        order_ids: activeOrdersList.map((o) => o.id),
        vehicle_ids: vehicles.map((v) => v.id),
        cost_profile_id: cpId,
        traffic_scenario_id: tsId,
        planning_mode: effPlanningMode,
        fleet_mode: effFleetMode,
        target_fleet_size: effFleetMode === 'TARGET' ? Number(effTargetSize) : null,
        profile: optProfile,
        max_extra_cost_paise:
          optProfile === 'DRIVER_PRODUCTIVITY' ? Math.round(Number(maxExtraCostINR) * 100) : null,
        departure_set_utc_s: [depots[0].opening_time_utc_s || BASE_MORNING_UTC_S],
        partial_split_mode: partialSplitMode,
      });

      setValidationReport(prResp.validation_report);
      setActivePlanningRequestId(prResp.planning_request_id);
      setActiveShiftId(prResp.shift_id);

      const adv = prResp.validation_report?.fleet_advisory;
      if (!runImmediately) {
        if (prResp.status === 'VALIDATED') {
          showToast(`✓ Readiness Check Passed: Minimum ${adv?.min_vehicles_for_complete_plan ?? 1} vehicle(s) required for 100% delivery.`);
        } else {
          showToast(`⚠ Fleet Limit Alert: Minimum ${adv?.min_vehicles_for_complete_plan ?? 1} vehicles needed for Complete Plan.`);
        }
        return;
      }

      // If Complete Plan is impossible with the selected target fleet, stay on Planning tab and highlight minimum required vehicles!
      if (effPlanningMode === 'COMPLETE' && prResp.status === 'REJECTED_PROVEN_INFEASIBLE') {
        showToast(
          `⚠ Complete Plan requires at least ${adv?.min_vehicles_for_complete_plan} vehicles (you selected ${adv?.selected_fleet_limit}). See advisory on the right.`
        );
        await refreshAllData();
        return;
      }

      const runResp = await apiClient.createOptimizationRun({
        planning_request_id: prResp.planning_request_id,
        solver_kind: solverKind,
        max_canonical_evaluations: Number(maxEvaluations),
        qpso_particles: Number(qpsoParticles),
        qpso_generations: Number(qpsoGenerations),
        qpso_alpha_max: Number(qpsoAlphaMax),
        qpso_alpha_min: Number(qpsoAlphaMin),
        seed: Number(randomSeed),
        execute_synchronously: true,
      });

      const fullResult = await apiClient.getOptimizationRunResult(runResp.run_id);
      setActiveRunResult(fullResult);
      if (fullResult.validation_report) {
        setValidationReport(fullResult.validation_report);
      }
      await refreshAllData();

      if (fullResult.plan) {
        setActivePlan(normalizeAndUncrossPlan(fullResult.plan, depots[0], solverKind));
        setSelectedBenchmarkRunId(runResp.run_id);
        setSelectedDispatchRunId(runResp.run_id);
        setReoptimizingRunId(null);
        setActiveTab('results');
        showToast(
          `✓ Route plan v${fullResult.plan.version} generated (${fullResult.result_status} · ${fullResult.plan.m_routes_used} vehicles).`
        );
      } else {
        showToast(
          `⚠ No feasible Complete Plan found with ${adv?.selected_fleet_limit} vehicle(s). Minimum ${adv?.min_vehicles_for_complete_plan} vehicles required.`
        );
      }
    } catch (err: any) {
      setErrorBanner(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRunSolverForComparison = async (targetSolverKind: string): Promise<PlanDto | null> => {
    const eligiblePool = orders.filter(
      (o: any) => o.status !== 'CANCELLED' && o.status !== 'DELIVERED' && o.status !== 'RETURNED'
    );
    if (!depots[0] || eligiblePool.length === 0 || vehicles.length === 0) {
      if (activePlan) return normalizeAndUncrossPlan(activePlan, depots[0], targetSolverKind);
      return null;
    }
    try {
      let cpId = costProfiles[0]?.id;
      if (!cpId) {
        const createdCp = await apiClient.createCostProfile({
          name: 'Default Fleet Tariff (₹8/km, ₹100/hr)',
          distance_rate_paise_per_km: { n: 800, d: 1 },
          time_rate_paise_per_hour: { n: 10000, d: 1 },
          critical_sla_paise_per_min: { n: 1000, d: 1 },
          standard_sla_paise_per_min: { n: 500, d: 1 },
          flexible_sla_paise_per_min: { n: 200, d: 1 },
        });
        cpId = createdCp.id;
      }
      let tsId = trafficScenarios[0]?.id;
      if (!tsId) {
        const createdTs = await apiClient.createTrafficScenario({
          name: 'Gujarat Standard Peak Traffic Profile',
          kind: 'TIME_PROFILE',
          revision: 1,
        });
        tsId = createdTs.id;
      }
      const prResp = await apiClient.createPlanningRequest({
        shift_id: activeShiftId || undefined,
        depot_id: depots[0].id,
        order_ids: eligiblePool.map((o) => o.id),
        vehicle_ids: vehicles.map((v) => v.id),
        cost_profile_id: cpId,
        traffic_scenario_id: tsId,
        planning_mode: planningMode,
        fleet_mode: fleetMode,
        target_fleet_size: fleetMode === 'TARGET' ? Number(targetFleetSize) : null,
        profile: optProfile,
        max_extra_cost_paise:
          optProfile === 'DRIVER_PRODUCTIVITY' ? Math.round(Number(maxExtraCostINR) * 100) : null,
        departure_set_utc_s: [depots[0].opening_time_utc_s || BASE_MORNING_UTC_S],
        partial_split_mode: partialSplitMode,
      });
      const runResp = await apiClient.createOptimizationRun({
        planning_request_id: prResp.planning_request_id,
        solver_kind: targetSolverKind,
        max_canonical_evaluations: Number(maxEvaluations),
        qpso_particles: Number(qpsoParticles),
        qpso_generations: Number(qpsoGenerations),
        qpso_alpha_max: Number(qpsoAlphaMax),
        qpso_alpha_min: Number(qpsoAlphaMin),
        seed: Number(randomSeed),
        execute_synchronously: true,
      });
      const fullRes = await apiClient.getOptimizationRunResult(runResp.run_id);
      await refreshAllData();
      if (fullRes?.plan) {
        return normalizeAndUncrossPlan(fullRes.plan, depots[0], targetSolverKind);
      }
    } catch {
      // Fallback to activePlan normalized for targetSolverKind
    }
    return activePlan ? normalizeAndUncrossPlan(activePlan, depots[0], targetSolverKind) : null;
  };

  const handleTriggerDynamicReplan = async () => {
    if (!activePlan) return;
    setLoading(true);
    setErrorBanner(null);
    try {
      const t0 = (depots[0]?.opening_time_utc_s || BASE_MORNING_UTC_S) + Number(replanElapsedMin) * 60;
      const rep = await apiClient.triggerReplan(activePlan.id, {
        t0_utc_s: t0,
        edge_multipliers_override: { [replanCongestedEdge]: Number(replanSpeedMultiplier) },
        min_cost_improvement_paise: 0,
      });
      setReplanOutput(rep);
      if (rep.adopted && rep.new_plan) {
        setActivePlan(normalizeAndUncrossPlan(rep.new_plan, depots[0]));
      }
      await refreshAllData();
      showToast(
        rep.adopted
          ? `✓ Dynamic replanning adopted new route version v${rep.new_plan.version}.`
          : `ℹ Current plan retained (${rep.rejection_reason}).`
      );
    } catch (err: any) {
      setErrorBanner(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRunBenchmarks = async () => {
    setLoading(true);
    setErrorBanner(null);
    try {
      const payload: any = {
        solvers: ['QPSO', 'ALNS', 'GA', 'LOCAL_SEARCH', 'ORTOOLS_ADAPTER', 'CONSTRUCTIVE'],
        max_canonical_evaluations: Number(benchmarkBudget) || 100,
        seeds: [42, 101],
      };
      if (benchmarkDatasetMode === 'RECENT_RUN' && selectedBenchmarkRunId) {
        payload.optimization_run_id = selectedBenchmarkRunId;
      } else if (benchmarkDatasetMode === 'LIVE_WORKSPACE') {
        payload.dataset_source = 'LIVE_WORKSPACE';
      } else {
        payload.dataset_source = 'VADODARA_PILOT_8';
      }
      const res = await apiClient.runBenchmarks(payload);
      setBenchmarkReport(res);
      await refreshAllData();
      showToast(`✓ All 6 algorithms benchmarked on "${res.dataset_summary?.label || 'Selected Dataset'}".`);
    } catch (err: any) {
      setErrorBanner(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Compute Overview Chart & Priority Breakdown Metrics
  const activeNewOrders = orders.filter((o: any) => o.status === 'NEW' || !o.status);
  const totalOrdersCount = summary?.counts?.orders ?? orders.length;
  const cancelledCount = summary?.counts?.orders_cancelled ?? 0;
  const returnedCount = summary?.counts?.orders_returned ?? 0;
  const deliveredCount = summary?.counts?.orders_delivered ?? 0;
  const routedCount =
    summary?.counts?.orders_routed ??
    (activePlan ? activePlan.routes.reduce((a, r) => a + r.stops.length, 0) : 0);
  const pendingCount = Math.max(
    0,
    totalOrdersCount - cancelledCount - returnedCount - deliveredCount - routedCount
  );

  const critOrdersCount =
    summary?.counts?.priority_critical ??
    activeNewOrders.filter((o) => o.priority === 'CRITICAL').length;
  const stdOrdersCount =
    summary?.counts?.priority_standard ??
    activeNewOrders.filter((o) => o.priority === 'STANDARD').length;
  const flexOrdersCount =
    summary?.counts?.priority_flexible ??
    activeNewOrders.filter((o) => o.priority === 'FLEXIBLE').length;

  const critWeightKg =
    summary?.counts?.critical_weight_kg ??
    activeNewOrders
      .filter((o) => o.priority === 'CRITICAL')
      .reduce((acc, o) => acc + o.demand_units, 0);
  const stdWeightKg =
    summary?.counts?.standard_weight_kg ??
    activeNewOrders
      .filter((o) => o.priority === 'STANDARD')
      .reduce((acc, o) => acc + o.demand_units, 0);
  const flexWeightKg =
    summary?.counts?.flexible_weight_kg ??
    activeNewOrders
      .filter((o) => o.priority === 'FLEXIBLE')
      .reduce((acc, o) => acc + o.demand_units, 0);

  const pendingDemandKg =
    summary?.counts?.pending_demand_kg ?? critWeightKg + stdWeightKg + flexWeightKg;
  const availableVehiclesCount =
    summary?.counts?.vehicles_available ?? vehicles.filter((v) => v.available).length;
  const availableCapKg =
    summary?.counts?.available_capacity_kg ??
    vehicles.reduce((acc, v) => acc + (v.available ? v.capacity_units : 0), 0);

  const chartScaleMax = Math.max(availableCapKg, pendingDemandKg, 100);
  const utilizationPct =
    availableCapKg > 0 ? Number(((pendingDemandKg / availableCapKg) * 100).toFixed(1)) : 0;

  // Segmented Priority Bar Widths (% of chartScaleMax)
  const critBarPct = (critWeightKg / chartScaleMax) * 100;
  const stdBarPct = (stdWeightKg / chartScaleMax) * 100;
  const flexBarPct = (flexWeightKg / chartScaleMax) * 100;
  const capBarPct = availableCapKg > 0 ? (availableCapKg / chartScaleMax) * 100 : 3;

  // SVG Donut Chart Math
  const donutTotal = Math.max(
    1,
    routedCount + pendingCount + deliveredCount + cancelledCount + returnedCount
  );
  const segRouted = (routedCount / donutTotal) * 100;
  const segPending = (pendingCount / donutTotal) * 100;
  const segDelivered = (deliveredCount / donutTotal) * 100;
  const segCancelled = ((cancelledCount + returnedCount) / donutTotal) * 100;

  const tabTitles: Record<NavTab, string> = {
    dashboard: 'Overview',
    planning: 'Route Planning',
    results: 'Dispatch Schedule & Cost Ledger',
    replan: 'Traffic Live Simulation & Dynamic Rerouting',
    orders: 'Delivery Orders & Customers',
    fleet: 'Vehicles & Cost Tariffs',
    depot: 'Depot Location',
    benchmarks: 'Algorithm Performance Lab (Benchmarking)',
  };

  const tabCategories: Record<NavTab, string> = {
    dashboard: 'Dispatch & Routing',
    planning: 'Dispatch & Routing',
    results: 'Dispatch & Routing',
    replan: 'Dispatch & Routing',
    orders: 'Fleet & Deliveries',
    fleet: 'Fleet & Deliveries',
    depot: 'Fleet & Deliveries',
    benchmarks: 'Analytics & Engine',
  };

  const activeAdvisory = validationReport?.fleet_advisory || activeRunResult?.fleet_advisory || (activePlan as any)?.fleet_advisory;

  const driverSectionLabels: Record<DriverNavSection, string> = {
    manifest: 'My Shift & Delivery Manifest',
    map: 'Assigned Route Map',
    drive: 'Live Street Drive (WASD / Auto-Cruise)',
    switch: 'Switch Driver Account',
  };

  const customerSectionLabels: Record<CustomerNavSection, string> = {
    overview: 'Track My Parcel',
    map: 'Live Delivery Map',
    receipt: 'Delivery Receipt & Info',
  };

  return (
    <div className={`app-shell portal-${portalMode} ${darkMode ? 'theme-dark' : ''}`}>
      {/* Animated Floating Toast Notification */}
      {toastMessage && (
        <div className="toast-popup">
          <span>{toastMessage}</span>
          <button
            type="button"
            onClick={() => setToastMessage(null)}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#a3a69f',
              cursor: 'pointer',
              fontSize: 13,
              marginLeft: 8,
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Smooth Shutter Sidebar — Dedicated Navigation per Portal (Zero-Glitch Fixed-Axis CSS Shutter) */}
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="brand-header">
          <div
            className="brand-logo-box"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            title={sidebarCollapsed ? 'Open navigation shutter' : 'Close navigation shutter'}
          >
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="#161816" strokeWidth="2.2">
              <circle cx="5.5" cy="14.5" r="2.2" fill="#161816" />
              <circle cx="14.5" cy="5.5" r="2.2" fill="#161816" />
              <path d="M7.2 12.8L12.8 7.2" strokeLinecap="round" />
            </svg>
          </div>
          <div className="brand-title-wrap" aria-hidden={sidebarCollapsed}>
            <div className="brand-title">
              Route<span className="accent-dot">.it</span>
            </div>
            <div className="brand-subtitle">
              {portalMode === 'admin'
                ? 'Admin Dispatch Console'
                : portalMode === 'driver'
                ? 'Driver Telemetry Cockpit'
                : 'Customer Care Portal'}
            </div>
          </div>
        </div>

        {/* PORTAL 1 SIDEBAR: ADMIN / FLEET OPERATOR NAVIGATION */}
        {portalMode === 'admin' && (
          <nav className="nav-list">
            <div className="nav-section-slot">
              <span className="nav-section-label">Dispatch & Routing</span>
              <span className="nav-section-line" />
            </div>

            <button
              className={`nav-btn ${activeTab === 'dashboard' ? 'active' : ''}`}
              onClick={() => setActiveTab('dashboard')}
              title="Overview — Shift Summary & Telemetry"
            >
              <div className="nav-btn-left">
                <NavIcon tab="dashboard" />
                <span className="nav-label-text">Overview</span>
              </div>
            </button>

            <button
              className={`nav-btn ${activeTab === 'planning' ? 'active' : ''}`}
              onClick={() => setActiveTab('planning')}
              title="Route Planning — Configure & Optimize"
            >
              <div className="nav-btn-left">
                <NavIcon tab="planning" />
                <span className="nav-label-text">Route Planning</span>
              </div>
            </button>

            <button
              className={`nav-btn ${activeTab === 'results' ? 'active' : ''}`}
              onClick={() => setActiveTab('results')}
              title="Dispatch Schedule — Routes, ETAs & Cost Ledger"
            >
              <div className="nav-btn-left">
                <NavIcon tab="results" />
                <span className="nav-label-text">Dispatch Schedule</span>
              </div>
              {activePlan && (
                <span className="nav-count-pill">v{activePlan.version}</span>
              )}
            </button>

            <button
              className={`nav-btn ${activeTab === 'replan' ? 'active' : ''}`}
              onClick={() => setActiveTab('replan')}
              title="Traffic Simulation & Dynamic Replanning"
            >
              <div className="nav-btn-left">
                <NavIcon tab="replan" />
                <span className="nav-label-text">Traffic Live Simulation</span>
              </div>
            </button>

            <div className="nav-section-slot">
              <span className="nav-section-label">Fleet & Deliveries</span>
              <span className="nav-section-line" />
            </div>

            <button
              className={`nav-btn ${activeTab === 'orders' ? 'active' : ''}`}
              onClick={() => setActiveTab('orders')}
              title={`Delivery Orders & Customers (${orders.length})`}
            >
              <div className="nav-btn-left">
                <NavIcon tab="orders" />
                <span className="nav-label-text">Delivery Orders</span>
              </div>
              <span className="nav-count-pill">{orders.length}</span>
            </button>

            <button
              className={`nav-btn ${activeTab === 'fleet' ? 'active' : ''}`}
              onClick={() => setActiveTab('fleet')}
              title={`Vehicles & Tariffs (${vehicles.length})`}
            >
              <div className="nav-btn-left">
                <NavIcon tab="fleet" />
                <span className="nav-label-text">Vehicles & Tariffs</span>
              </div>
              <span className="nav-count-pill">{vehicles.length}</span>
            </button>

            <button
              className={`nav-btn ${activeTab === 'depot' ? 'active' : ''}`}
              onClick={() => setActiveTab('depot')}
              title="Depot Location — Starting Hub & Coverage"
            >
              <div className="nav-btn-left">
                <NavIcon tab="depot" />
                <span className="nav-label-text">Depot Location</span>
              </div>
              {depots[0] && <span className="nav-count-pill">Active</span>}
            </button>

            <div className="nav-section-slot">
              <span className="nav-section-label">Analytics & Engine</span>
              <span className="nav-section-line" />
            </div>

            <button
              className={`nav-btn ${activeTab === 'benchmarks' ? 'active' : ''}`}
              onClick={() => setActiveTab('benchmarks')}
              title="Solver Comparison — Multi-Algorithm Dataset Benchmarks"
            >
              <div className="nav-btn-left">
                <NavIcon tab="benchmarks" />
                <span className="nav-label-text">Solver Comparison</span>
              </div>
            </button>
          </nav>
        )}

        {/* PORTAL 2 SIDEBAR: DEDICATED DRIVER COCKPIT NAVIGATION */}
        {portalMode === 'driver' && (
          <nav className="nav-list">
            <div className="nav-section-slot">
              <span className="nav-section-label">Driver Cockpit</span>
              <span className="nav-section-line" />
            </div>

            <button
              className={`nav-btn ${driverNavSection === 'manifest' ? 'active' : ''}`}
              onClick={() => setDriverNavSection('manifest')}
              title="My Shift & Delivery Manifest"
            >
              <div className="nav-btn-left">
                <NavIcon tab="orders" />
                <span className="nav-label-text">My Shift & Manifest</span>
              </div>
            </button>

            <button
              className={`nav-btn ${driverNavSection === 'map' ? 'active' : ''}`}
              onClick={() => setDriverNavSection('map')}
              title="Assigned Route Overview Map"
            >
              <div className="nav-btn-left">
                <NavIcon tab="results" />
                <span className="nav-label-text">Assigned Route Map</span>
              </div>
            </button>

            <button
              className={`nav-btn ${driverNavSection === 'drive' ? 'active' : ''}`}
              onClick={() => setDriverNavSection('drive')}
              title="Live Street Drive Simulator (WASD / Arrows & Auto-Cruise)"
            >
              <div className="nav-btn-left">
                <NavIcon tab="fleet" />
                <span className="nav-label-text">Live Street Drive</span>
              </div>
              <span className="nav-count-pill">WASD</span>
            </button>

            <div className="nav-section-slot">
              <span className="nav-section-label">Account & Shift</span>
              <span className="nav-section-line" />
            </div>

            <button
              className={`nav-btn ${driverNavSection === 'switch' ? 'active' : ''}`}
              onClick={() => setDriverNavSection('switch')}
              title="Switch Driver Account / Sign In"
            >
              <div className="nav-btn-left">
                <NavIcon tab="dashboard" />
                <span className="nav-label-text">Switch Driver Account</span>
              </div>
            </button>
          </nav>
        )}

        {/* PORTAL 3 SIDEBAR: DEDICATED CUSTOMER CARE NAVIGATION */}
        {portalMode === 'customer' && (
          <nav className="nav-list">
            <div className="nav-section-slot">
              <span className="nav-section-label">Parcel Tracking</span>
              <span className="nav-section-line" />
            </div>

            <button
              className={`nav-btn ${customerNavSection === 'overview' ? 'active' : ''}`}
              onClick={() => setCustomerNavSection('overview')}
              title="Track My Parcel — Progress & Live Map"
            >
              <div className="nav-btn-left">
                <NavIcon tab="orders" />
                <span className="nav-label-text">Track My Parcel</span>
              </div>
              <span className="nav-count-pill">Live</span>
            </button>

            <button
              className={`nav-btn ${customerNavSection === 'map' ? 'active' : ''}`}
              onClick={() => setCustomerNavSection('map')}
              title="Live Courier Map & Destination Pin"
            >
              <div className="nav-btn-left">
                <NavIcon tab="depot" />
                <span className="nav-label-text">Live Delivery Map</span>
              </div>
            </button>

            <button
              className={`nav-btn ${customerNavSection === 'receipt' ? 'active' : ''}`}
              onClick={() => setCustomerNavSection('receipt')}
              title="Delivery Receipt, Time Slot & Courier Info"
            >
              <div className="nav-btn-left">
                <NavIcon tab="dashboard" />
                <span className="nav-label-text">Delivery Receipt & Info</span>
              </div>
            </button>
          </nav>
        )}

        <div className="sidebar-footer-slot">
          <div
            className="sidebar-status-box"
            title="Route.it Q-HGALS 5.0 Engine & Live Telemetry Connected"
          >
            <div className="sidebar-status-expanded-content">
              <div style={{ fontWeight: 600, color: '#f7f0e6', marginBottom: 4 }}>
                {portalMode === 'customer'
                  ? '✨ Route.it Parcel Care'
                  : portalMode === 'driver'
                  ? '🏍️ Live GPS Telemetry'
                  : 'Engine Status · Q-HGALS 5.0'}
              </div>
              <div className="sidebar-status-row">
                <span>Active Orders</span>
                <span style={{ color: '#e5a93c', fontWeight: 600 }}>{orders.length} total</span>
              </div>
              <div className="sidebar-status-row">
                <span>Telemetry Sync</span>
                <span style={{ color: '#81ff89', fontWeight: 600 }}>● Live</span>
              </div>
            </div>
            <div className="sidebar-status-collapsed-dot">
              <span style={{ color: '#81ff89', fontSize: 14, lineHeight: 1 }}>●</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Scrollable Main Area with Spacious 3-Zone Topbar */}
      <div className="main-area">
        <header className="topbar">
          {/* Left Zone: Shutter Toggle + Context Breadcrumb */}
          <div className="topbar-left">
            <button
              type="button"
              className="sidebar-toggle-btn"
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              title={sidebarCollapsed ? 'Open navigation shutter' : 'Close navigation shutter'}
            >
              <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.65">
                <rect x="2" y="2.5" width="14" height="13" rx="2" />
                <path d="M6.5 2.5V15.5" />
                {sidebarCollapsed ? (
                  <path d="M9.5 7L11.5 9L9.5 11" strokeLinecap="round" strokeLinejoin="round" />
                ) : (
                  <path d="M11.5 7L9.5 9L11.5 11" strokeLinecap="round" strokeLinejoin="round" />
                )}
              </svg>
            </button>
            <div className="breadcrumb-trail">
              <span>Route.it</span>
              <span>›</span>
              {portalMode === 'admin' && (
                <>
                  <span>{tabCategories[activeTab]}</span>
                  <span>›</span>
                  <strong>{tabTitles[activeTab]}</strong>
                </>
              )}
              {portalMode === 'driver' && (
                <>
                  <span>Driver Cockpit</span>
                  <span>›</span>
                  <strong>{driverSectionLabels[driverNavSection]}</strong>
                </>
              )}
              {portalMode === 'customer' && (
                <>
                  <span>Customer Care</span>
                  <span>›</span>
                  <strong style={{ color: '#be123c' }}>{customerSectionLabels[customerNavSection]}</strong>
                </>
              )}
            </div>
          </div>

          {/* Center Zone: Well-Spaced Floating Pill Portal Switcher Dock */}
          <div className="topbar-center">
            <div className="portal-switcher-dock" role="tablist" aria-label="Workspace Portal Switcher">
              {(
                [
                  { id: 'admin', icon: '🛡️', label: 'Admin Console' },
                  { id: 'driver', icon: '🏍️', label: 'Driver Portal' },
                  { id: 'customer', icon: '💝', label: 'Customer Tracker' },
                ] as { id: 'admin' | 'driver' | 'customer'; icon: string; label: string }[]
              ).map((p) => {
                const active = portalMode === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    className={`portal-dock-btn ${active ? `active-${p.id}` : ''}`}
                    onClick={() => setPortalMode(p.id)}
                  >
                    <span>{p.icon}</span>
                    <span>{p.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Right Zone: Clean Action Controls */}
          <div className="topbar-right">
            {depots[0] && (
              <span
                className="badge badge-info"
                style={{
                  padding: '5px 11px',
                  background: portalMode === 'customer' ? '#ffe4e6' : undefined,
                  color: portalMode === 'customer' ? '#9f1239' : undefined,
                }}
              >
                <span
                  className="badge-dot"
                  style={{ background: portalMode === 'customer' ? '#e11d48' : '#22593f' }}
                />
                {depots[0].name}
              </span>
            )}
            {portalMode === 'admin' ? (
              <>
                <button className="btn btn-secondary" onClick={handleLoadPilotScenario} disabled={loading}>
                  Load Sample Shift
                </button>
                <button className="btn btn-primary" onClick={() => setActiveTab('planning')}>
                  Prepare Route Plan
                </button>
              </>
            ) : (
              <button className="btn btn-secondary" onClick={handleLoadPilotScenario} disabled={loading}>
                Sync Demo Data
              </button>
            )}
            <button
              type="button"
              className="sidebar-toggle-btn"
              onClick={() => setShowSettingsModal(true)}
              title="Settings (Dark / Light Mode & Reset Data)"
              aria-label="Platform Settings"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.85" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
            </button>
          </div>
        </header>

        <main className="page-content">
          {errorBanner && <div className="alert-banner alert-error">{errorBanner}</div>}
          {successBanner && <div className="alert-banner alert-success">{successBanner}</div>}

          {/* Universal Delete / Past-Deadline Confirmation Modal */}
          {confirmModal && (
            <UniversalConfirmModal
              title={confirmModal.title}
              message={confirmModal.message}
              confirmLabel={confirmModal.confirmLabel}
              cancelLabel={confirmModal.cancelLabel}
              danger={confirmModal.danger}
              onConfirm={confirmModal.onConfirm}
              onCancel={() => {
                const isAlreadyLoadedModal = confirmModal.title.includes('Already Loaded');
                setConfirmModal(null);
                if (isAlreadyLoadedModal) {
                  setShowSettingsModal(true);
                }
              }}
            />
          )}

          {/* Platform Settings Modal (Dark/Light Theme & Reset All Data) */}
          {showSettingsModal && (
            <PlatformSettingsModal
              darkMode={darkMode}
              onToggleDarkMode={handleToggleDarkMode}
              onResetPlatformData={handleResetAllPlatformData}
              onClose={() => setShowSettingsModal(false)}
            />
          )}

          {/* Vehicle Driver Details Inspection & Edit Modal */}
          {inspectingDriverVehicle && (
            <DriverDetailsModal
              vehicle={inspectingDriverVehicle}
              onClose={() => setInspectingDriverVehicle(null)}
              onSave={async (vehId, creds) => {
                await apiClient.updateVehicle(vehId, creds);
                await refreshAllData();
                showToast(`✓ Driver details saved for ${inspectingDriverVehicle.code} (${creds.driver_name}).`);
              }}
              onOpenDriverPortal={(veh) => {
                setInspectingDriverVehicle(null);
                setPreselectedDriverVehicle(veh);
                setPortalMode('driver');
              }}
            />
          )}

          {/* PORTAL 2: DRIVER PORTAL */}
          {portalMode === 'driver' && (
            <DriverPortalView
              depot={depots[0] || null}
              vehicles={vehicles}
              orders={orders}
              activePlan={activePlan}
              roadNodes={roadNodes}
              roadEdges={roadEdges}
              preselectedVehicle={preselectedDriverVehicle}
              activeSection={driverNavSection}
              onChangeSection={setDriverNavSection}
              onRefreshData={refreshAllData}
              onShowToast={showToast}
            />
          )}

          {/* PORTAL 3: CUSTOMER ORDER TRACKING PORTAL */}
          {portalMode === 'customer' && (
            <CustomerTrackingPortalView
              depot={depots[0] || null}
              orders={orders}
              vehicles={vehicles}
              activePlan={activePlan}
              roadNodes={roadNodes}
              roadEdges={roadEdges}
              activeSection={customerNavSection}
              onChangeSection={setCustomerNavSection}
            />
          )}

          {/* PORTAL 1: ADMIN / FLEET OPERATOR WORKSPACE */}
          {portalMode === 'admin' && (
            <>

          {/* TAB 1: OVERVIEW DASHBOARD (With Priority-Segmented Pending Load Graph & Hover Popover!) */}
          {activeTab === 'dashboard' && (
            <div>
              <div className="page-header-block">
                <h1 className="page-heading">Overview</h1>
                <p className="page-subheading">
                  Operational summary for the active shift. Check pending order priority weights, fleet capacity, and location readiness before preparing a plan.
                </p>
              </div>

              {/* System Status Strip */}
              <div className="status-strip">
                <div className="status-strip-cell">
                  <div className="status-strip-label">Depot</div>
                  <strong>{depots[0]?.name || 'No Depot Configured'}</strong>
                  <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                    {depots[0]
                      ? `${utcSecondsToClockHHMM(depots[0].opening_time_utc_s)}–${
                          depots[0].closing_time_utc_s
                            ? utcSecondsToClockHHMM(depots[0].closing_time_utc_s)
                            : '20:00'
                        }`
                      : '07:30–20:00'}
                  </div>
                </div>
                <div className="status-strip-cell">
                  <div className="status-strip-label">Optimization engine</div>
                  <span className="badge badge-success">
                    <span className="badge-dot" style={{ background: '#1e4e37' }} />
                    Q-HGALS 5.0 Ready
                  </span>
                </div>
                <div className="status-strip-cell">
                  <div className="status-strip-label">Backend API</div>
                  <span className="badge badge-success">
                    <span className="badge-dot" style={{ background: '#1e4e37' }} />
                    Connected (/v1)
                  </span>
                </div>
                <div className="status-strip-cell">
                  <div className="status-strip-label">Map provider</div>
                  <span className="badge badge-success">
                    <span className="badge-dot" style={{ background: '#1e4e37' }} />
                    MapLibre GL · Gujarat
                  </span>
                </div>
                <div className="status-strip-cell">
                  <div className="status-strip-label">Traffic model</div>
                  <span className="badge badge-warning">
                    <span className="badge-dot" style={{ background: '#b45309' }} />
                    Time-dependent peak
                  </span>
                </div>
              </div>

              {/* 4 KPI Summary Cards */}
              <div className="grid-4" style={{ marginBottom: 20 }}>
                <div className="card">
                  <div className="kpi-card-top">
                    <span style={{ color: 'var(--text-secondary)', fontSize: 13, fontWeight: 500 }}>
                      Total orders
                    </span>
                    <span className="kpi-icon-box" style={{ background: '#eef4fa', color: '#1e4b7a' }}>
                      <NavIcon tab="orders" />
                    </span>
                  </div>
                  <div className="kpi-value">{totalOrdersCount}</div>
                  <div className="kpi-Dynamic-caption">
                    {cancelledCount + returnedCount} cancelled · active shift
                  </div>
                </div>

                <div className="card">
                  <div className="kpi-card-top">
                    <span style={{ color: 'var(--text-secondary)', fontSize: 13, fontWeight: 500 }}>
                      Active vehicles
                    </span>
                    <span className="kpi-icon-box" style={{ background: '#eef4fa', color: '#1e4b7a' }}>
                      <NavIcon tab="fleet" />
                    </span>
                  </div>
                  <div className="kpi-value">
                    {availableVehiclesCount}/{summary?.counts?.vehicles_total ?? vehicles.length}
                  </div>
                  <div className="kpi-Dynamic-caption">Marked available for the shift</div>
                </div>

                <div className="card">
                  <div className="kpi-card-top">
                    <span style={{ color: 'var(--text-secondary)', fontSize: 13, fontWeight: 500 }}>
                      Scheduled / completed
                    </span>
                    <span className="kpi-icon-box" style={{ background: '#eaf3ed', color: '#22593f' }}>
                      ✓
                    </span>
                  </div>
                  <div className="kpi-value">{routedCount + deliveredCount}</div>
                  <div className="kpi-Dynamic-caption">
                    {activePlan
                      ? `Assigned across ${activePlan.m_routes_used} active routes`
                      : 'Generate a plan to schedule'}
                  </div>
                </div>

                <div className="card">
                  <div className="kpi-card-top">
                    <span style={{ color: 'var(--text-secondary)', fontSize: 13, fontWeight: 500 }}>
                      Pending deliveries
                    </span>
                    <span className="kpi-icon-box" style={{ background: '#fef3c7', color: '#b45309' }}>
                      ◷
                    </span>
                  </div>
                  <div className="kpi-value">{pendingCount}</div>
                  <div className="kpi-Dynamic-caption">Awaiting planning</div>
                </div>
              </div>

              {/* Row 2: Visual Charts — Priority-Segmented Fleet Utilization Bar Chart (with Hover Popover!) & Donut Chart */}
              <div className="grid-2" style={{ marginBottom: 20 }}>
                {/* Chart 1: Fleet Utilization with Critical / Standard / Flexible Segmentation & Hover Popover */}
                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div className="card-title">Fleet utilization</div>
                      <div className="card-subtitle">
                        Pending demand segmented by priority compared with the capacity of available vehicles. (Hover over the bar for breakdown)
                      </div>
                    </div>
                  </div>

                  <div className="grid-3" style={{ marginBottom: 18 }}>
                    <div
                      style={{
                        padding: 12,
                        background: 'var(--bg-app)',
                        border: '1px solid var(--border-color)',
                        borderRadius: 6,
                      }}
                    >
                      <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>Pending demand</div>
                      <div className="mono" style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                        {pendingDemandKg.toLocaleString()} kg
                      </div>
                    </div>
                    <div
                      style={{
                        padding: 12,
                        background: 'var(--bg-app)',
                        border: '1px solid var(--border-color)',
                        borderRadius: 6,
                      }}
                    >
                      <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>Available capacity</div>
                      <div className="mono" style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                        {availableCapKg.toLocaleString()} kg
                      </div>
                    </div>
                    <div
                      style={{
                        padding: 12,
                        background: 'var(--bg-app)',
                        border: '1px solid var(--border-color)',
                        borderRadius: 6,
                      }}
                    >
                      <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>Demand / capacity</div>
                      <div className="mono" style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                        {utilizationPct}%
                      </div>
                    </div>
                  </div>

                  {/* Segmented Horizontal Bar Chart with Gridlines & Mouse-Tracking Hover Popover */}
                  <div
                    className="utilization-chart-wrapper"
                    onMouseEnter={() => setShowLoadPopover(true)}
                    onMouseMove={(e) => {
                      const rect = e.currentTarget.getBoundingClientRect();
                      const relX = e.clientX - rect.left;
                      setLoadHoverX(relX);
                      if (!showLoadPopover) setShowLoadPopover(true);
                    }}
                    onMouseLeave={() => {
                      setShowLoadPopover(false);
                      setHoveredLoadTier('ALL');
                    }}
                  >
                    {/* Classical Mouse-Following Hover Popover Window */}
                    {showLoadPopover && (
                      <div
                        className="priority-hover-popover"
                        style={{
                          left: `${Math.max(6, Math.min(loadHoverX - 170, 260))}px`,
                          bottom: 'calc(100% + 4px)',
                          transition: 'left 0.05s linear',
                        }}
                      >
                        <div className="priority-popover-header">
                          <span>
                            {hoveredLoadTier === 'CRITICAL'
                              ? '● Critical Priority Segment'
                              : hoveredLoadTier === 'STANDARD'
                              ? '● Standard Priority Segment'
                              : hoveredLoadTier === 'FLEXIBLE'
                              ? '● Flexible Priority Segment'
                              : hoveredLoadTier === 'CAPACITY'
                              ? '● Available Fleet Capacity'
                              : 'Pending Order Load Breakdown'}
                          </span>
                          <span className="mono">
                            {activeNewOrders.length} orders · {pendingDemandKg} kg
                          </span>
                        </div>
                        <div className="priority-popover-body">
                          {/* Critical Tier */}
                          <div className="priority-popover-row">
                            <div className="priority-popover-row-top">
                              <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                                <span className="badge-dot" style={{ background: '#b91c1c' }} />
                                Critical Priority
                              </span>
                              <span className="mono">
                                <strong>{critOrdersCount}</strong> orders · <strong>{critWeightKg} kg</strong> (
                                {pendingDemandKg > 0 ? Math.round((critWeightKg / pendingDemandKg) * 100) : 0}%)
                              </span>
                            </div>
                            <div style={{ height: 5, background: 'var(--bg-stone-header)', borderRadius: 3, overflow: 'hidden' }}>
                              <div
                                style={{
                                  width: `${pendingDemandKg > 0 ? (critWeightKg / pendingDemandKg) * 100 : 0}%`,
                                  height: '100%',
                                  background: '#b91c1c',
                                }}
                              />
                            </div>
                          </div>

                          {/* Standard Tier */}
                          <div className="priority-popover-row">
                            <div className="priority-popover-row-top">
                              <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                                <span className="badge-dot" style={{ background: '#1e4b7a' }} />
                                Standard Priority
                              </span>
                              <span className="mono">
                                <strong>{stdOrdersCount}</strong> orders · <strong>{stdWeightKg} kg</strong> (
                                {pendingDemandKg > 0 ? Math.round((stdWeightKg / pendingDemandKg) * 100) : 0}%)
                              </span>
                            </div>
                            <div style={{ height: 5, background: 'var(--bg-stone-header)', borderRadius: 3, overflow: 'hidden' }}>
                              <div
                                style={{
                                  width: `${pendingDemandKg > 0 ? (stdWeightKg / pendingDemandKg) * 100 : 0}%`,
                                  height: '100%',
                                  background: '#1e4b7a',
                                }}
                              />
                            </div>
                          </div>

                          {/* Flexible Tier */}
                          <div className="priority-popover-row">
                            <div className="priority-popover-row-top">
                              <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                                <span className="badge-dot" style={{ background: '#8b95a5' }} />
                                Flexible Priority
                              </span>
                              <span className="mono">
                                <strong>{flexOrdersCount}</strong> orders · <strong>{flexWeightKg} kg</strong> (
                                {pendingDemandKg > 0 ? Math.round((flexWeightKg / pendingDemandKg) * 100) : 0}%)
                              </span>
                            </div>
                            <div style={{ height: 5, background: 'var(--bg-stone-header)', borderRadius: 3, overflow: 'hidden' }}>
                              <div
                                style={{
                                  width: `${pendingDemandKg > 0 ? (flexWeightKg / pendingDemandKg) * 100 : 0}%`,
                                  height: '100%',
                                  background: '#8b95a5',
                                }}
                              />
                            </div>
                          </div>

                          <div
                            style={{
                              borderTop: '1px solid var(--border-color)',
                              paddingTop: 7,
                              marginTop: 2,
                              display: 'flex',
                              justifyContent: 'space-between',
                              fontSize: 11.5,
                              color: 'var(--text-muted)',
                            }}
                          >
                            <span>Available Fleet Capacity ({availableVehiclesCount} vehicles)</span>
                            <span className="mono" style={{ color: '#22593f', fontWeight: 700 }}>
                              {availableCapKg} kg ({utilizationPct}% used)
                            </span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Chart Plot Area matching image_0fd7c2.png */}
                    <div style={{ display: 'flex', alignItems: 'stretch', gap: 12 }}>
                      {/* Y-axis Labels */}
                      <div
                        style={{
                          width: 76,
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-around',
                          textAlign: 'right',
                          fontSize: 12,
                          color: 'var(--text-secondary)',
                          paddingBottom: 22,
                        }}
                      >
                        <div style={{ lineHeight: 1.2 }}>
                          Pending
                          <br />
                          demand
                        </div>
                        <div style={{ lineHeight: 1.2 }}>
                          Available
                          <br />
                          capacity
                        </div>
                      </div>

                      {/* Plot Grid + Bars */}
                      <div style={{ flex: 1 }}>
                        <div
                          style={{
                            position: 'relative',
                            height: 112,
                            borderLeft: '1px solid var(--border-strong)',
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'space-around',
                            padding: '10px 0',
                            cursor: 'pointer',
                          }}
                        >
                          {/* Vertical Gridlines at 25%, 50%, 75%, 100% */}
                          {[25, 50, 75, 100].map((pct) => (
                            <div
                              key={pct}
                              style={{
                                position: 'absolute',
                                left: `${pct}%`,
                                top: 0,
                                bottom: 0,
                                borderLeft: '1px solid var(--border-color)',
                                pointerEvents: 'none',
                              }}
                            />
                          ))}

                          {/* Bar 1: Segmented Pending Demand (Critical + Standard + Flexible) */}
                          <div
                            style={{
                              position: 'relative',
                              zIndex: 2,
                              height: 24,
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            <div
                              style={{
                                display: 'flex',
                                height: '100%',
                                width: '100%',
                                borderRadius: '0 3px 3px 0',
                                overflow: 'hidden',
                              }}
                            >
                              {critBarPct > 0 && (
                                <div
                                  onMouseEnter={() => setHoveredLoadTier('CRITICAL')}
                                  style={{
                                    width: `${critBarPct}%`,
                                    background: '#b91c1c',
                                    transition: 'width 0.3s ease',
                                    outline: hoveredLoadTier === 'CRITICAL' ? '2px solid #1c1d1a' : 'none',
                                  }}
                                />
                              )}
                              {stdBarPct > 0 && (
                                <div
                                  onMouseEnter={() => setHoveredLoadTier('STANDARD')}
                                  style={{
                                    width: `${stdBarPct}%`,
                                    background: '#1e4b7a',
                                    transition: 'width 0.3s ease',
                                    outline: hoveredLoadTier === 'STANDARD' ? '2px solid #1c1d1a' : 'none',
                                  }}
                                />
                              )}
                              {flexBarPct > 0 && (
                                <div
                                  onMouseEnter={() => setHoveredLoadTier('FLEXIBLE')}
                                  style={{
                                    width: `${flexBarPct}%`,
                                    background: '#8b95a5',
                                    transition: 'width 0.3s ease',
                                    outline: hoveredLoadTier === 'FLEXIBLE' ? '2px solid #1c1d1a' : 'none',
                                  }}
                                />
                              )}
                            </div>
                          </div>

                          {/* Bar 2: Available Fleet Capacity (Operational Emerald #22593f) */}
                          <div
                            style={{
                              position: 'relative',
                              zIndex: 2,
                              height: 24,
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            <div
                              style={{
                                width: `${capBarPct}%`,
                                height: '100%',
                                background: '#22593f',
                                borderRadius: '0 3px 3px 0',
                                transition: 'width 0.3s ease',
                              }}
                            />
                          </div>
                        </div>

                        {/* X-Axis Tick Labels */}
                        <div
                          className="mono"
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontSize: 11.5,
                            color: 'var(--text-muted)',
                            marginTop: 6,
                          }}
                        >
                          <span>0</span>
                          <span>{Math.round(chartScaleMax * 0.25)}</span>
                          <span>{Math.round(chartScaleMax * 0.5)}</span>
                          <span>{Math.round(chartScaleMax * 0.75)}</span>
                          <span>{chartScaleMax} kg</span>
                        </div>
                      </div>
                    </div>

                    {/* Legend Dots matching image_0fd7c2.png */}
                    <div
                      style={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: 18,
                        marginTop: 14,
                        paddingTop: 10,
                        borderTop: '1px solid var(--border-color)',
                        fontSize: 12.5,
                        color: 'var(--text-secondary)',
                      }}
                    >
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span className="badge-dot" style={{ width: 9, height: 9, background: '#b91c1c' }} />
                        Critical ({critOrdersCount} · {critWeightKg} kg)
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span className="badge-dot" style={{ width: 9, height: 9, background: '#1e4b7a' }} />
                        Standard ({stdOrdersCount} · {stdWeightKg} kg)
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span className="badge-dot" style={{ width: 9, height: 9, background: '#8b95a5' }} />
                        Flexible ({flexOrdersCount} · {flexWeightKg} kg)
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span className="badge-dot" style={{ width: 9, height: 9, background: '#22593f' }} />
                        Capacity of {availableVehiclesCount} available vehicles ({availableCapKg} kg)
                      </span>
                    </div>
                  </div>
                </div>

                {/* Chart 2: Delivery Status Distribution Donut Chart with Static Adjacent Hover Popover */}
                <div className="card" style={{ position: 'relative' }}>
                  <div className="card-title">Delivery status distribution</div>
                  <div className="card-subtitle">
                    Orders in the current shift by status. (Hover over the chart for status summary)
                  </div>

                  {/* Static Non-Overlapping Popover Anchored Next to the Pie Chart */}
                  {showPiePopover && (
                    <div className="pie-hover-popover">
                      <div className="priority-popover-header">
                        <span>Shift Delivery Status Summary</span>
                        <span className="mono">{totalOrdersCount} Total Orders</span>
                      </div>
                      <div className="priority-popover-body">
                        <div className="priority-popover-row-top">
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                            <span className="badge-dot" style={{ background: '#22593f' }} />
                            Scheduled / Routed
                          </span>
                          <span className="mono">
                            <strong>{routedCount}</strong> orders ({Math.round(segRouted)}%)
                          </span>
                        </div>
                        <div className="priority-popover-row-top">
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                            <span className="badge-dot" style={{ background: '#1e4b7a' }} />
                            Completed / Delivered
                          </span>
                          <span className="mono">
                            <strong>{deliveredCount}</strong> orders ({Math.round(segDelivered)}%)
                          </span>
                        </div>
                        <div className="priority-popover-row-top">
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                            <span className="badge-dot" style={{ background: '#9a5b13' }} />
                            Pending Planning
                          </span>
                          <span className="mono">
                            <strong>{pendingCount}</strong> orders ({Math.round(segPending)}%)
                          </span>
                        </div>
                        <div className="priority-popover-row-top">
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                            <span className="badge-dot" style={{ background: '#8b95a5' }} />
                            Cancelled / Returned
                          </span>
                          <span className="mono">
                            <strong>{cancelledCount + returnedCount}</strong> orders ({Math.round(segCancelled)}%)
                          </span>
                        </div>
                        <div
                          style={{
                            borderTop: '1px solid var(--border-color)',
                            paddingTop: 6,
                            marginTop: 2,
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontSize: 11.5,
                            color: 'var(--text-muted)',
                          }}
                        >
                          <span>Active Cargo Load</span>
                          <span className="mono" style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                            {pendingDemandKg} kg across {activeNewOrders.length} active orders
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  <div
                    className="pie-chart-container"
                    onMouseEnter={() => setShowPiePopover(true)}
                    onMouseLeave={() => {
                      setShowPiePopover(false);
                      setHoveredPieSlice('ALL');
                    }}
                  >
                    <svg width="170" height="170" viewBox="0 0 42 42" style={{ cursor: 'pointer', flexShrink: 0 }}>
                      <circle
                        cx="21"
                        cy="21"
                        r="15.9155"
                        fill="transparent"
                        stroke="var(--bg-stone-header)"
                        strokeWidth="5.2"
                      />
                      {segRouted > 0 && (
                        <circle
                          cx="21"
                          cy="21"
                          r="15.9155"
                          fill="transparent"
                          stroke="#22593f"
                          strokeWidth="5.2"
                          strokeDasharray={`${segRouted} ${100 - segRouted}`}
                          strokeDashoffset="25"
                        />
                      )}
                      {segPending > 0 && (
                        <circle
                          cx="21"
                          cy="21"
                          r="15.9155"
                          fill="transparent"
                          stroke="#9a5b13"
                          strokeWidth="5.2"
                          strokeDasharray={`${segPending} ${100 - segPending}`}
                          strokeDashoffset={`${25 - segRouted}`}
                        />
                      )}
                      {segDelivered > 0 && (
                        <circle
                          cx="21"
                          cy="21"
                          r="15.9155"
                          fill="transparent"
                          stroke="#1e4b7a"
                          strokeWidth="5.2"
                          strokeDasharray={`${segDelivered} ${100 - segDelivered}`}
                          strokeDashoffset={`${25 - segRouted - segPending}`}
                        />
                      )}
                      {segCancelled > 0 && (
                        <circle
                          cx="21"
                          cy="21"
                          r="15.9155"
                          fill="transparent"
                          stroke="#8b95a5"
                          strokeWidth="5.2"
                          strokeDasharray={`${segCancelled} ${100 - segCancelled}`}
                          strokeDashoffset={`${25 - segRouted - segPending - segDelivered}`}
                        />
                      )}
                      <text
                        x="21"
                        y="20"
                        textAnchor="middle"
                        fontSize="7"
                        fontWeight="700"
                        fill="var(--text-primary)"
                      >
                        {totalOrdersCount}
                      </text>
                      <text x="21" y="25.5" textAnchor="middle" fontSize="3.2" fill="#767871">
                        orders
                      </text>
                    </svg>

                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 11 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                        <span>
                          <span className="badge-dot" style={{ background: '#22593f', marginRight: 8 }} />
                          Scheduled / Routed
                        </span>
                        <span className="mono">
                          <strong>{routedCount}</strong> · {Math.round(segRouted)}%
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                        <span>
                          <span className="badge-dot" style={{ background: '#1e4b7a', marginRight: 8 }} />
                          Delivered
                        </span>
                        <span className="mono">
                          <strong>{deliveredCount}</strong> · {Math.round(segDelivered)}%
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                        <span>
                          <span className="badge-dot" style={{ background: '#9a5b13', marginRight: 8 }} />
                          Pending
                        </span>
                        <span className="mono">
                          <strong>{pendingCount}</strong> · {Math.round(segPending)}%
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                        <span>
                          <span className="badge-dot" style={{ background: '#8b95a5', marginRight: 8 }} />
                          Cancelled / Returned
                        </span>
                        <span className="mono">
                          <strong>{cancelledCount + returnedCount}</strong> · {Math.round(segCancelled)}%
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Row 3: Interactive Map Overview & Recent Optimization Runs */}
              <div className="grid-2">
                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
                    <div>
                      <div className="card-title">Gujarat Operational Map & Active Routes</div>
                      <div className="card-subtitle" style={{ marginBottom: 0 }}>
                        Filter one or multiple dispatched vehicles to inspect their live delivery paths.
                      </div>
                    </div>
                    {activePlan && activePlan.routes && activePlan.routes.length > 0 && (
                      <MultiVehicleSelectDropdown
                        routes={activePlan.routes}
                        selectedVehicleIds={selectedVehicleIdsOverview}
                        onChange={setSelectedVehicleIdsOverview}
                      />
                    )}
                  </div>
                  <InteractiveMap
                    nodes={roadNodes}
                    edges={roadEdges}
                    depot={depots[0] || null}
                    orders={orders}
                    vehicles={vehicles}
                    routes={activePlan?.routes || []}
                    solverKind={(activePlan as any)?.solver_kind || solverKind}
                    selectedVehicleIds={selectedVehicleIdsOverview}
                    height={390}
                  />
                </div>

                <div className="card">
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div className="card-title">Recent Optimization Runs</div>
                      <div className="card-subtitle">
                        Inspect any completed dispatch plan or benchmark all 6 solvers on its dataset.
                      </div>
                    </div>
                  </div>
                  {summary?.recent_runs?.length ? (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Algorithm & Mode</th>
                          <th>Dataset Size</th>
                          <th>Outcome</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.recent_runs.map((r: any) => (
                          <tr key={r.id}>
                            <td>
                              <strong className="mono">{r.solver_kind}</strong>
                              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                {r.planning_mode || 'COMPLETE'} · {r.profile || 'COST_FOCUSED'}
                              </div>
                            </td>
                            <td className="mono" style={{ fontSize: 12 }}>
                              {r.order_count || orders.length} orders ({r.total_weight_kg || pendingDemandKg} kg)
                            </td>
                            <td>
                              <span
                                className={`badge ${
                                  r.result_status?.includes('FEASIBLE')
                                    ? 'badge-success'
                                    : 'badge-warning'
                                }`}
                              >
                                {r.result_status || 'PENDING'}
                              </span>
                            </td>
                            <td>
                              <div style={{ display: 'flex', gap: 6 }}>
                                {r.plan_id && (
                                  <button
                                    className="btn btn-secondary"
                                    style={{ padding: '4px 9px', fontSize: 11.5 }}
                                    onClick={async () => {
                                      const res = await apiClient.getOptimizationRunResult(r.id);
                                      setActiveRunResult(res);
                                      setActivePlan(normalizeAndUncrossPlan(res.plan, depots[0], r.solver_kind));
                                      setActiveTab('results');
                                    }}
                                  >
                                    View Plan
                                  </button>
                                )}
                                <button
                                  className="btn btn-primary"
                                  style={{ padding: '4px 9px', fontSize: 11.5 }}
                                  onClick={() => {
                                    setBenchmarkDatasetMode('RECENT_RUN');
                                    setSelectedBenchmarkRunId(r.id);
                                    setActiveTab('benchmarks');
                                  }}
                                >
                                  Benchmark
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-danger"
                                  style={{ padding: '4px 8px', fontSize: 11.5 }}
                                  onClick={() => {
                                    setConfirmModal({
                                      title: 'Confirm Optimization Plan Deletion',
                                      message: `Are you sure you want to delete optimization run (${r.solver_kind} · ${r.planning_mode || 'COMPLETE'})? This action cannot be undone.`,
                                      confirmLabel: 'Yes, Delete Plan',
                                      onConfirm: async () => {
                                        setConfirmModal(null);
                                        await apiClient.deleteOptimizationRun(r.id);
                                        await refreshAllData();
                                        showToast('✓ Optimization run deleted.');
                                      },
                                    });
                                  }}
                                >
                                  Delete
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p style={{ color: 'var(--text-muted)', padding: '16px 0' }}>
                      No optimization runs executed yet. Click "Load Sample Shift Data" above or add your own orders to begin.
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: DEPOT LOCATION (Single Active Depot Replacement Mode — No Multi-Depot Confusion!) */}
          {activeTab === 'depot' && (
            <div className="grid-2" style={{ alignItems: 'start' }}>
              <div className="card">
                <div className="card-title">Central Dispatch Depot Configuration</div>
                <div className="card-subtitle">
                  This platform operates in Single-Depot mode. Saving a new depot location automatically replaces the active starting hub for all vehicles and orders.
                </div>

                {/* Current Active Depot Banner */}
                {depots[0] && (
                  <div
                    style={{
                      padding: 14,
                      background: 'var(--bg-app)',
                      border: '1px solid var(--border-strong)',
                      borderRadius: 8,
                      marginBottom: 18,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontSize: 11.5, fontWeight: 700, textTransform: 'uppercase', color: 'var(--brand-primary)' }}>
                        ● Current Active Starting Depot
                      </span>
                      <span className="badge badge-success">
                        {depots[0].return_enabled ? 'Return to Depot Required' : 'Open Route End'}
                      </span>
                    </div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {depots[0].name}
                    </div>
                    <div className="mono" style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
                      Coordinates: {depots[0].lat.toFixed(4)}°N, {depots[0].lon.toFixed(4)}°E · Operating Window:{' '}
                      {utcSecondsToClockHHMM(depots[0].opening_time_utc_s)} –{' '}
                      {depots[0].closing_time_utc_s
                        ? utcSecondsToClockHHMM(depots[0].closing_time_utc_s)
                        : '20:30'}{' '}
                      IST
                    </div>
                  </div>
                )}

                <form
                  onSubmit={async (e) => {
                    e.preventDefault();
                    setErrorBanner(null);
                    if (!depotName.trim()) {
                      setErrorBanner('Please enter your Depot / Warehouse Name.');
                      return;
                    }
                    try {
                      const openS = clockHHMMToUtcSeconds(depotOpenHHMM);
                      const closeS = clockHHMMToUtcSeconds(depotCloseHHMM);
                      const saved = await apiClient.createDepot({
                        name: depotName.trim(),
                        lat: depotLat,
                        lon: depotLon,
                        opening_time_utc_s: openS,
                        closing_time_utc_s: closeS,
                        return_enabled: depotReturnEnabled,
                        return_deadline_utc_s: closeS,
                      });
                      await refreshAllData();
                      setDepotName('');
                      showToast(`✓ Active depot updated to "${saved.name}"!`);
                    } catch (err: any) {
                      setErrorBanner(err.message);
                    }
                  }}
                >
                  <div className="form-group">
                    <label className="form-label">New / Updated Depot Name</label>
                    <span className="form-help">Enter your custom hub name (not overwritten by map clicks)</span>
                    <input
                      className="form-input"
                      placeholder={depots[0] ? `Replace "${depots[0].name}" with new name...` : 'Enter depot or warehouse name'}
                      value={depotName}
                      onChange={(e) => setDepotName(e.target.value)}
                      required
                    />
                  </div>
                  <div className="grid-2">
                    <div className="form-group">
                      <label className="form-label">Operating Shift Opens At</label>
                      <input
                        className="form-input mono"
                        type="time"
                        value={depotOpenHHMM}
                        onChange={(e) => setDepotOpenHHMM(e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Operating Shift Closes At</label>
                      <input
                        className="form-input mono"
                        type="time"
                        value={depotCloseHHMM}
                        onChange={(e) => setDepotCloseHHMM(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="grid-2">
                    <div className="form-group">
                      <label className="form-label">Pin Latitude (°N)</label>
                      <input
                        className="form-input mono"
                        type="number"
                        step="0.0001"
                        value={depotLat}
                        onChange={(e) => setDepotLat(Number(e.target.value))}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Pin Longitude (°E)</label>
                      <input
                        className="form-input mono"
                        type="number"
                        step="0.0001"
                        value={depotLon}
                        onChange={(e) => setDepotLon(Number(e.target.value))}
                      />
                    </div>
                  </div>
                  <div className="form-group">
                    <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <input
                        type="checkbox"
                        checked={depotReturnEnabled}
                        onChange={(e) => setDepotReturnEnabled(e.target.checked)}
                      />
                      <span>Vehicles must return to the depot after completing their last delivery</span>
                    </label>
                  </div>
                  <button className="btn btn-primary" type="submit" style={{ width: '100%' }}>
                    {depots[0] ? 'Replace Active Central Depot' : 'Set as Active Central Depot'}
                  </button>
                </form>
              </div>

              <div className="card">
                <div className="card-title">Depot Location Map Selector</div>
                <div className="card-subtitle">
                  Search any locality in the map bar below or click on the map to position the active depot pin.
                </div>
                <InteractiveMap
                  nodes={roadNodes}
                  edges={roadEdges}
                  depot={depots[0] || null}
                  draftPin={{ lat: depotLat, lon: depotLon, label: depotName || depots[0]?.name || 'Depot Pin' }}
                  onSelectLocation={(lat, lon) => {
                    setDepotLat(lat);
                    setDepotLon(lon);
                  }}
                  height={460}
                />
              </div>
            </div>
          )}

          {/* TAB 3: CUSTOMERS & DELIVERY ORDERS */}
          {activeTab === 'orders' && (
            <div>
              <div className="grid-2" style={{ marginBottom: 20, alignItems: 'start' }}>
                <div className="card" style={{ position: 'sticky', top: 16 }}>
                  <div className="card-title">Customer Delivery Location Map</div>
                  <div className="card-subtitle">
                    Search any place in the map search bar or click/drag the pin to set the customer's delivery address.
                  </div>
                  <InteractiveMap
                    nodes={roadNodes}
                    edges={roadEdges}
                    depot={depots[0] || null}
                    orders={orders}
                    draftPin={{ lat: custLat, lon: custLon, label: custName || 'Delivery Pin' }}
                    onSelectLocation={handleMapPinPickForCustomer}
                    height={510}
                  />
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                  <div className="card">
                    <div className="card-title">Step 1: Add Customer & Delivery Address</div>
                    <div className="card-subtitle">
                      Enter the customer's name yourself. Dropping a pin on the map automatically fills the street address below.
                    </div>
                    <form onSubmit={handleCreateCustomerAndConfirm}>
                      <div className="grid-2">
                        <div className="form-group">
                          <label className="form-label">Customer / Consignee Name</label>
                          <span className="form-help">Entered by you (not changed by map clicks)</span>
                          <input
                            className="form-input"
                            placeholder="Enter customer or store name"
                            value={custName}
                            onChange={(e) => setCustName(e.target.value)}
                            required
                          />
                        </div>
                        <div className="form-group">
                          <label className="form-label">Gate / Delivery Instructions</label>
                          <span className="form-help">Optional landmark or unloading note</span>
                          <input
                            className="form-input"
                            placeholder="e.g., Main Gate / Call before arrival"
                            value={custInstructions}
                            onChange={(e) => setCustInstructions(e.target.value)}
                          />
                        </div>
                      </div>
                      <div className="form-group">
                        <label className="form-label">Delivery Street Address</label>
                        <input
                          className="form-input"
                          placeholder="Pin a location on the map (left) or type the street address..."
                          value={custAddress}
                          onChange={(e) => setCustAddress(e.target.value)}
                          required
                        />
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 12, color: 'var(--status-success)', fontWeight: 500 }}>
                          {locationVerified
                            ? '✓ Road delivery access verified'
                            : `Pin: ${custLat.toFixed(4)}°N, ${custLon.toFixed(4)}°E`}
                        </span>
                        <button className="btn btn-primary" type="submit">
                          Save Customer Location
                        </button>
                      </div>
                    </form>
                  </div>

                  <div className="card">
                    <div className="card-title">Step 2: Create Delivery Order</div>
                    <div className="card-subtitle">
                      Specify parcel weight, unloading duration, promised delivery date, and optional customer time slot.
                    </div>
                    <form onSubmit={handleCreateOrder}>
                      <div className="form-group">
                        <label className="form-label">Select Customer</label>
                        <select
                          className="form-select"
                          value={selectedCustomerId}
                          onChange={(e) => setSelectedCustomerId(e.target.value)}
                          required
                        >
                          <option value="">-- Choose a saved customer --</option>
                          {customers.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name} — {c.address_text.slice(0, 55)}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="grid-3">
                        <div className="form-group">
                          <label className="form-label">Order Weight (kg)</label>
                          <span className="form-help">Total shipment weight in kg</span>
                          <input
                            className="form-input mono"
                            type="number"
                            min={1}
                            placeholder="e.g. 25"
                            value={orderWeightKg}
                            onChange={(e) => setOrderWeightKg(e.target.value)}
                            required
                          />
                        </div>
                        <div className="form-group">
                          <label className="form-label">Unloading Time (Minutes)</label>
                          <span className="form-help">Time needed at customer location</span>
                          <input
                            className="form-input mono"
                            type="number"
                            min={1}
                            placeholder="e.g. 10"
                            value={orderServiceMinutes}
                            onChange={(e) => setOrderServiceMinutes(e.target.value)}
                            required
                          />
                        </div>
                        <div className="form-group">
                          <label className="form-label">Order ID (Optional)</label>
                          <span className="form-help">Auto-generated if left blank</span>
                          <input
                            className="form-input mono"
                            placeholder="e.g. ORD-204"
                            value={orderRef}
                            onChange={(e) => setOrderRef(e.target.value)}
                          />
                        </div>
                      </div>

                      <div className="grid-2">
                        <div className="form-group">
                          <label className="form-label">Promised Delivery Date (Order Deadline)</label>
                          <span className="form-help">
                            Final promised date by which the customer must receive this order
                          </span>
                          <input
                            className="form-input mono"
                            type="date"
                            value={promisedDate}
                            onChange={(e) => setPromisedDate(e.target.value)}
                            required
                          />
                        </div>
                        <div className="form-group">
                          <label className="form-label">Delivery Priority Level</label>
                          <span className="form-help">Determines which orders are prioritized first</span>
                          <select
                            className="form-select"
                            value={orderPriority}
                            onChange={(e) =>
                              setOrderPriority(e.target.value as 'CRITICAL' | 'STANDARD' | 'FLEXIBLE')
                            }
                          >
                            <option value="CRITICAL">Critical / Urgent Priority</option>
                            <option value="STANDARD">Standard Priority</option>
                            <option value="FLEXIBLE">Flexible / Economy Priority</option>
                          </select>
                        </div>
                      </div>

                      <div
                        style={{
                          padding: 12,
                          background: 'var(--bg-app)',
                          border: '1px solid var(--border-color)',
                          borderRadius: 6,
                          marginBottom: 14,
                        }}
                      >
                        <label
                          className="form-label"
                          style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
                        >
                          <input
                            type="checkbox"
                            checked={hasFixedTimeWindow}
                            onChange={(e) => setHasFixedTimeWindow(e.target.checked)}
                          />
                          <span>Does this customer require a specific delivery time window today?</span>
                        </label>
                        <span className="form-help" style={{ marginBottom: hasFixedTimeWindow ? 10 : 0 }}>
                          {hasFixedTimeWindow
                            ? 'Specify the exact hours during which the customer accepts delivery (e.g. 10:00 AM to 12:00 PM).'
                            : 'No fixed slot required — order can be delivered anytime during normal shift hours.'}
                        </span>

                        {hasFixedTimeWindow && (
                          <div>
                            <div className="grid-2">
                              <div className="form-group">
                                <label className="form-label">Window Opens At (HH:MM)</label>
                                <span className="form-help">Earliest time customer accepts delivery</span>
                                <input
                                  className="form-input mono"
                                  type="time"
                                  value={slotOpenHHMM}
                                  onChange={(e) => setSlotOpenHHMM(e.target.value)}
                                  required
                                />
                              </div>
                              <div className="form-group">
                                <label className="form-label">Window Closes At (HH:MM)</label>
                                <span className="form-help">Delivery & unloading must finish by this time</span>
                                <input
                                  className="form-input mono"
                                  type="time"
                                  value={slotCloseHHMM}
                                  onChange={(e) => setSlotCloseHHMM(e.target.value)}
                                  required
                                />
                              </div>
                            </div>

                            <div className="form-group" style={{ marginBottom: 0 }}>
                              <label className="form-label">What if the vehicle arrives after the window closes?</label>
                              <select
                                className="form-select"
                                value={orderWinType}
                                onChange={(e) => setOrderWinType(e.target.value as 'HARD' | 'SOFT')}
                              >
                                <option value="HARD">
                                  Strict Window — Customer will NOT accept delivery outside this time slot
                                </option>
                                <option value="SOFT">
                                  Flexible Window — Customer prefers this slot, but accepts late delivery (late fee applies)
                                </option>
                              </select>
                            </div>
                          </div>
                        )}
                      </div>

                      <button className="btn btn-emerald" type="submit" style={{ width: '100%' }}>
                        + Add Delivery Order
                      </button>
                    </form>
                  </div>
                </div>
              </div>

              {/* Edit Order Drawer */}
              {editingOrder && (
                <div
                  className="card"
                  style={{
                    marginBottom: 20,
                    border: '2px solid var(--obsidian)',
                    background: 'var(--bg-surface)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div>
                      <div className="card-title">
                        Edit Order {editingOrder.external_ref} ({editingOrder.customer_name})
                      </div>
                      <div className="card-subtitle" style={{ marginBottom: 0 }}>
                        Update order status (Cancel, Return, Delivered), change delivery address/instructions, or adjust time slot & weight.
                      </div>
                    </div>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => setEditingOrder(null)}
                    >
                      Close ✕
                    </button>
                  </div>

                  <form onSubmit={handleSaveEditedOrder}>
                    <div className="grid-4">
                      <div className="form-group">
                        <label className="form-label">Order Status</label>
                        <select
                          className="form-select"
                          value={editStatus}
                          onChange={(e) => setEditStatus(e.target.value)}
                        >
                          <option value="NEW">Active / Pending Delivery</option>
                          <option value="CANCELLED">Cancelled by Customer</option>
                          <option value="RETURNED">Returned / Delivery Refused</option>
                          <option value="DELIVERED">Completed / Delivered</option>
                        </select>
                      </div>
                      <div className="form-group">
                        <label className="form-label">Order Weight (kg)</label>
                        <input
                          className="form-input mono"
                          type="number"
                          min={1}
                          value={editWeightKg}
                          onChange={(e) => setEditWeightKg(Number(e.target.value))}
                        />
                      </div>
                      <div className="form-group">
                        <label className="form-label">Unloading Time (Minutes)</label>
                        <input
                          className="form-input mono"
                          type="number"
                          min={1}
                          value={editServiceMinutes}
                          onChange={(e) => setEditServiceMinutes(Number(e.target.value))}
                        />
                      </div>
                      <div className="form-group">
                        <label className="form-label">Priority Level</label>
                        <select
                          className="form-select"
                          value={editPriority}
                          onChange={(e) =>
                            setEditPriority(e.target.value as 'CRITICAL' | 'STANDARD' | 'FLEXIBLE')
                          }
                        >
                          <option value="CRITICAL">Critical / Urgent</option>
                          <option value="STANDARD">Standard</option>
                          <option value="FLEXIBLE">Flexible / Economy</option>
                        </select>
                      </div>
                    </div>

                    <div className="grid-4">
                      <div className="form-group">
                        <label className="form-label">Promised Delivery Date</label>
                        <input
                          className="form-input mono"
                          type="date"
                          value={editPromisedDate}
                          onChange={(e) => setEditPromisedDate(e.target.value)}
                        />
                      </div>
                      <div className="form-group">
                        <label className="form-label">Window Opens At (HH:MM)</label>
                        <input
                          className="form-input mono"
                          type="time"
                          value={editSlotOpenHHMM}
                          onChange={(e) => setEditSlotOpenHHMM(e.target.value)}
                        />
                      </div>
                      <div className="form-group">
                        <label className="form-label">Window Closes At (HH:MM)</label>
                        <input
                          className="form-input mono"
                          type="time"
                          value={editSlotCloseHHMM}
                          onChange={(e) => setEditSlotCloseHHMM(e.target.value)}
                        />
                      </div>
                      <div className="form-group">
                        <label className="form-label">Window Policy</label>
                        <select
                          className="form-select"
                          value={editWinType}
                          onChange={(e) => setEditWinType(e.target.value as 'HARD' | 'SOFT')}
                        >
                          <option value="HARD">Strict Window (No late delivery)</option>
                          <option value="SOFT">Flexible Window (Late fee applies)</option>
                        </select>
                      </div>
                    </div>

                    <div className="grid-2">
                      <div className="form-group">
                        <label className="form-label">Updated Delivery Address</label>
                        <input
                          className="form-input"
                          value={editAddress}
                          onChange={(e) => setEditAddress(e.target.value)}
                        />
                      </div>
                      <div className="form-group">
                        <label className="form-label">Updated Gate / Delivery Instructions</label>
                        <input
                          className="form-input"
                          value={editInstructions}
                          onChange={(e) => setEditInstructions(e.target.value)}
                        />
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: 10 }}>
                      <button className="btn btn-primary" type="submit">
                        Save Order Changes
                      </button>
                      <button
                        className="btn btn-secondary"
                        type="button"
                        onClick={() => setEditingOrder(null)}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                </div>
              )}

              <div className="card">
                <div className="card-title">Shift Delivery Orders ({orders.length})</div>
                <div className="card-subtitle">
                  Manage active orders, edit delivery instructions or time slots, or mark orders as Cancelled / Returned.
                </div>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Order ID</th>
                      <th>Customer & Address</th>
                      <th>Weight</th>
                      <th>Unloading</th>
                      <th>Preferred Time Window</th>
                      <th>Window Rule</th>
                      <th>Priority</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((o: any, oIdx: number) => {
                      const cCode = o.customer_code || deriveCustomerCode(o.external_ref, oIdx + 1);
                      const opStatus = computeOrderOperationalStatus(
                        o,
                        activePlan,
                        vehicles,
                        apiClient.getDriverJourneys()
                      );
                      const isOverdue = Boolean(o.is_overdue) || isPromisedDateOverdue(o.promised_date);
                      return (
                      <tr key={o.id} style={{ opacity: o.status === 'CANCELLED' ? 0.55 : 1 }}>
                        <td className="mono">
                          <span
                            style={{
                              display: 'inline-block',
                              padding: '2px 7px',
                              borderRadius: 10,
                              background: 'var(--obsidian)',
                              color: '#f7f5f0',
                              fontWeight: 700,
                              fontSize: 11.5,
                              marginRight: 7,
                            }}
                          >
                            {cCode}
                          </span>
                          <strong>{o.external_ref}</strong>
                        </td>
                        <td>
                          <strong>{o.customer_name}</strong>
                          <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                            {o.address_text}
                            {o.delivery_instructions ? ` · Note: "${o.delivery_instructions}"` : ''}
                          </div>
                        </td>
                        <td className="mono">{o.demand_units} kg</td>
                        <td className="mono">{Math.round((o.service_seconds || 300) / 60)} mins</td>
                        <td className="mono">
                          {o.promised_date ? (
                            <div style={{ fontWeight: 600, color: isOverdue ? '#9f1c1c' : 'var(--text-primary)' }}>
                              📅 {o.promised_date} {isOverdue ? '(Past)' : ''}
                            </div>
                          ) : null}
                          <div>
                            {utcSecondsToClockHHMM(o.window_open_utc_s)} –{' '}
                            {utcSecondsToClockHHMM(o.window_close_utc_s)} IST
                          </div>
                        </td>
                        <td>
                          <span className={`badge ${o.window_type === 'HARD' ? 'badge-danger' : 'badge-warning'}`}>
                            {o.window_type === 'HARD' ? 'Strict Slot' : 'Flexible Slot'}
                          </span>
                        </td>
                        <td>
                          {isOverdue && o.priority === 'CRITICAL' ? (
                            <span className="badge badge-danger" title="Critical order with passed deadline — given highest dispatch priority">
                              🔥 CRITICAL · TOP PRIORITY
                            </span>
                          ) : (
                            <span
                              className={`badge ${
                                o.priority === 'CRITICAL'
                                  ? 'badge-danger'
                                  : o.priority === 'STANDARD'
                                  ? 'badge-info'
                                  : 'badge-neutral'
                              }`}
                            >
                              {o.priority}
                            </span>
                          )}
                        </td>
                        <td>
                          <span className={`badge ${opStatus.badgeClass}`}>
                            {opStatus.label}
                          </span>
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            <button
                              type="button"
                              className="btn btn-secondary"
                              style={{ padding: '4px 9px', fontSize: 11.5 }}
                              onClick={() => handleOpenEditOrder(o)}
                            >
                              Edit
                            </button>
                            {o.status !== 'CANCELLED' && o.status !== 'DELIVERED' && (
                              <button
                                type="button"
                                className="btn btn-secondary"
                                style={{ padding: '4px 9px', fontSize: 11.5, color: '#b45309' }}
                                onClick={() => {
                                  setConfirmModal({
                                    title: 'Confirm Order Cancellation',
                                    message: `Are you sure you want to mark order ${o.external_ref} (${o.customer_name}) as Cancelled?`,
                                    confirmLabel: 'Yes, Cancel Order',
                                    onConfirm: async () => {
                                      setConfirmModal(null);
                                      await apiClient.updateOrder(o.id, { status: 'CANCELLED' });
                                      await refreshAllData();
                                      showToast(`✓ Order ${o.external_ref} marked as Cancelled.`);
                                    },
                                  });
                                }}
                              >
                                Cancel
                              </button>
                            )}
                            <button
                              type="button"
                              className="btn btn-danger"
                              style={{ padding: '4px 9px', fontSize: 11.5 }}
                              onClick={() => {
                                setConfirmModal({
                                  title: 'Confirm Permanent Order Deletion',
                                  message: `Are you sure you want to permanently delete order ${o.external_ref} (${o.customer_name})?`,
                                  confirmLabel: 'Yes, Delete Order',
                                  onConfirm: async () => {
                                    setConfirmModal(null);
                                    await apiClient.deleteOrder(o.id);
                                    await refreshAllData();
                                    showToast(`✓ Removed order ${o.external_ref}.`);
                                  },
                                });
                              }}
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* TAB 4: VEHICLES & COST TARIFFS */}
          {activeTab === 'fleet' && (
            <div className="grid-2" style={{ alignItems: 'start' }}>
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <div className="card-title" style={{ marginBottom: 0 }}>Register Delivery Vehicles</div>
                  <span className="badge badge-neutral mono">
                    {showVehicleDriverStep ? 'Step 2 of 2 · Driver Assignment' : 'Step 1 of 2 · Vehicle Specs'}
                  </span>
                </div>
                <div className="card-subtitle">
                  Enter vehicle payload and dispatch cost first. Once entered, the Driver Credentials box appears smoothly below to keep the workspace clean.
                </div>
                <form onSubmit={handleCreateVehicle}>
                  <div className="grid-3">
                    <div className="form-group">
                      <label className="form-label">Vehicle Number / Code</label>
                      <span className="form-help">Registration plate or fleet ID</span>
                      <input
                        className="form-input mono"
                        placeholder="e.g. GJ-06-AX-105"
                        value={vehCode}
                        onChange={(e) => setVehCode(e.target.value)}
                        required
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Max Load Capacity (kg)</label>
                      <span className="form-help">Maximum cargo weight carried</span>
                      <input
                        className="form-input mono"
                        type="number"
                        min={1}
                        placeholder="e.g. 60"
                        value={vehCapacityKg}
                        onChange={(e) => setVehCapacityKg(e.target.value)}
                        required
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Shift Dispatch Base Cost (₹)</label>
                      <span className="form-help">Fixed fee when vehicle is used</span>
                      <input
                        className="form-input mono"
                        type="number"
                        min={0}
                        placeholder="e.g. 300"
                        value={vehActivationINR}
                        onChange={(e) => setVehActivationINR(e.target.value)}
                        required
                      />
                    </div>
                  </div>

                  {!showVehicleDriverStep ? (
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                        Next: Assign driver name & Driver Portal login credentials
                      </span>
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => {
                          const capKg = parseInt(vehCapacityKg, 10);
                          const actInr = parseFloat(vehActivationINR || '0');
                          if (!vehCode.trim() || !capKg || capKg <= 0 || isNaN(actInr) || actInr < 0) {
                            setErrorBanner(
                              'Please enter Vehicle Code, Max Load Capacity (kg), and Shift Dispatch Base Cost (₹) first.'
                            );
                            return;
                          }
                          setErrorBanner(null);
                          if (!vehDriverUsername.trim()) {
                            const suggested = vehCode.trim().toLowerCase().replace(/[^a-z0-9]/g, '');
                            setVehDriverUsername(suggested);
                          }
                          if (!vehDriverPassword.trim()) {
                            setVehDriverPassword('pass123');
                          }
                          setShowVehicleDriverStep(true);
                        }}
                      >
                        Next: Assign Driver Details →
                      </button>
                    </div>
                  ) : (
                    <div
                      style={{
                        marginTop: 8,
                        padding: '16px 18px',
                        borderRadius: 10,
                        background: 'var(--bg-stone-header)',
                        border: '1.5px solid var(--obsidian)',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                        <div>
                          <div style={{ fontWeight: 700, fontSize: 13.5, color: 'var(--text-primary)' }}>
                            👤 Step 2 · Assign Driver & Portal Login Credentials for{' '}
                            <span className="mono">{vehCode.trim()}</span>
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                            These credentials allow the assigned driver to sign into the Driver Portal.
                          </div>
                        </div>
                        <button
                          type="button"
                          className="btn btn-secondary"
                          style={{ padding: '4px 10px', fontSize: 11.5 }}
                          onClick={() => setShowVehicleDriverStep(false)}
                        >
                          ← Edit Vehicle Specs
                        </button>
                      </div>

                      <div className="grid-3">
                        <div className="form-group">
                          <label className="form-label">Assigned Driver Name</label>
                          <span className="form-help">Driver full name for manifest</span>
                          <input
                            className="form-input"
                            placeholder="e.g. Vikram Solanki"
                            value={vehDriverName}
                            onChange={(e) => setVehDriverName(e.target.value)}
                            required
                            autoFocus
                          />
                        </div>
                        <div className="form-group">
                          <label className="form-label">Driver Portal Username</label>
                          <span className="form-help">Used by driver to sign in</span>
                          <input
                            className="form-input mono"
                            placeholder="e.g. vikram105"
                            value={vehDriverUsername}
                            onChange={(e) => setVehDriverUsername(e.target.value)}
                            required
                          />
                        </div>
                        <div className="form-group">
                          <label className="form-label">Driver Portal Password</label>
                          <span className="form-help">Login password for Driver Portal</span>
                          <input
                            className="form-input mono"
                            placeholder="e.g. pass105"
                            value={vehDriverPassword}
                            onChange={(e) => setVehDriverPassword(e.target.value)}
                            required
                          />
                        </div>
                      </div>

                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                        <button className="btn btn-emerald" type="submit">
                          ✓ Register Vehicle & Driver to Fleet
                        </button>
                      </div>
                    </div>
                  )}
                </form>

                <table className="data-table" style={{ marginTop: 20 }}>
                  <thead>
                    <tr>
                      <th>Vehicle Code</th>
                      <th>Load Capacity</th>
                      <th>Dispatch Base Cost</th>
                      <th>Status</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {vehicles.map((v) => {
                      const journeys = apiClient.getDriverJourneys();
                      const isInTransit = Boolean(v.in_transit) || Boolean(journeys[v.id]?.inTransit);
                      return (
                        <tr key={v.id}>
                          <td className="mono">
                            <strong>{v.code}</strong>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                              👤 {v.driver_name || `Driver (${v.code})`}
                            </div>
                          </td>
                          <td className="mono">{v.capacity_units} kg</td>
                          <td className="mono">₹{(v.activation_cost_paise / 100).toFixed(2)}</td>
                          <td>
                            {isInTransit ? (
                              <span className="badge badge-info">🚚 In Transit</span>
                            ) : (
                              <span className={`badge ${v.available ? 'badge-success' : 'badge-warning'}`}>
                                {v.available ? 'Available' : 'In Maintenance'}
                              </span>
                            )}
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                              <button
                                type="button"
                                className="btn btn-secondary"
                                style={{ padding: '4px 8px', fontSize: 11.5 }}
                                onClick={() => setInspectingDriverVehicle(v)}
                              >
                                👤 Driver Details
                              </button>
                              <button
                                type="button"
                                className="btn btn-secondary"
                                style={{
                                  padding: '4px 8px',
                                  fontSize: 11.5,
                                  opacity: isInTransit ? 0.55 : 1,
                                  cursor: isInTransit ? 'not-allowed' : 'pointer',
                                }}
                                onClick={async () => {
                                  if (isInTransit) {
                                    setErrorBanner(
                                      `Vehicle ${v.code} is currently In Transit on an active delivery route and cannot be marked for maintenance.`
                                    );
                                    return;
                                  }
                                  try {
                                    await apiClient.updateVehicle(v.id, { available: !v.available });
                                    await refreshAllData();
                                    showToast(
                                      `✓ Vehicle ${v.code} marked as ${!v.available ? 'Available' : 'In Maintenance'}.`
                                    );
                                  } catch (err: any) {
                                    setErrorBanner(err.message);
                                  }
                                }}
                              >
                                {isInTransit
                                  ? '🔒 In Transit'
                                  : v.available
                                  ? 'Mark Maintenance'
                                  : 'Mark Available'}
                              </button>
                              <button
                                type="button"
                                className="btn btn-danger"
                                style={{
                                  padding: '4px 8px',
                                  fontSize: 11.5,
                                  opacity: isInTransit ? 0.55 : 1,
                                  cursor: isInTransit ? 'not-allowed' : 'pointer',
                                }}
                                onClick={() => {
                                  if (isInTransit) {
                                    setErrorBanner(
                                      `Vehicle ${v.code} is currently In Transit on an active delivery route and cannot be removed.`
                                    );
                                    return;
                                  }
                                  setConfirmModal({
                                    title: 'Confirm Vehicle Removal',
                                    message: `Are you sure you want to permanently remove vehicle ${v.code} (${v.driver_name || 'Driver'}) from the fleet?`,
                                    confirmLabel: 'Yes, Remove Vehicle',
                                    onConfirm: async () => {
                                      setConfirmModal(null);
                                      try {
                                        await apiClient.deleteVehicle(v.id);
                                        await refreshAllData();
                                        showToast(`✓ Removed vehicle ${v.code}.`);
                                      } catch (err: any) {
                                        setErrorBanner(err.message);
                                      }
                                    },
                                  });
                                }}
                              >
                                Remove
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="card">
                <div className="card-title">Fleet Operating Cost & SLA Tariff</div>
                <div className="card-subtitle">
                  Configure how route running expenses (fuel, driver wages, and late delivery compensation) are calculated during route planning.
                </div>

                {costProfiles[0] && (
                  <div
                    style={{
                      padding: 16,
                      background: 'var(--bg-app)',
                      border: '1px solid var(--border-color)',
                      borderRadius: 8,
                      marginBottom: 20,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                      <strong>Active Tariff: {costProfiles[0].name}</strong>
                      <span className="badge badge-success">Active</span>
                    </div>
                    <div className="grid-3">
                      <div style={{ background: 'var(--bg-surface)', padding: 10, borderRadius: 6, border: '1px solid var(--border-color)' }}>
                        <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>Fuel & Distance Rate</div>
                        <div className="mono" style={{ fontSize: 16, fontWeight: 700, marginTop: 3 }}>
                          ₹{(costProfiles[0].rates.distance_rate_paise_per_km.n / (100 * costProfiles[0].rates.distance_rate_paise_per_km.d)).toFixed(2)} / km
                        </div>
                      </div>
                      <div style={{ background: 'var(--bg-surface)', padding: 10, borderRadius: 6, border: '1px solid var(--border-color)' }}>
                        <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>Driver & Time Rate</div>
                        <div className="mono" style={{ fontSize: 16, fontWeight: 700, marginTop: 3 }}>
                          ₹{(costProfiles[0].rates.time_rate_paise_per_hour.n / (100 * costProfiles[0].rates.time_rate_paise_per_hour.d)).toFixed(2)} / hr
                        </div>
                      </div>
                      <div style={{ background: 'var(--bg-surface)', padding: 10, borderRadius: 6, border: '1px solid var(--border-color)' }}>
                        <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>Late Fee (Urgent / Std)</div>
                        <div className="mono" style={{ fontSize: 14, fontWeight: 700, marginTop: 4 }}>
                          ₹{(costProfiles[0].rates.critical_sla_paise_per_min.n / 100).toFixed(0)} / ₹{(costProfiles[0].rates.standard_sla_paise_per_min.n / 100).toFixed(0)} per min
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                <form onSubmit={handleCreateTariffProfile}>
                  <div className="card-title" style={{ fontSize: 14, marginBottom: 10 }}>
                    Update Operating Cost Rates
                  </div>
                  <div className="grid-2">
                    <div className="form-group">
                      <label className="form-label">Distance Cost (₹ per km)</label>
                      <span className="form-help">Fuel, tires & maintenance per km</span>
                      <input
                        className="form-input mono"
                        type="number"
                        step="0.5"
                        min={0}
                        value={tariffPerKmINR}
                        onChange={(e) => setTariffPerKmINR(e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Running Time Cost (₹ per hour)</label>
                      <span className="form-help">Driver wage & hourly operating expense</span>
                      <input
                        className="form-input mono"
                        type="number"
                        step="5"
                        min={0}
                        value={tariffPerHourINR}
                        onChange={(e) => setTariffPerHourINR(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="grid-3">
                    <div className="form-group">
                      <label className="form-label">Urgent Late Fee (₹/min)</label>
                      <input
                        className="form-input mono"
                        type="number"
                        min={0}
                        value={tariffCritSlaINR}
                        onChange={(e) => setTariffCritSlaINR(e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Standard Late Fee (₹/min)</label>
                      <input
                        className="form-input mono"
                        type="number"
                        min={0}
                        value={tariffStdSlaINR}
                        onChange={(e) => setTariffStdSlaINR(e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Economy Late Fee (₹/min)</label>
                      <input
                        className="form-input mono"
                        type="number"
                        min={0}
                        value={tariffFlexSlaINR}
                        onChange={(e) => setTariffFlexSlaINR(e.target.value)}
                      />
                    </div>
                  </div>
                  <button className="btn btn-secondary" type="submit">
                    Save Updated Cost Tariff
                  </button>
                </form>
              </div>
            </div>
          )}

          {/* TAB 5: ROUTE PLANNING (Classical Selectable Radio-Card UI Inspired by image_0f5bc2.png + Fleet Advisory Intelligence!) */}
          {activeTab === 'planning' && (
            <div className="grid-2" style={{ alignItems: 'start' }}>
              <div className="card">
                <div className="card-title">Planning configuration</div>
                <div className="card-subtitle">
                  Choose how the delivery plan should be built. Every option explains what it does.
                </div>

                {/* Section 1: Planning Mode */}
                <div className="config-section-block">
                  <div className="config-section-header">
                    <span>1 · Planning mode</span>
                    <span className="badge badge-success" style={{ fontSize: 10.5 }}>
                      FINAL
                    </span>
                  </div>
                  <div className="choice-card-grid-2">
                    <div
                      className={`choice-card ${planningMode === 'COMPLETE' ? 'selected' : ''}`}
                      onClick={() => setPlanningMode('COMPLETE')}
                    >
                      <div className="choice-radio-circle">
                        {planningMode === 'COMPLETE' && <div className="choice-radio-dot" />}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div className="choice-card-title">Complete plan</div>
                        <div className="choice-card-desc">
                          Every order must be served exactly once. If that is not possible with the selected fleet, the minimum required vehicles are shown.
                        </div>
                      </div>
                    </div>

                    <div
                      className={`choice-card ${planningMode === 'PARTIAL' ? 'selected' : ''}`}
                      onClick={() => setPlanningMode('PARTIAL')}
                    >
                      <div className="choice-radio-circle">
                        {planningMode === 'PARTIAL' && <div className="choice-radio-dot" />}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div className="choice-card-title">Partial plan</div>
                        <div className="choice-card-desc">
                          Serve as many orders as possible in priority order Critical → Standard → Flexible; unserved orders are listed with reasons.
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="choice-section-caption">
                    Decides what happens if not every order can be served today.
                  </div>
                </div>

                {/* Section 2: Fleet Sizing */}
                <div className="config-section-block">
                  <div className="config-section-header">
                    <span>2 · Fleet sizing</span>
                  </div>
                  <div className="choice-card-grid-2">
                    <div
                      className={`choice-card ${fleetMode === 'AUTO' ? 'selected' : ''}`}
                      onClick={() => setFleetMode('AUTO')}
                    >
                      <div className="choice-radio-circle">
                        {fleetMode === 'AUTO' && <div className="choice-radio-dot" />}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div className="choice-card-title">Auto fleet</div>
                        <div className="choice-card-desc">
                          The system decides how many vehicles to activate, up to the available fleet ({availableVehiclesCount} vehicles).
                        </div>
                      </div>
                    </div>

                    <div
                      className={`choice-card ${fleetMode === 'TARGET' ? 'selected' : ''}`}
                      onClick={() => setFleetMode('TARGET')}
                    >
                      <div className="choice-radio-circle">
                        {fleetMode === 'TARGET' && <div className="choice-radio-dot" />}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div className="choice-card-title">
                          <span>Target fleet</span>
                          <span className="badge badge-warning" style={{ fontSize: 10 }}>
                            CAP LIMIT
                          </span>
                        </div>
                        <div className="choice-card-desc">
                          Plan around a specific maximum vehicle count that you choose.
                        </div>
                      </div>
                    </div>
                  </div>

                  {fleetMode === 'TARGET' && (
                    <div style={{ marginTop: 14, maxWidth: 280 }}>
                      <label className="form-label">Maximum vehicles</label>
                      <input
                        className="form-input mono"
                        type="number"
                        min={1}
                        max={Math.max(10, vehicles.length)}
                        value={targetFleetSize}
                        onChange={(e) => setTargetFleetSize(Math.max(1, Number(e.target.value)))}
                      />
                    </div>
                  )}
                  <div className="choice-section-caption">
                    How many vehicles may be used. {availableVehiclesCount} vehicles are currently marked available ({availableCapKg} kg total capacity).
                  </div>
                </div>

                {/* Section 3: Optimization Profile */}
                <div className="config-section-block">
                  <div className="config-section-header">
                    <span>3 · Optimization profile</span>
                  </div>
                  <div className="choice-card-grid-3">
                    <div
                      className={`choice-card ${optProfile === 'COST_FOCUSED' ? 'selected' : ''}`}
                      onClick={() => setOptProfile('COST_FOCUSED')}
                    >
                      <div className="choice-radio-circle">
                        {optProfile === 'COST_FOCUSED' && <div className="choice-radio-dot" />}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div className="choice-card-title">Cost-focused</div>
                        <div className="choice-card-desc">
                          Lowest total cost: operating cost + vehicle activation + SLA penalties.
                        </div>
                      </div>
                    </div>

                    <div
                      className={`choice-card ${optProfile === 'BALANCED' ? 'selected' : ''}`}
                      onClick={() => setOptProfile('BALANCED')}
                    >
                      <div className="choice-radio-circle">
                        {optProfile === 'BALANCED' && <div className="choice-radio-dot" />}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div className="choice-card-title">Balanced</div>
                        <div className="choice-card-desc">
                          Trade-off between total route cost and driver waiting time objectives.
                        </div>
                      </div>
                    </div>

                    <div
                      className={`choice-card ${optProfile === 'DRIVER_PRODUCTIVITY' ? 'selected' : ''}`}
                      onClick={() => setOptProfile('DRIVER_PRODUCTIVITY')}
                    >
                      <div className="choice-radio-circle">
                        {optProfile === 'DRIVER_PRODUCTIVITY' && <div className="choice-radio-dot" />}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div className="choice-card-title">Driver productivity</div>
                        <div className="choice-card-desc">
                          Better use of paid driver time (minimum gate wait) within an extra-cost limit.
                        </div>
                      </div>
                    </div>
                  </div>

                  {optProfile === 'DRIVER_PRODUCTIVITY' && (
                    <div style={{ marginTop: 14, maxWidth: 320 }}>
                      <label className="form-label">Maximum extra budget above cheapest plan (₹)</label>
                      <input
                        className="form-input mono"
                        type="number"
                        min={0}
                        value={maxExtraCostINR}
                        onChange={(e) => setMaxExtraCostINR(Number(e.target.value))}
                      />
                    </div>
                  )}
                  <div className="choice-section-caption">
                    What the plan should prioritise. Infeasible plans are never accepted under any profile.
                  </div>
                </div>

                {/* Section 4: Optimization Engine (Solver) */}
                <div className="config-section-block">
                  <div className="config-section-header">
                    <span>4 · Optimization algorithm</span>
                  </div>
                  <div className="choice-card-grid-2">
                    {[
                      {
                        id: 'QPSO',
                        title: 'Q-HGALS 5.0 (QPSO)',
                        badge: 'CORE ENGINE',
                        desc: 'Quantum-behaved swarm + continuation-safe Split DP + Local Search.',
                      },
                      {
                        id: 'ALNS',
                        title: 'ALNS Metaheuristic',
                        badge: 'ADAPTIVE',
                        desc: 'Adaptive destroy & repair neighborhood search over time windows.',
                      },
                      {
                        id: 'GA',
                        title: 'Hybrid Genetic (GA)',
                        badge: 'EVOLUTIONARY',
                        desc: 'Order-crossover genetic search paired with Vehicle-Aware Split.',
                      },
                      {
                        id: 'LOCAL_SEARCH',
                        title: 'Deterministic Local Search',
                        badge: 'FAST',
                        desc: 'Multi-start construction refined by 2-Opt, Relocate, and Swap.',
                      },
                    ].map((s) => (
                      <div
                        key={s.id}
                        className={`choice-card ${solverKind === s.id ? 'selected' : ''}`}
                        onClick={() => setSolverKind(s.id)}
                      >
                        <div className="choice-radio-circle">
                          {solverKind === s.id && <div className="choice-radio-dot" />}
                        </div>
                        <div style={{ flex: 1 }}>
                          <div className="choice-card-title">
                            <span>{s.title}</span>
                            <span className="badge badge-info" style={{ fontSize: 9.5 }}>
                              {s.badge}
                            </span>
                          </div>
                          <div className="choice-card-desc">{s.desc}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Progressive Disclosure for Advanced Research Controls */}
                <div style={{ margin: '10px 0 16px' }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    style={{ width: '100%', justifyContent: 'space-between' }}
                    onClick={() => setShowAdvancedControls(!showAdvancedControls)}
                  >
                    <span>Advanced Swarm & Evaluation Budget Controls</span>
                    <span>{showAdvancedControls ? '▲ Hide' : '▼ Configure'}</span>
                  </button>
                  {showAdvancedControls && (
                    <div
                      style={{
                        padding: 14,
                        border: '1px solid var(--border-color)',
                        borderRadius: 6,
                        marginTop: 8,
                        background: 'var(--bg-app)',
                      }}
                    >
                      <div className="grid-2">
                        <div className="form-group">
                          <label className="form-label">Evaluation Budget</label>
                          <input
                            className="form-input mono"
                            type="number"
                            min={20}
                            max={10000}
                            value={maxEvaluations}
                            onChange={(e) => setMaxEvaluations(Number(e.target.value))}
                          />
                        </div>
                        <div className="form-group">
                          <label className="form-label">Random Seed</label>
                          <input
                            className="form-input mono"
                            type="number"
                            value={randomSeed}
                            onChange={(e) => setRandomSeed(Number(e.target.value))}
                          />
                        </div>
                      </div>
                      <div className="grid-2">
                        <div className="form-group">
                          <label className="form-label">QPSO Swarm Size (P)</label>
                          <input
                            className="form-input mono"
                            type="number"
                            min={1}
                            value={qpsoParticles}
                            onChange={(e) => setQpsoParticles(Number(e.target.value))}
                          />
                        </div>
                        <div className="form-group">
                          <label className="form-label">QPSO Generations (T)</label>
                          <input
                            className="form-input mono"
                            type="number"
                            min={1}
                            value={qpsoGenerations}
                            onChange={(e) => setQpsoGenerations(Number(e.target.value))}
                          />
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Section 4: Pick Customer Orders for Next Dispatch (Requirement 12) */}
                <div className="config-section-block" style={{ marginTop: 18 }}>
                  <div className="config-section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                    <span>4 · Select customer orders for next dispatch</span>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        style={{ padding: '4px 10px', fontSize: 11.5 }}
                        onClick={() => {
                          const inDepotIds = orders
                            .filter((o: any) => {
                              const st = computeOrderOperationalStatus(
                                o,
                                activePlan,
                                vehicles,
                                apiClient.getDriverJourneys()
                              );
                              return st.isInDepot;
                            })
                            .map((o: any) => o.id);
                          setSelectedOrderIdsForPlanning(inDepotIds);
                          showToast(`✓ Selected all ${inDepotIds.length} in-depot orders for next dispatch.`);
                        }}
                      >
                        ✓ Pick All In-Depot Orders
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        style={{ padding: '4px 10px', fontSize: 11.5 }}
                        onClick={() => {
                          const allEligible = orders
                            .filter((o: any) => o.status !== 'CANCELLED' && o.status !== 'DELIVERED' && o.status !== 'RETURNED')
                            .map((o: any) => o.id);
                          setSelectedOrderIdsForPlanning(allEligible);
                        }}
                      >
                        Select All Active
                      </button>
                    </div>
                  </div>

                  <div
                    style={{
                      maxHeight: 250,
                      overflowY: 'auto',
                      border: '1px solid var(--border-color)',
                      borderRadius: 6,
                      background: 'var(--bg-surface)',
                      marginTop: 8,
                    }}
                  >
                    <table className="data-table" style={{ margin: 0 }}>
                      <thead>
                        <tr>
                          <th style={{ width: 36 }}>Pick</th>
                          <th>Customer & Order</th>
                          <th>Weight</th>
                          <th>Promised Deadline</th>
                          <th>Priority</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {orders
                          .filter((o: any) => o.status !== 'CANCELLED' && o.status !== 'DELIVERED' && o.status !== 'RETURNED')
                          .map((o: any, idx: number) => {
                            const cCode = o.customer_code || deriveCustomerCode(o.external_ref, idx + 1);
                            const isChecked = selectedOrderIdsForPlanning.includes(o.id);
                            const overdue = Boolean(o.is_overdue) || isPromisedDateOverdue(o.promised_date);
                            const opSt = computeOrderOperationalStatus(
                              o,
                              activePlan,
                              vehicles,
                              apiClient.getDriverJourneys()
                            );
                            return (
                              <tr
                                key={o.id}
                                onClick={() => {
                                  setSelectedOrderIdsForPlanning((prev) =>
                                    prev.includes(o.id) ? prev.filter((id) => id !== o.id) : [...prev, o.id]
                                  );
                                }}
                                style={{
                                  cursor: 'pointer',
                                  background: isChecked ? 'rgba(21, 128, 61, 0.06)' : '#ffffff',
                                }}
                              >
                                <td onClick={(e) => e.stopPropagation()}>
                                  <input
                                    type="checkbox"
                                    checked={isChecked}
                                    onChange={() => {
                                      setSelectedOrderIdsForPlanning((prev) =>
                                        prev.includes(o.id) ? prev.filter((id) => id !== o.id) : [...prev, o.id]
                                      );
                                    }}
                                    style={{ width: 15, height: 15, accentColor: '#15803d', cursor: 'pointer' }}
                                  />
                                </td>
                                <td>
                                  <strong className="mono">{cCode}</strong> · <strong>{o.customer_name}</strong>
                                  <div className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                    {o.external_ref}
                                  </div>
                                </td>
                                <td className="mono">{o.demand_units} kg</td>
                                <td className="mono" style={{ fontSize: 11.5 }}>
                                  {o.promised_date ? (
                                    <div style={{ fontWeight: 600, color: overdue ? '#9f1c1c' : 'var(--text-primary)' }}>
                                      📅 {o.promised_date} {overdue ? '(Past)' : ''}
                                    </div>
                                  ) : (
                                    <div>Current Shift</div>
                                  )}
                                  <div style={{ color: 'var(--text-muted)' }}>
                                    {utcSecondsToClockHHMM(o.window_open_utc_s)}–{utcSecondsToClockHHMM(o.window_close_utc_s)}
                                  </div>
                                </td>
                                <td>
                                  {overdue && o.priority === 'CRITICAL' ? (
                                    <span className="badge badge-danger">🔥 CRITICAL · TOP</span>
                                  ) : (
                                    <span
                                      className={`badge ${
                                        o.priority === 'CRITICAL'
                                          ? 'badge-danger'
                                          : o.priority === 'STANDARD'
                                          ? 'badge-info'
                                          : 'badge-neutral'
                                      }`}
                                    >
                                      {o.priority}
                                    </span>
                                  )}
                                </td>
                                <td>
                                  <span className={`badge ${opSt.badgeClass}`}>{opSt.label}</span>
                                </td>
                              </tr>
                            );
                          })}
                      </tbody>
                    </table>
                  </div>
                  <div className="choice-section-caption">
                    Selected <strong>{selectedOrderIdsForPlanning.length}</strong> order(s) for next dispatch. Critical orders with passed deadlines are automatically given top priority.
                  </div>
                </div>

                {reoptimizingRunId && (
                  <div
                    style={{
                      padding: '10px 14px',
                      borderRadius: 6,
                      background: '#eaf3ed',
                      border: '1.5px solid #15803d',
                      marginBottom: 12,
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      fontSize: 12.5,
                    }}
                  >
                    <div>
                      <strong>↺ Re-Optimization Mode Active (Most Recent Plan):</strong> Modify any settings above and click <strong>&ldquo;2. Re-Optimize Routes&rdquo;</strong> below.
                    </div>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      style={{ padding: '3px 8px', fontSize: 11 }}
                      onClick={() => setReoptimizingRunId(null)}
                    >
                      New Run Mode
                    </button>
                  </div>
                )}

                {/* Action Buttons */}
                <div style={{ display: 'flex', gap: 12 }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    style={{ flex: 1, padding: '11px 16px' }}
                    onClick={() => handleValidateAndRunOptimization(false)}
                    disabled={loading}
                  >
                    1. Check Capacity & Readiness
                  </button>
                  <button
                    type="button"
                    className="btn btn-emerald"
                    style={{ flex: 1.3, padding: '11px 18px' }}
                    onClick={() => handleValidateAndRunOptimization(true)}
                    disabled={loading}
                  >
                    {loading
                      ? 'Optimizing Routes...'
                      : reoptimizingRunId
                      ? '2. ↺ Re-Optimize Routes'
                      : '2. Generate Optimized Routes'}
                  </button>
                </div>
              </div>

              {/* Right Column: Pre-Optimization Readiness Check & Fleet Sizing Advisory */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                <div className="card">
                  <div className="card-title">Pre-Optimization Readiness & Fleet Advisory</div>
                  <div className="card-subtitle">
                    Verifies cargo capacity, time windows, and calculates the exact minimum vehicles needed for a 100% Complete Plan.
                  </div>

                  {validationReport ? (
                    <div>
                      <div style={{ marginBottom: 14 }}>
                        <span
                          className={`badge ${
                            validationReport.status === 'VALIDATED' ? 'badge-success' : 'badge-danger'
                          }`}
                          style={{ fontSize: 12.5, padding: '4px 12px' }}
                        >
                          {validationReport.status === 'VALIDATED'
                            ? '✓ All Prechecks Passed — Ready to Dispatch'
                            : '⚠ Insufficient Vehicles for Complete Plan'}
                        </span>
                      </div>

                      {/* Key Fleet Metrics Strip */}
                      <div className="grid-3" style={{ marginBottom: 16 }}>
                        <div style={{ padding: 12, background: 'var(--bg-app)', borderRadius: 6, border: '1px solid var(--border-color)' }}>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Min. Vehicles for 100% Plan</div>
                          <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: 'var(--obsidian)', marginTop: 4 }}>
                            {validationReport.fleet_advisory?.min_vehicles_for_complete_plan ??
                              validationReport.capacity_lower_bound_all_orders}{' '}
                            vehicles
                          </div>
                        </div>
                        <div style={{ padding: 12, background: 'var(--bg-app)', borderRadius: 6, border: '1px solid var(--border-color)' }}>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Selected Vehicle Limit</div>
                          <div className="mono" style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>
                            {validationReport.fleet_advisory?.selected_fleet_limit ?? availableVehiclesCount} vehicles
                          </div>
                        </div>
                        <div style={{ padding: 12, background: 'var(--bg-app)', borderRadius: 6, border: '1px solid var(--border-color)' }}>
                          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Available in Fleet</div>
                          <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: '#22593f', marginTop: 4 }}>
                            {availableVehiclesCount} vehicles
                          </div>
                        </div>
                      </div>

                      {/* Intelligent Advisory Banner (Handles Complete Infeasible & Partial Plan Upgrade Suggestions!) */}
                      {validationReport.fleet_advisory && (
                        <div
                          style={{
                            padding: 16,
                            borderRadius: 8,
                            marginBottom: 14,
                            border:
                              validationReport.fleet_advisory.advisory_kind === 'COMPLETE_INFEASIBLE_NEED_MORE_VEHICLES'
                                ? '1.5px solid #d97706'
                                : '1.5px solid #22593f',
                            background:
                              validationReport.fleet_advisory.advisory_kind === 'COMPLETE_INFEASIBLE_NEED_MORE_VEHICLES'
                                ? '#fffbeb'
                                : '#eaf3ed',
                          }}
                        >
                          <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)', marginBottom: 6 }}>
                            {validationReport.fleet_advisory.headline}
                          </div>
                          <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                            {validationReport.fleet_advisory.message}
                          </div>

                          {/* One-Click Resolution Actions when Complete Plan needs more vehicles */}
                          {validationReport.fleet_advisory.advisory_kind ===
                            'COMPLETE_INFEASIBLE_NEED_MORE_VEHICLES' && (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 12 }}>
                              {validationReport.fleet_advisory.complete_plan_possible_with_available_fleet && (
                                <button
                                  type="button"
                                  className="btn btn-emerald"
                                  onClick={() =>
                                    handleValidateAndRunOptimization(true, {
                                      planningMode: 'COMPLETE',
                                      fleetMode: 'TARGET',
                                      targetFleetSize:
                                        validationReport.fleet_advisory.min_vehicles_for_complete_plan,
                                    })
                                  }
                                >
                                  Use Minimum Required ({validationReport.fleet_advisory.min_vehicles_for_complete_plan}{' '}
                                  Vehicles) & Generate Complete Plan
                                </button>
                              )}
                              <button
                                type="button"
                                className="btn btn-primary"
                                onClick={() =>
                                  handleValidateAndRunOptimization(true, {
                                    planningMode: 'PARTIAL',
                                  })
                                }
                              >
                                Switch to Partial Plan (Keep {validationReport.fleet_advisory.selected_fleet_limit}{' '}
                                Vehicle Limit)
                              </button>
                            </div>
                          )}

                          {/* One-Click Upgrade Action when Partial Plan is chosen but Complete Plan is possible */}
                          {(validationReport.fleet_advisory.advisory_kind ===
                            'PARTIAL_CAN_UPGRADE_TO_COMPLETE_SAME_FLEET' ||
                            validationReport.fleet_advisory.advisory_kind ===
                              'PARTIAL_CAN_UPGRADE_TO_COMPLETE_MORE_VEHICLES') && (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 12 }}>
                              <button
                                type="button"
                                className="btn btn-emerald"
                                onClick={() =>
                                  handleValidateAndRunOptimization(true, {
                                    planningMode: 'COMPLETE',
                                    fleetMode: 'TARGET',
                                    targetFleetSize:
                                      validationReport.fleet_advisory.min_vehicles_for_complete_plan,
                                  })
                                }
                              >
                                Switch to Complete Plan ({validationReport.fleet_advisory.min_vehicles_for_complete_plan}{' '}
                                Vehicles · 100% Delivery)
                              </button>
                            </div>
                          )}
                        </div>
                      )}

                      {validationReport.diagnostics?.map((d: any, i: number) => (
                        <div key={i} className="alert-banner alert-info" style={{ padding: '8px 12px', fontSize: 12 }}>
                          {d.message}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div
                      style={{
                        padding: 18,
                        background: 'var(--bg-app)',
                        borderRadius: 8,
                        border: '1px solid var(--border-color)',
                      }}
                    >
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>
                        Current Shift Summary ({activeNewOrders.length} Active Orders · {pendingDemandKg} kg)
                      </div>
                      <p style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginBottom: 12 }}>
                        Click <strong>"1. Check Capacity & Readiness"</strong> to verify how many vehicles are required to deliver all {activeNewOrders.length} orders today, or click <strong>"2. Generate Optimized Routes"</strong> to compute the optimal dispatch plan directly.
                      </p>
                      <div className="mono" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                        • Critical Orders: {critOrdersCount} ({critWeightKg} kg) · Standard: {stdOrdersCount} ({stdWeightKg} kg) · Flexible: {flexOrdersCount} ({flexWeightKg} kg)
                      </div>
                    </div>
                  )}
                </div>

                {/* All Optimization Runs & Plans History in Route Planning (Requirement 10) */}
                <div className="card">
                  <div className="card-title">All Optimization Runs & Generated Plans</div>
                  <div className="card-subtitle">
                    View any generated plan in Dispatch Schedule. You can modify configuration and re-optimize the <strong>most recent plan</strong> (older historical plans are read-only).
                  </div>
                  {summary?.recent_runs?.length ? (
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Plan & Mode</th>
                          <th>Orders & Fleet</th>
                          <th>Status</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.recent_runs.map((r: any, idx: number) => {
                          const isMostRecent = idx === 0;
                          const isSelectedForReopt = reoptimizingRunId === r.id;
                          return (
                            <tr
                              key={r.id}
                              style={{
                                background: isSelectedForReopt ? 'rgba(21, 128, 61, 0.08)' : undefined,
                              }}
                            >
                              <td>
                                <strong className="mono">
                                  Run #{summary.recent_runs.length - idx} · {r.solver_kind}
                                </strong>
                                {isMostRecent && (
                                  <span className="badge badge-success" style={{ marginLeft: 6, fontSize: 10 }}>
                                    LATEST
                                  </span>
                                )}
                                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                  {r.planning_mode || 'COMPLETE'} · {r.profile || 'COST_FOCUSED'}
                                </div>
                              </td>
                              <td className="mono" style={{ fontSize: 11.5 }}>
                                {r.order_count || orders.length} orders · {r.m_routes_used || r.vehicle_count || 3} veh
                                {r.total_cost_paise ? (
                                  <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
                                    ₹{(r.total_cost_paise / 100).toFixed(2)}
                                  </div>
                                ) : null}
                              </td>
                              <td>
                                <span
                                  className={`badge ${
                                    r.result_status?.includes('FEASIBLE')
                                      ? 'badge-success'
                                      : 'badge-warning'
                                  }`}
                                >
                                  {r.result_status || 'COMPLETED'}
                                </span>
                              </td>
                              <td>
                                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                                  {r.plan_id && (
                                    <button
                                      type="button"
                                      className="btn btn-secondary"
                                      style={{ padding: '4px 8px', fontSize: 11 }}
                                      onClick={async () => {
                                        const res = await apiClient.getOptimizationRunResult(r.id);
                                        setActiveRunResult(res);
                                        setActivePlan(normalizeAndUncrossPlan(res.plan, depots[0], r.solver_kind));
                                        setSelectedDispatchRunId(r.id);
                                        setActiveTab('results');
                                      }}
                                    >
                                      View Plan
                                    </button>
                                  )}
                                  {isMostRecent ? (
                                    <button
                                      type="button"
                                      className="btn btn-primary"
                                      style={{ padding: '4px 8px', fontSize: 11 }}
                                      onClick={() => {
                                        setReoptimizingRunId(r.id);
                                        if (r.planning_mode) setPlanningMode(r.planning_mode);
                                        if (r.fleet_mode) setFleetMode(r.fleet_mode);
                                        if (r.target_fleet_size) setTargetFleetSize(Number(r.target_fleet_size));
                                        if (r.profile) setOptProfile(r.profile);
                                        showToast(
                                          '↺ Most recent plan loaded for configuration editing. Click "2. Re-Optimize Routes" when ready!'
                                        );
                                      }}
                                    >
                                      {isSelectedForReopt ? '↺ Editing Config' : 'Re-Optimize'}
                                    </button>
                                  ) : (
                                    <span
                                      className="mono"
                                      style={{
                                        fontSize: 10.5,
                                        color: 'var(--text-muted)',
                                        alignSelf: 'center',
                                        padding: '2px 6px',
                                      }}
                                      title="Only the most recent plan can be re-optimized"
                                    >
                                      Read-Only
                                    </span>
                                  )}
                                  <button
                                    type="button"
                                    className="btn btn-danger"
                                    style={{ padding: '4px 8px', fontSize: 11 }}
                                    onClick={() => {
                                      setConfirmModal({
                                        title: 'Confirm Optimization Plan Deletion',
                                        message: `Are you sure you want to delete Run #${summary.recent_runs.length - idx} (${r.solver_kind})?`,
                                        confirmLabel: 'Yes, Delete Plan',
                                        onConfirm: async () => {
                                          setConfirmModal(null);
                                          await apiClient.deleteOptimizationRun(r.id);
                                          if (reoptimizingRunId === r.id) setReoptimizingRunId(null);
                                          await refreshAllData();
                                          showToast('✓ Optimization run deleted.');
                                        },
                                      });
                                    }}
                                  >
                                    Delete
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  ) : (
                    <div style={{ padding: 14, color: 'var(--text-muted)', fontSize: 12.5 }}>
                      No optimization runs recorded yet. Click &ldquo;2. Generate Optimized Routes&rdquo; to create your first plan.
                    </div>
                  )}
                </div>
              </div>


            </div>
          )}

          {/* TAB 6: DISPATCH SCHEDULE, ROUTES, UNSERVED ORDERS & COST LEDGER */}
          {activeTab === 'results' && (
            <div>
              {!activePlan ? (
                <div className="card">
                  <div className="card-title">No Route Plan Generated Yet</div>
                  <p style={{ color: 'var(--text-muted)', marginTop: 8 }}>
                    Go to "Route Planning" in the left menu and click "2. Generate Optimized Routes".
                  </p>
                </div>
              ) : (
                <div>
                  {/* Dispatch Schedule Plan Selector Bar (Requirement 10) */}
                  <div
                    className="card"
                    style={{
                      marginBottom: 16,
                      padding: '12px 16px',
                      background: 'var(--bg-stone-header)',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      gap: 12,
                    }}
                  >
                    <div>
                      <strong style={{ fontSize: 13.5 }}>Viewing Dispatch Schedule & Route Map:</strong>
                      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                        Defaults to your most recent optimization run. Use the dropdown to inspect any historical plan.
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ fontSize: 12, fontWeight: 600 }}>Select Plan:</span>
                      <select
                        className="form-select mono"
                        style={{ minWidth: 310, fontWeight: 600 }}
                        value={selectedDispatchRunId || (summary?.recent_runs?.[0]?.id ?? '')}
                        onChange={async (e) => {
                          const runId = e.target.value;
                          setSelectedDispatchRunId(runId);
                          if (!runId) return;
                          const res = await apiClient.getOptimizationRunResult(runId);
                          if (res?.plan) {
                            const matchedRun = (summary?.recent_runs || []).find((x: any) => x.id === runId);
                            const runSolver = res.solver_kind || (res.plan as any)?.solver_kind || matchedRun?.solver_kind || solverKind;
                            setActiveRunResult(res);
                            setActivePlan(normalizeAndUncrossPlan(res.plan, depots[0], runSolver));
                            setSelectedVehicleIdsResults([]);
                          }
                        }}
                      >
                        {(summary?.recent_runs || [])
                          .filter((r: any) => r.plan_id)
                          .map((r: any, idx: number, arr: any[]) => (
                            <option key={r.id} value={r.id}>
                              {idx === 0 ? '★ Latest Plan: ' : 'Historical: '}
                              Run #{arr.length - idx} · {r.solver_kind} ({r.planning_mode || 'COMPLETE'}) ·{' '}
                              {r.m_routes_used || 3} Vehicles · ₹
                              {((r.total_cost_paise || activePlan.total_cost_paise) / 100).toFixed(2)}
                            </option>
                          ))}
                      </select>
                    </div>
                  </div>

                  <div className="alert-banner alert-success" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <strong>Plan Status: {activePlan.result_status}</strong> · Plan Version v{activePlan.version}
                    </div>
                    <div className="mono">
                      Delivered Today:{' '}
                      <strong>
                        {activePlan.coverage_critical + activePlan.coverage_standard + activePlan.coverage_flexible}
                      </strong>{' '}
                      orders · Not Delivered Today: <strong>{activePlan.unserved_orders.length}</strong> orders
                    </div>
                  </div>

                  {/* Smart Suggestion Banner if user ran Partial Plan and a Complete Plan is possible! */}
                  {activeAdvisory &&
                    (activeAdvisory.advisory_kind === 'PARTIAL_CAN_UPGRADE_TO_COMPLETE_SAME_FLEET' ||
                      activeAdvisory.advisory_kind === 'PARTIAL_CAN_UPGRADE_TO_COMPLETE_MORE_VEHICLES') && (
                      <div
                        style={{
                          padding: '14px 18px',
                          background: '#fffbeb',
                          border: '1.5px solid #d97706',
                          borderRadius: 8,
                          marginBottom: 20,
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          gap: 16,
                        }}
                      >
                        <div>
                          <div style={{ fontWeight: 700, fontSize: 14, color: '#853a05' }}>
                            💡 Complete Plan Suggestion: {activeAdvisory.headline}
                          </div>
                          <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 3 }}>
                            {activeAdvisory.message}
                          </div>
                        </div>
                        <button
                          type="button"
                          className="btn btn-emerald"
                          style={{ whiteSpace: 'nowrap' }}
                          onClick={() =>
                            handleValidateAndRunOptimization(true, {
                              planningMode: 'COMPLETE',
                              fleetMode: 'TARGET',
                              targetFleetSize: activeAdvisory.min_vehicles_for_complete_plan,
                            })
                          }
                        >
                          Switch to Complete Plan ({activeAdvisory.min_vehicles_for_complete_plan} Vehicles)
                        </button>
                      </div>
                    )}

                  {/* EXPLICIT SECTION: ORDERS NOT DELIVERED TODAY (When Partial Plan leaves orders unserved) */}
                  {activePlan.unserved_orders.length > 0 && (
                    <div
                      className="card"
                      style={{
                        marginBottom: 20,
                        border: '1.5px solid #dc2626',
                        background: '#fffafa',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                        <div>
                          <div className="card-title" style={{ color: '#851717' }}>
                            ⚠ Orders Not Delivered Today ({activePlan.unserved_orders.length} Unserved Order
                            {activePlan.unserved_orders.length > 1 ? 's' : ''})
                          </div>
                          <div className="card-subtitle" style={{ marginBottom: 0 }}>
                            The following orders could not be accommodated within your selected {activePlan.m_routes_used}-vehicle partial plan. Critical & Standard orders were prioritized first.
                          </div>
                        </div>
                        {activeAdvisory?.complete_plan_possible_with_available_fleet && (
                          <span className="badge badge-warning">
                            Use {activeAdvisory.min_vehicles_for_complete_plan} vehicles to deliver all orders today
                          </span>
                        )}
                      </div>

                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Order ID</th>
                            <th>Customer & Address</th>
                            <th>Priority</th>
                            <th>Weight</th>
                            <th>Requested Time Window</th>
                            <th>Reason Not Delivered Today</th>
                          </tr>
                        </thead>
                        <tbody>
                          {activePlan.unserved_orders.map((u: any) => (
                            <tr key={u.order_id}>
                              <td className="mono">
                                <strong>{u.external_ref}</strong>
                              </td>
                              <td>
                                <strong>{u.customer_name}</strong>
                                <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                                  {u.address_text || 'Vadodara'}
                                </div>
                              </td>
                              <td>
                                <span
                                  className={`badge ${
                                    u.priority === 'CRITICAL'
                                      ? 'badge-danger'
                                      : u.priority === 'STANDARD'
                                      ? 'badge-warning'
                                      : 'badge-info'
                                  }`}
                                >
                                  {u.priority}
                                </span>
                              </td>
                              <td className="mono">{u.demand_units} kg</td>
                              <td className="mono">
                                {u.window_open_utc_s
                                  ? `${utcSecondsToClockHHMM(u.window_open_utc_s)} – ${utcSecondsToClockHHMM(
                                      u.window_close_utc_s
                                    )} IST`
                                  : 'Shift Hours'}
                              </td>
                              <td style={{ color: '#851717', fontSize: 12.5, fontWeight: 500 }}>
                                {u.reason_explanation || u.detail || u.reason}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <div className="grid-4" style={{ marginBottom: 20 }}>
                    <div className="card">
                      <div className="card-subtitle">Total Route Cost</div>
                      <div className="kpi-value" style={{ fontSize: 22 }}>
                        ₹{(activePlan.total_cost_paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </div>
                      <div className="kpi-Dynamic-caption mono">{activePlan.total_cost_paise.toLocaleString()} paise</div>
                    </div>
                    <div className="card">
                      <div className="card-subtitle">Vehicles Dispatched</div>
                      <div className="kpi-value" style={{ fontSize: 22 }}>
                        {activePlan.m_routes_used} Vehicles
                      </div>
                      <div className="kpi-Dynamic-caption">
                        {activePlan.m_new_activated} newly activated in shift
                      </div>
                    </div>
                    <div className="card">
                      <div className="card-subtitle">Total Distance</div>
                      <div className="kpi-value" style={{ fontSize: 22 }}>
                        {(activePlan.total_distance_m / 1000).toFixed(2)} km
                      </div>
                      <div className="kpi-Dynamic-caption">Road-network path distance</div>
                    </div>
                    <div className="card">
                      <div className="card-subtitle">Gate Waiting Time</div>
                      <div className="kpi-value" style={{ fontSize: 22 }}>
                        {formatDurationSeconds(activePlan.idle_seconds)}
                      </div>
                      <div className="kpi-Dynamic-caption">Early arrival waiting for window open</div>
                    </div>
                  </div>

                  <div className="grid-2" style={{ marginBottom: 20 }}>
                    <div className="card">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
                        <div>
                          <div className="card-title">Interactive Route Map</div>
                          <div className="card-subtitle" style={{ marginBottom: 0 }}>
                            Select one or multiple vehicles to display their routes simultaneously
                          </div>
                        </div>
                        <MultiVehicleSelectDropdown
                          routes={activePlan.routes}
                          selectedVehicleIds={selectedVehicleIdsResults}
                          onChange={setSelectedVehicleIdsResults}
                        />
                      </div>
                      <InteractiveMap
                        nodes={roadNodes}
                        edges={roadEdges}
                        depot={depots[0] || null}
                        orders={orders}
                        vehicles={vehicles}
                        routes={activePlan.routes}
                        solverKind={(activePlan as any)?.solver_kind || solverKind}
                        selectedVehicleIds={selectedVehicleIdsResults}
                        height={410}
                      />
                    </div>

                    <div className="card">
                      <div className="card-title">Cost Breakdown & Shift Dispatch Ledger</div>
                      <div className="card-subtitle">
                        Itemized breakdown of distance, driver time, vehicle dispatch fees, and late delivery penalties
                      </div>
                      <table className="data-table">
                        <tbody>
                          <tr>
                            <td>Fuel & Distance Cost</td>
                            <td className="mono">{formatPaiseToINR(activePlan.cost_breakdown.distance_cost_paise)}</td>
                          </tr>
                          <tr>
                            <td>Driver & Running Time Cost</td>
                            <td className="mono">{formatPaiseToINR(activePlan.cost_breakdown.time_cost_paise)}</td>
                          </tr>
                          <tr>
                            <td>Late Delivery Compensation (SLA)</td>
                            <td className="mono">{formatPaiseToINR(activePlan.cost_breakdown.sla_cost_paise)}</td>
                          </tr>
                          <tr>
                            <td>New Vehicle Dispatch Fees</td>
                            <td className="mono">
                              {formatPaiseToINR(activePlan.cost_breakdown.incremental_activation_cost_paise)}
                            </td>
                          </tr>
                          <tr style={{ background: 'var(--bg-stone-header)', fontWeight: 700 }}>
                            <td>Total Plan Cost</td>
                            <td className="mono">
                              {formatPaiseToINR(activePlan.cost_breakdown.incremental_decision_cost_paise)}
                            </td>
                          </tr>
                          <tr>
                            <td>Previously Posted Shift Dispatch Fees</td>
                            <td className="mono">
                              {formatPaiseToINR(activePlan.cost_breakdown.activation_posted_before_paise)}
                            </td>
                          </tr>
                          <tr>
                            <td>Cumulative Shift Total Forecast</td>
                            <td className="mono">
                              {formatPaiseToINR(activePlan.cost_breakdown.shift_forecast_total_after_paise)}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="card" style={{ marginBottom: 20 }}>
                    <div className="card-title">Vehicle Delivery Schedules & Stop ETAs</div>
                    <div className="card-subtitle">
                      Exact arrival, waiting, unloading start, and completion times for each dispatched vehicle
                    </div>
                    {activePlan.routes.map((route, rIdx) => {
                      const vColor = VEHICLE_COLORS[rIdx % VEHICLE_COLORS.length];
                      const vColorName = VEHICLE_COLOR_NAMES[rIdx % VEHICLE_COLOR_NAMES.length];
                      const stopCodes = route.stops.map((s: any, idx: number) => s.customer_code || deriveCustomerCode(s.external_ref, idx + 1));
                      const returnOn = depots[0] ? Boolean(depots[0].return_enabled) : true;
                      return (
                      <div
                        key={route.id}
                        style={{
                          border: `1.5px solid ${vColor}`,
                          borderLeft: `6px solid ${vColor}`,
                          borderRadius: 6,
                          padding: 14,
                          marginBottom: 14,
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span
                              style={{
                                padding: '3px 9px',
                                borderRadius: 4,
                                background: vColor,
                                color: '#ffffff',
                                fontWeight: 700,
                                fontSize: 12.5,
                              }}
                              className="mono"
                            >
                              {route.vehicle_code} ({vColorName})
                            </span>
                            <strong>
                              Route: H → {stopCodes.join(' → ')}{returnOn ? ' ⇢ ↩ H (Depot Return)' : ''}
                            </strong>
                          </div>
                          <span className="mono">
                            Load: <strong>{route.initial_load_units}/{route.capacity_units} kg</strong> · Distance:{' '}
                            <strong>{(route.distance_m / 1000).toFixed(2)} km</strong> · Duration:{' '}
                            {formatDurationSeconds(route.paid_seconds)}
                          </span>
                        </div>
                        <table className="data-table">
                          <thead>
                            <tr>
                              <th>Customer No.</th>
                              <th>Visit Seq</th>
                              <th>Customer & Order ID</th>
                              <th>Weight</th>
                              <th>Arrival Time</th>
                              <th>Gate Wait</th>
                              <th>Unloading Start</th>
                              <th>Finished By</th>
                              <th>Window Deadline</th>
                              <th>Punctuality</th>
                            </tr>
                          </thead>
                          <tbody>
                            {route.stops.map((s: any, sIdx: number) => {
                              const cCode = s.customer_code || deriveCustomerCode(s.external_ref, sIdx + 1);
                              return (
                              <tr key={s.id}>
                                <td>
                                  <span
                                    className="mono"
                                    style={{
                                      display: 'inline-block',
                                      padding: '2px 8px',
                                      borderRadius: 12,
                                      background: vColor,
                                      color: '#ffffff',
                                      fontWeight: 700,
                                      fontSize: 12,
                                    }}
                                  >
                                    {cCode}
                                  </span>
                                </td>
                                <td className="mono">Stop #{s.seq}</td>
                                <td>
                                  <strong>{s.customer_name}</strong>
                                  <div className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                    {s.external_ref}
                                  </div>
                                </td>
                                <td className="mono">{s.demand_units} kg</td>
                                <td className="mono">{formatSecondsToClockIST(s.arrival_utc_s)}</td>
                                <td className="mono">{Math.round(s.wait_s / 60)}m ({s.wait_s}s)</td>
                                <td className="mono">{formatSecondsToClockIST(s.service_start_utc_s)}</td>
                                <td className="mono">
                                  <strong>{formatSecondsToClockIST(s.service_end_utc_s)}</strong>
                                </td>
                                <td className="mono">
                                  {formatSecondsToClockIST(s.window_close_utc_s)} ({s.window_type === 'HARD' ? 'Strict' : 'Flex'})
                                </td>
                                <td>
                                  {(() => {
                                    const matchedOrd = orders.find(
                                      (o) => o.id === s.order_id || o.external_ref === s.external_ref
                                    );
                                    const pDate = matchedOrd?.promised_date || s.promised_date;
                                    const overdueDate =
                                      Boolean(matchedOrd?.is_overdue || s.is_overdue) ||
                                      isPromisedDateOverdue(pDate);
                                    const lateWindow =
                                      Number(s.lateness_s || 0) > 0 ||
                                      Number(s.service_end_utc_s || 0) > Number(s.window_close_utc_s || 1e15);
                                    if (matchedOrd?.status === 'DELIVERED' || s.order_status === 'DELIVERED') {
                                      return <span className="badge badge-success">✓ Delivered</span>;
                                    }
                                    if (overdueDate) {
                                      return (
                                        <span className="badge badge-danger">
                                          ⚠ Missed Deadline ({pDate || 'Past Date'})
                                        </span>
                                      );
                                    }
                                    if (lateWindow) {
                                      const mins = Math.max(
                                        1,
                                        Math.ceil(
                                          (Number(s.lateness_s) ||
                                            Number(s.service_end_utc_s) - Number(s.window_close_utc_s)) / 60
                                        )
                                      );
                                      return (
                                        <span className="badge badge-danger">
                                          ⚠ Late by {mins}m
                                        </span>
                                      );
                                    }
                                    return <span className="badge badge-success">On Time</span>;
                                  })()}
                                </td>
                              </tr>
                              );
                            })}
                            {returnOn && (
                              <tr style={{ background: 'var(--bg-subtle)' }}>
                                <td>
                                  <span
                                    className="mono"
                                    style={{
                                      display: 'inline-block',
                                      padding: '2px 8px',
                                      borderRadius: 6,
                                      background: '#1c1d1a',
                                      color: '#e5a93c',
                                      fontWeight: 800,
                                      fontSize: 11.5,
                                    }}
                                  >
                                    ↩ H
                                  </span>
                                </td>
                                <td className="mono">Return Leg</td>
                                <td colSpan={5}>
                                  <strong>Return to Depot ({depots[0]?.name || 'Central Hub'})</strong>
                                </td>
                                <td className="mono">
                                  <strong>{formatSecondsToClockIST(route.return_utc_s)}</strong>
                                </td>
                                <td className="mono">Depot Close</td>
                                <td>
                                  <span className="badge badge-info">Returned to Hub</span>
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 7: ADAPTIVE-THEME TRAFFIC LIVE SIMULATION & DYNAMIC REROUTING (Requirement 6) */}
          {activeTab === 'replan' && (
            <TrafficLiveSimulationView
              depot={depots[0] || null}
              orders={orders}
              vehicles={vehicles}
              roadNodes={roadNodes}
              roadEdges={roadEdges}
              activePlan={activePlan}
              loading={loading}
              replanOutput={replanOutput}
              onShowToast={showToast}
              onExecuteReplan={async ({ elapsedMin, closedEdgeIds, edgeMultipliers }) => {
                if (!activePlan) {
                  showToast('ℹ Generate an initial route plan in Route Planning first to see dynamic detour rerouting.');
                  return null;
                }
                setLoading(true);
                setErrorBanner(null);
                try {
                  const t0 =
                    (depots[0]?.opening_time_utc_s || BASE_MORNING_UTC_S) + Number(elapsedMin) * 60;
                  const rep = await apiClient.triggerReplan(activePlan.id, {
                    t0_utc_s: t0,
                    closed_edge_ids: closedEdgeIds,
                    edge_multipliers_override: edgeMultipliers,
                    min_cost_improvement_paise: 0,
                  });
                  setReplanOutput(rep);
                  if (rep.adopted && rep.new_plan) {
                    setActivePlan(normalizeAndUncrossPlan(rep.new_plan, depots[0]));
                  }
                  await refreshAllData();
                  showToast(
                    rep.adopted
                      ? `✓ Dynamic rerouting adopted new detour plan v${rep.new_plan.version}!`
                      : `ℹ Current routes retained (${rep.rejection_reason || 'Optimal under current disruption'}).`
                  );
                  return rep;
                } catch (err: any) {
                  setErrorBanner(err.message);
                  return null;
                } finally {
                  setLoading(false);
                }
              }}
            />
          )}

          {/* TAB 8: SOLVER COMPARISON & BENCHMARKS */}
          {activeTab === 'benchmarks' && (
            <AlgorithmPerformanceLabView
              benchmarkDatasetMode={benchmarkDatasetMode}
              setBenchmarkDatasetMode={setBenchmarkDatasetMode}
              selectedBenchmarkRunId={selectedBenchmarkRunId}
              setSelectedBenchmarkRunId={setSelectedBenchmarkRunId}
              benchmarkBudget={benchmarkBudget}
              setBenchmarkBudget={setBenchmarkBudget}
              benchmarkReport={benchmarkReport}
              loading={loading}
              onRunBenchmarks={handleRunBenchmarks}
              recentRuns={summary?.recent_runs || []}
              activeOrdersCount={activeNewOrders.length}
              pendingDemandKg={pendingDemandKg}
              availableVehiclesCount={availableVehiclesCount}
              availableCapKg={availableCapKg}
              depot={depots[0] || null}
            />
          )}
          </>
          )}
        </main>
      </div>
    </div>
  );
};
