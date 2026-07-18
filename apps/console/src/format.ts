export function formatDateTime(value: string | undefined): string {
  if (!value) return 'In progress';
  return new Intl.DateTimeFormat('en-CA', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(value));
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat('en-CA', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`));
}

export function percent(value: number, digits = 0): string {
  return new Intl.NumberFormat('en-CA', { style: 'percent', maximumFractionDigits: digits }).format(value);
}

export function scoreBand(score: number): 'CRITICAL' | 'HIGH' | 'MODERATE' | 'LOW' {
  if (score >= 17) return 'CRITICAL';
  if (score >= 10) return 'HIGH';
  if (score >= 5) return 'MODERATE';
  return 'LOW';
}

export function shortHash(value: string): string {
  if (value.length <= 18) return value;
  return `${value.slice(0, 12)}…${value.slice(-6)}`;
}
