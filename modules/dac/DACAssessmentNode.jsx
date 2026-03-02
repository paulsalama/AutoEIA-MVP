/**
 * DACAssessmentNode — ReactFlow node for the DAC Assessment module
 *
 * Visual workflow builder component for CEQR Chapter 23:
 * Effects on Disadvantaged Communities.
 *
 * Renders in the AutoEIA module orchestration canvas.
 * Accepts project_location input from upstream nodes (e.g., project_screening).
 * Outputs screening_determination and dac_tracts_geojson to downstream nodes.
 *
 * Integration:
 *   import DACAssessmentNode from './DACAssessmentNode';
 *   const nodeTypes = { ...existingTypes, dac_assessment: DACAssessmentNode };
 */

import React, { useState, useCallback, useEffect, memo } from 'react';
import { Handle, Position } from 'reactflow';

// Status indicators
const STATUS_COLORS = {
  idle: '#6b7280',
  running: '#f59e0b',
  complete: '#10b981',
  error: '#ef4444',
  warning: '#f97316',
};

const PROXIMITY_LABELS = {
  within_dac: { label: 'Within DAC', color: '#dc2626', icon: '🔴' },
  proximate_to_dac: { label: 'Proximate (½ mi)', color: '#f59e0b', icon: '🟡' },
  extended_proximity: { label: 'Extended Proximity', color: '#3b82f6', icon: '🔵' },
  outside_dac: { label: 'Outside DAC', color: '#10b981', icon: '🟢' },
};

const DACAssessmentNode = memo(({ data, isConnectable }) => {
  const [status, setStatus] = useState('idle');
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);

  // Config state
  const [bufferDistance, setBufferDistance] = useState(data?.config?.buffer_distance_miles || 0.5);
  const [technicalAreas, setTechnicalAreas] = useState(data?.config?.ceqr_technical_areas || []);

  // Available CEQR technical areas for pollution screening
  const CEQR_AREAS = [
    { id: 'air_quality', label: 'Air Quality', relevance: 'high' },
    { id: 'noise', label: 'Noise', relevance: 'high' },
    { id: 'hazardous_materials', label: 'Hazardous Materials', relevance: 'high' },
    { id: 'transportation_traffic', label: 'Transportation/Traffic', relevance: 'moderate' },
    { id: 'water_sewer', label: 'Water & Sewer', relevance: 'moderate' },
    { id: 'solid_waste', label: 'Solid Waste', relevance: 'moderate' },
    { id: 'construction', label: 'Construction', relevance: 'moderate' },
    { id: 'greenhouse_gas', label: 'Greenhouse Gas', relevance: 'moderate' },
  ];

  /**
   * Execute the assessment via the backend API
   */
  const runAssessment = useCallback(async () => {
    if (!data?.inputs?.project_location) {
      setError('No project location received from upstream node');
      setStatus('error');
      return;
    }

    setStatus('running');
    setError(null);

    try {
      const response = await fetch('/api/modules/dac_assessment/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_location: data.inputs.project_location,
          project_polygon: data.inputs.project_polygon || null,
          project_description: data.inputs.project_description || '',
          ceqr_technical_areas: technicalAreas,
          buffer_distance_miles: bufferDistance,
          project_name: data.inputs.project_name || 'Proposed Action',
          ceqr_number: data.inputs.ceqr_number || '',
          generate_report: true,
        }),
      });

      const json = await response.json();

      if (json.success) {
        setResult(json.result);
        setStatus('complete');

        // Propagate outputs to downstream nodes
        if (data.onOutputChange) {
          data.onOutputChange({
            screening_determination: json.result.screening_determination,
            dac_tracts_geojson: json.result.dac_tracts_geojson,
            study_area_geojson: json.result.study_area_geojson,
            eaf_responses: json.result.eaf_responses,
            burden_summary: json.result.pollution_screening,
            screening_report: json.report_markdown,
          });
        }
      } else {
        setError(json.error || 'Assessment failed');
        setStatus('error');
      }
    } catch (err) {
      setError(err.message);
      setStatus('error');
    }
  }, [data, technicalAreas, bufferDistance]);

  // Auto-run when inputs change (if configured)
  useEffect(() => {
    if (data?.config?.auto_run && data?.inputs?.project_location) {
      runAssessment();
    }
  }, [data?.inputs?.project_location]);

  const determination = result?.screening_determination;
  const proximity = determination
    ? PROXIMITY_LABELS[determination.proximity_classification]
    : null;

  return (
    <div
      style={{
        background: 'white',
        borderRadius: '8px',
        border: `2px solid ${STATUS_COLORS[status]}`,
        minWidth: '280px',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        fontSize: '12px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
      }}
    >
      {/* Input handles */}
      <Handle
        type="target"
        position={Position.Left}
        id="project_location"
        style={{ background: '#6366f1', width: 10, height: 10 }}
        isConnectable={isConnectable}
      />

      {/* Header */}
      <div
        style={{
          padding: '8px 12px',
          background: '#f0fdf4',
          borderBottom: '1px solid #e5e7eb',
          borderRadius: '6px 6px 0 0',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div>
          <div style={{ fontWeight: 600, fontSize: '13px', color: '#1f2937' }}>
            Ch. 23: Disadvantaged Communities
          </div>
          <div style={{ color: '#6b7280', fontSize: '10px', marginTop: '2px' }}>
            EJSL Screening Assessment
          </div>
        </div>
        <div
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: STATUS_COLORS[status],
          }}
        />
      </div>

      {/* Body */}
      <div style={{ padding: '8px 12px' }}>
        {/* Config: Buffer distance */}
        <div style={{ marginBottom: '6px' }}>
          <label style={{ color: '#6b7280', fontSize: '10px', display: 'block' }}>
            Study Area Buffer
          </label>
          <select
            value={bufferDistance}
            onChange={(e) => setBufferDistance(parseFloat(e.target.value))}
            style={{
              width: '100%',
              padding: '3px 6px',
              border: '1px solid #d1d5db',
              borderRadius: '4px',
              fontSize: '11px',
            }}
          >
            <option value={0.25}>0.25 miles</option>
            <option value={0.5}>0.5 miles (CEQR default)</option>
            <option value={1.0}>1.0 miles</option>
          </select>
        </div>

        {/* Config: Technical areas */}
        <div style={{ marginBottom: '8px' }}>
          <label style={{ color: '#6b7280', fontSize: '10px', display: 'block' }}>
            Pollution-Relevant Technical Areas
          </label>
          <div
            style={{
              maxHeight: '80px',
              overflowY: 'auto',
              border: '1px solid #e5e7eb',
              borderRadius: '4px',
              padding: '4px',
            }}
          >
            {CEQR_AREAS.map((area) => (
              <label
                key={area.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  fontSize: '10px',
                  padding: '1px 0',
                  cursor: 'pointer',
                }}
              >
                <input
                  type="checkbox"
                  checked={technicalAreas.includes(area.id)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setTechnicalAreas([...technicalAreas, area.id]);
                    } else {
                      setTechnicalAreas(technicalAreas.filter((a) => a !== area.id));
                    }
                  }}
                  style={{ marginRight: '4px' }}
                />
                <span>{area.label}</span>
                <span
                  style={{
                    marginLeft: 'auto',
                    color: area.relevance === 'high' ? '#dc2626' : '#f59e0b',
                    fontSize: '9px',
                  }}
                >
                  {area.relevance}
                </span>
              </label>
            ))}
          </div>
        </div>

        {/* Run button */}
        <button
          onClick={runAssessment}
          disabled={status === 'running'}
          style={{
            width: '100%',
            padding: '6px',
            background: status === 'running' ? '#d1d5db' : '#4f46e5',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            fontSize: '11px',
            fontWeight: 500,
            cursor: status === 'running' ? 'not-allowed' : 'pointer',
          }}
        >
          {status === 'running' ? 'Analyzing...' : 'Run DAC Screening'}
        </button>

        {/* Error */}
        {error && (
          <div
            style={{
              marginTop: '6px',
              padding: '4px 6px',
              background: '#fef2f2',
              color: '#dc2626',
              borderRadius: '4px',
              fontSize: '10px',
            }}
          >
            {error}
          </div>
        )}

        {/* Results summary */}
        {determination && (
          <div style={{ marginTop: '8px' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '6px 8px',
                background: proximity
                  ? `${proximity.color}15`
                  : '#f9fafb',
                borderRadius: '4px',
                marginBottom: '4px',
              }}
            >
              <span style={{ marginRight: '6px' }}>{proximity?.icon}</span>
              <span style={{ fontWeight: 600, color: proximity?.color }}>
                {proximity?.label}
              </span>
              <span style={{ marginLeft: 'auto', color: '#6b7280', fontSize: '10px' }}>
                {determination.dac_tracts_in_study_area} tract(s)
              </span>
            </div>

            <div style={{ fontSize: '10px', color: '#4b5563', lineHeight: 1.4 }}>
              <div>
                <strong>EAF (½ mi):</strong>{' '}
                {determination.eaf_question_within_half_mile}
              </div>
              <div>
                <strong>Assessment:</strong>{' '}
                {determination.assessment_level_required.replace(/_/g, ' ')}
              </div>
              {determination.nearest_dac_distance_miles !== null && (
                <div>
                  <strong>Nearest DAC:</strong>{' '}
                  {determination.nearest_dac_distance_miles.toFixed(3)} mi
                  ({determination.nearest_dac_geoid})
                </div>
              )}
            </div>

            {/* Expandable details */}
            <button
              onClick={() => setExpanded(!expanded)}
              style={{
                width: '100%',
                padding: '3px',
                marginTop: '4px',
                background: 'none',
                border: '1px solid #e5e7eb',
                borderRadius: '4px',
                fontSize: '10px',
                color: '#6b7280',
                cursor: 'pointer',
              }}
            >
              {expanded ? '▼ Hide Details' : '▶ Show Details'}
            </button>

            {expanded && (
              <div
                style={{
                  marginTop: '4px',
                  padding: '6px',
                  background: '#f9fafb',
                  borderRadius: '4px',
                  fontSize: '10px',
                  maxHeight: '150px',
                  overflowY: 'auto',
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: '4px' }}>
                  Affected DAC Tracts:
                </div>
                {result.dac_tracts
                  ?.filter((t) => t.is_within_buffer)
                  .map((tract) => (
                    <div
                      key={tract.geoid}
                      style={{
                        padding: '3px 0',
                        borderBottom: '1px solid #e5e7eb',
                      }}
                    >
                      <strong>{tract.geoid}</strong> — {tract.distance_miles.toFixed(3)} mi
                      {tract.top_burden_indicators?.length > 0 && (
                        <div style={{ color: '#dc2626', marginTop: '2px' }}>
                          Top burden:{' '}
                          {tract.top_burden_indicators
                            .slice(0, 3)
                            .map(([name, pct]) => `${name.replace(/_/g, ' ')} (${Math.round(pct)}th)`)
                            .join(', ')}
                        </div>
                      )}
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Output handles */}
      <Handle
        type="source"
        position={Position.Right}
        id="screening_determination"
        style={{ top: '30%', background: '#10b981', width: 10, height: 10 }}
        isConnectable={isConnectable}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="dac_tracts_geojson"
        style={{ top: '50%', background: '#3b82f6', width: 10, height: 10 }}
        isConnectable={isConnectable}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="screening_report"
        style={{ top: '70%', background: '#8b5cf6', width: 10, height: 10 }}
        isConnectable={isConnectable}
      />
    </div>
  );
});

DACAssessmentNode.displayName = 'DACAssessmentNode';

export default DACAssessmentNode;

/**
 * Node type registration for the module registry.
 * Import this in platform/frontend/src/nodes/index.js
 */
export const dacAssessmentNodeConfig = {
  type: 'dac_assessment',
  label: 'Ch. 23: Disadvantaged Communities',
  category: 'environmental_justice',
  component: DACAssessmentNode,
  inputs: [
    { id: 'project_location', label: 'Project Location', type: 'coordinates' },
  ],
  outputs: [
    { id: 'screening_determination', label: 'Screening Result', type: 'json' },
    { id: 'dac_tracts_geojson', label: 'DAC Tracts (GeoJSON)', type: 'geojson' },
    { id: 'screening_report', label: 'Report (Markdown)', type: 'markdown' },
  ],
};
