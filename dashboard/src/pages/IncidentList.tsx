import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../Badge";
import { fetchIncidents, type Incident } from "../api";

const API_BASE = import.meta.env.VITE_DASHBOARD_API_BASE as string;

export function IncidentList() {
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchIncidents(API_BASE)
      .then(setIncidents)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <div className="page">
      <h1>Incidents</h1>
      {error && <p className="error-state" role="alert">{error}</p>}
      {!error && incidents === null && <p className="loading-state">Loading…</p>}
      {!error && incidents !== null && incidents.length === 0 && (
        <p className="empty-state">No incidents yet.</p>
      )}
      {!error && incidents !== null && incidents.length > 0 && (
        <ul className="incident-list">
          {incidents.map((incident) => (
            <li key={incident.id}>
              <Link className="incident-card" to={`/incidents/${incident.id}`}>
                <div className="incident-card-row">
                  <span className="incident-card-title">{incident.alertname}</span>
                  <Badge value={incident.status} />
                </div>
                <div className="incident-card-time">
                  {new Date(incident.created_at).toLocaleString()}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
