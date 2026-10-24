import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge } from "../Badge";
import {
  approveAction,
  fetchActions,
  fetchIncident,
  rejectAction,
  type ActionSummary,
  type IncidentDetail as IncidentDetailData,
} from "../api";

const API_BASE = import.meta.env.VITE_DASHBOARD_API_BASE as string;

function describeFix(fix: { type: string; [key: string]: unknown }): string {
  switch (fix.type) {
    case "rollback":
      return `Rollback ${fix.deployment} → revision ${fix.to_revision}`;
    case "restart":
      return `Restart ${fix.deployment}`;
    case "scale":
      return `Scale ${fix.deployment} to ${fix.replicas} replicas`;
    case "manual":
      return `Manual: ${fix.reason}`;
    default:
      return JSON.stringify(fix);
  }
}

function RejectForm({ onSubmit, onCancel }: { onSubmit: (reason: string) => void; onCancel: () => void }) {
  const [reason, setReason] = useState("");
  return (
    <div className="reject-form">
      <textarea
        placeholder="Reason for rejecting this action"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div className="action-buttons">
        <button className="btn-reject" disabled={!reason.trim()} onClick={() => onSubmit(reason)}>
          Confirm reject
        </button>
        <button onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<IncidentDetailData | null>(null);
  const [actions, setActions] = useState<ActionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);

  const reload = () => {
    if (!id) return;
    fetchIncident(API_BASE, id).then(setIncident).catch((err: Error) => setError(err.message));
    fetchActions(API_BASE, id).then(setActions).catch((err: Error) => setError(err.message));
  };

  useEffect(reload, [id]);

  if (error) return <p className="error-state" role="alert">{error}</p>;
  if (!incident) return <p className="loading-state">Loading…</p>;

  return (
    <div className="page">
      <Link className="back-link" to="/">
        ← Back to incidents
      </Link>
      <div className="page-header">
        <h1>{incident.alertname}</h1>
        <Badge value={incident.status} />
      </div>

      <h2>Findings</h2>
      {incident.findings.length === 0 && <p className="empty-state">No findings yet.</p>}
      {incident.findings.map((finding) => (
        <div className="card" key={finding.id}>
          <div className="card-row">
            <span className="card-label">Confidence</span>
            <Badge value={finding.confidence} />
          </div>
          <p>{finding.summary}</p>
          <div className="card-row" style={{ marginTop: 12 }}>
            <span className="card-label">Root cause</span>
          </div>
          <p>{finding.root_cause}</p>
          <div className="fix-block">{describeFix(finding.suggested_fix)}</div>
        </div>
      ))}

      <h2>Timeline</h2>
      {incident.timeline.length === 0 ? (
        <p className="empty-state">No timeline events yet.</p>
      ) : (
        <ul className="timeline">
          {incident.timeline.map((entry, i) => (
            <li key={i}>
              <span className="timeline-time">{new Date(entry.created_at).toLocaleString()}</span>
              {entry.event_type}
            </li>
          ))}
        </ul>
      )}

      <h2>Actions</h2>
      {actions.length === 0 && <p className="empty-state">No actions proposed.</p>}
      {actions.map((action) => (
        <div className="card" key={action.id}>
          <div className="card-row">
            <span className="card-label">{action.type}</span>
            <Badge value={action.status} />
          </div>
          <p>{action.reason}</p>
          {action.status === "pending" && (
            <>
              <div className="action-buttons">
                <button
                  className="btn-approve"
                  onClick={() =>
                    approveAction(API_BASE, action.id).then(reload).catch((err: Error) => setError(err.message))
                  }
                >
                  Approve
                </button>
                <button className="btn-reject" onClick={() => setRejectingId(action.id)}>
                  Reject
                </button>
              </div>
              {rejectingId === action.id && (
                <RejectForm
                  onCancel={() => setRejectingId(null)}
                  onSubmit={(reason) => {
                    rejectAction(API_BASE, action.id, reason)
                      .then(() => {
                        setRejectingId(null);
                        reload();
                      })
                      .catch((err: Error) => setError(err.message));
                  }}
                />
              )}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
