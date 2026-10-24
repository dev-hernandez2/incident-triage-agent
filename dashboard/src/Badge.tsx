const STATUS_COLORS: Record<string, string> = {
  received: "gray",
  resolved: "green",
  complete: "green",
  budget_exceeded: "amber",
  pending: "gray",
  approved: "green",
  executed: "green",
  executing: "blue",
  rejected: "red",
  failed: "red",
  high: "green",
  medium: "amber",
  low: "red",
};

export function Badge({ value }: { value: string }) {
  const color = STATUS_COLORS[value] ?? "gray";
  return <span className={`badge badge-${color}`}>{value.replace(/_/g, " ")}</span>;
}
