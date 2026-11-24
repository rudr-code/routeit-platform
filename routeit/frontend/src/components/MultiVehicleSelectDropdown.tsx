import React, { useEffect, useRef, useState } from 'react';
import { RouteDto } from '../types/api';
import { VEHICLE_COLORS, VEHICLE_COLOR_NAMES, deriveCustomerCode } from './InteractiveMap';

interface MultiVehicleSelectDropdownProps {
  routes: RouteDto[];
  selectedVehicleIds: string[];
  onChange: (newSelectedIds: string[]) => void;
}

/**
 * Multi-Select Vehicle Filter Dropdown (Requirements 1 & 2):
 * - Allows selecting 1, 2, or more vehicles simultaneously to compare/view their paths on the map.
 * - Checking "All Dispatched Vehicles" automatically unchecks all individual vehicle checkboxes
 *   (and shows all vehicles on the map).
 * - Checking any individual vehicle unchecks "All Dispatched Vehicles" and shows only the checked vehicles.
 */
export const MultiVehicleSelectDropdown: React.FC<MultiVehicleSelectDropdownProps> = ({
  routes,
  selectedVehicleIds,
  onChange,
}) => {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  if (!routes || routes.length === 0) return null;

  const isAllSelected = selectedVehicleIds.length === 0;

  const handleToggleAll = () => {
    // When "All Dispatched Vehicles" is selected, all individual vehicle options become unchecked!
    onChange([]);
  };

  const handleToggleVehicle = (vehicleId: string) => {
    if (selectedVehicleIds.includes(vehicleId)) {
      const next = selectedVehicleIds.filter((id) => id !== vehicleId);
      onChange(next);
    } else {
      onChange([...selectedVehicleIds, vehicleId]);
    }
  };

  const buttonSummary = isAllSelected
    ? `All Dispatched Vehicles (${routes.length})`
    : routes
        .filter((r) => selectedVehicleIds.includes(r.vehicle_id))
        .map((r) => r.vehicle_code)
        .join(', ') || `All Dispatched Vehicles (${routes.length})`;

  return (
    <div ref={containerRef} style={{ position: 'relative', minWidth: 245, zIndex: 45 }}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 10,
          padding: '7px 12px',
          fontSize: 12.5,
          fontWeight: 600,
          background: 'var(--bg-surface)',
          color: 'var(--text-primary)',
          border: '1.5px solid var(--border-strong)',
          borderRadius: 6,
          cursor: 'pointer',
          boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {buttonSummary}
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 5px)',
            right: 0,
            minWidth: 290,
            background: 'var(--bg-surface)',
            border: '1.5px solid var(--border-strong)',
            borderRadius: 8,
            boxShadow: '0 12px 28px rgba(22, 24, 22, 0.18)',
            padding: '6px 0',
            zIndex: 120,
          }}
        >
          <div
            style={{
              padding: '6px 12px 4px',
              fontSize: 10.5,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              color: 'var(--text-muted)',
              borderBottom: '1px solid var(--border-color)',
            }}
          >
            Select Vehicles to Display (Multi-Select)
          </div>

          {/* Option 0: All Dispatched Vehicles */}
          <label
            onClick={handleToggleAll}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 12px',
              cursor: 'pointer',
              background: isAllSelected ? 'rgba(21, 128, 61, 0.08)' : '#ffffff',
              borderBottom: '1px solid var(--border-color)',
              fontSize: 12.5,
              fontWeight: isAllSelected ? 700 : 500,
            }}
          >
            <input
              type="checkbox"
              checked={isAllSelected}
              onChange={handleToggleAll}
              style={{ width: 15, height: 15, accentColor: '#15803d', cursor: 'pointer' }}
            />
            <div style={{ flex: 1 }}>
              <div>All Dispatched Vehicles ({routes.length})</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
                Unchecks individual filters and shows all active routes
              </div>
            </div>
          </label>

          {/* Individual Vehicles */}
          {routes.map((r, rIdx) => {
            const color = VEHICLE_COLORS[rIdx % VEHICLE_COLORS.length];
            const colorName = VEHICLE_COLOR_NAMES[rIdx % VEHICLE_COLOR_NAMES.length];
            const isChecked = selectedVehicleIds.includes(r.vehicle_id);
            const stopCodes = (r.stops || []).map(
              (s: any, idx: number) => s.customer_code || deriveCustomerCode(s.external_ref, idx + 1)
            );

            return (
              <label
                key={r.vehicle_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '8px 12px',
                  cursor: 'pointer',
                  background: isChecked ? 'rgba(21, 128, 61, 0.06)' : '#ffffff',
                  borderBottom:
                    rIdx < routes.length - 1 ? '1px solid var(--border-color)' : 'none',
                  fontSize: 12.5,
                }}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => handleToggleVehicle(r.vehicle_id)}
                  style={{ width: 15, height: 15, accentColor: color, cursor: 'pointer' }}
                />
                <span
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 3,
                    background: color,
                    flexShrink: 0,
                  }}
                  title={colorName}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                    <strong className="mono" style={{ color }}>
                      {r.vehicle_code} ({r.stops.length} stops)
                    </strong>
                    <span className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {r.initial_load_units}/{r.capacity_units} kg
                    </span>
                  </div>
                  <div className="mono" style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                    H ▶ {stopCodes.join(' ▶ ')}
                  </div>
                </div>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
};
