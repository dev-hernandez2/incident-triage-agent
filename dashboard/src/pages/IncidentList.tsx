import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchIncidents, type Incident } from "../api";

const API_BASE = import.meta.env.VITE_DASHBOARD_API_BASE as string;

export function IncidentList() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchIncidents(API_BASE)
      .then(setIncidents)
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) return <p role="alert">{error}</p>;

  return (
    <ul>
      {incidents.map((incident) => (
        <li key={incident.id}>
          <Link to={`/incidents/${incident.id}`}>
            {incident.alertname} — {incident.status}
          </Link>
        </li>
      ))}
    </ul>
  );
}
