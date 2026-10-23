import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  approveAction,
  fetchActions,
  fetchIncident,
  rejectAction,
  type ActionSummary,
  type IncidentDetail as IncidentDetailData,
} from "../api";

const API_BASE = import.meta.env.VITE_DASHBOARD_API_BASE as string;

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<IncidentDetailData | null>(null);
  const [actions, setActions] = useState<ActionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    if (!id) return;
    fetchIncident(API_BASE, id).then(setIncident).catch((err: Error) => setError(err.message));
    fetchActions(API_BASE, id).then(setActions).catch((err: Error) => setError(err.message));
  };

  useEffect(reload, [id]);

  if (error) return <p role="alert">{error}</p>;
  if (!incident) return <p>Loading…</p>;

  return (
    <div>
      <h1>{incident.alertname}</h1>
      <p>Status: {incident.status}</p>

      <h2>Findings</h2>
      {incident.findings.map((finding) => (
        <div key={finding.id}>
          <p>{finding.summary}</p>
          <p>Root cause: {finding.root_cause}</p>
        </div>
      ))}

      <h2>Timeline</h2>
      <ul>
        {incident.timeline.map((entry, i) => (
          <li key={i}>
            {entry.created_at} — {entry.event_type}
          </li>
        ))}
      </ul>

      <h2>Actions</h2>
      {actions.map((action) => (
        <div key={action.id}>
          <p>
            {action.type}: {action.reason} ({action.status})
          </p>
          {action.status === "pending" && (
            <>
              <button
                onClick={() => approveAction(API_BASE, action.id).then(reload).catch((err: Error) => setError(err.message))}
              >
                Approve
              </button>
              <button
                onClick={() => {
                  const reason = window.prompt("Rejection reason");
                  if (reason) {
                    rejectAction(API_BASE, action.id, reason).then(reload).catch((err: Error) => setError(err.message));
                  }
                }}
              >
                Reject
              </button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
