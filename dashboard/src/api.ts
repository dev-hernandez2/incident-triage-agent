export interface Incident {
  id: string;
  alertname: string;
  status: string;
  created_at: string;
}

export interface TimelineEntry {
  created_at: string;
  event_type: string;
  detail: unknown;
}

export interface FindingSummary {
  id: string;
  summary: string;
  root_cause: string;
  confidence: string;
  evidence: unknown[];
  suggested_fix: { type: string; [key: string]: unknown };
}

export interface IncidentDetail extends Incident {
  findings: FindingSummary[];
  timeline: TimelineEntry[];
}

export interface ActionSummary {
  id: string;
  type: string;
  status: string;
  reason: string;
}

export async function fetchIncidents(apiBase: string): Promise<Incident[]> {
  const response = await fetch(`${apiBase}/incidents`, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`failed to fetch incidents: ${response.status}`);
  }
  return response.json();
}

export async function fetchIncident(apiBase: string, id: string): Promise<IncidentDetail> {
  const response = await fetch(`${apiBase}/incidents/${id}`, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`failed to fetch incident ${id}: ${response.status}`);
  }
  return response.json();
}

export async function fetchActions(apiBase: string, incidentId: string): Promise<ActionSummary[]> {
  const response = await fetch(`${apiBase}/incidents/${incidentId}/actions`, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`failed to fetch actions for incident ${incidentId}: ${response.status}`);
  }
  return response.json();
}

export async function approveAction(apiBase: string, actionId: string): Promise<void> {
  const response = await fetch(`${apiBase}/actions/${actionId}/approve`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`failed to approve action ${actionId}: ${response.status}`);
  }
}

export async function rejectAction(
  apiBase: string,
  actionId: string,
  reason: string
): Promise<void> {
  const response = await fetch(`${apiBase}/actions/${actionId}/reject`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!response.ok) {
    throw new Error(`failed to reject action ${actionId}: ${response.status}`);
  }
}
