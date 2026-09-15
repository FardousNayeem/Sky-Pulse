/** Display helpers. Pure functions, no data fetching. */

export const compactNumber = (n: number): string =>
  new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);

export const percent = (share: number, digits = 3): string =>
  `${(share * 100).toFixed(digits)}%`;

export const clockTime = (unixSeconds: number): string =>
  new Date(unixSeconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export const dateTime = (unixSeconds: number): string =>
  new Date(unixSeconds * 1000).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export function relativeTime(unixSeconds: number): string {
  const seconds = Math.floor(Date.now() / 1000) - unixSeconds;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function durationFromMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const hours = minutes / 60;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

/**
 * Severity band for an alert, used for colour only.
 *
 * Relative to the horizon's own bar, not an absolute z. Each horizon sets a
 * different threshold - `fast` demands more evidence than `deep` because it
 * takes far more shots - so a flat cutoff would paint every fast alert the
 * same colour and every deep one a different one, for no reason to do with
 * how unusual either is.
 */
export function severity(zscore: number, threshold = 4): "high" | "medium" | "low" {
  if (zscore >= threshold * 2.5) return "high";
  if (zscore >= threshold * 1.5) return "medium";
  return "low";
}

/** A URL as something readable: the host, and a hint of the path. */
export function linkLabel(url: string): string {
  try {
    const { hostname, pathname } = new URL(url);
    const host = hostname.replace(/^www\./, "");
    const tail = pathname.replace(/\/$/, "").split("/").filter(Boolean).pop();
    return tail ? `${host}/${tail.slice(0, 28)}` : host;
  } catch {
    return url.slice(0, 40);
  }
}

/** Compact lag reading for the ingest readout. */
export function lagLabel(seconds: number | null): string {
  if (seconds === null) return "no data";
  if (seconds < 90) return "live";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m behind`;
  return `${(seconds / 3600).toFixed(1)}h behind`;
}
