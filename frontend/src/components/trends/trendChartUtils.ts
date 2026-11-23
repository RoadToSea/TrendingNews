import type { TrendSeriesDTO } from "@/api/types";

/** High-contrast categorical palette used to distinguish trend events. */
export const TREND_EVENT_PALETTE = [
  "#2563eb",
  "#0d9488",
  "#d97706",
  "#e11d48",
  "#7c3aed",
  "#16a34a",
  "#ea580c",
  "#0284c7",
  "#c026d3",
  "#65a30d",
  "#4f46e5",
  "#dc2626",
  "#0891b2",
  "#9333ea",
  "#ca8a04",
  "#059669",
] as const;

/** Input parameters for computing a symmetric, today-centered X axis. */
export interface CenteredXAxisInput {
  dates: string[];
  series: TrendSeriesDTO[];
  isCompact: boolean;
}

/** Computed symmetric numeric X-axis bounds centered on anchorDate (x = 0). */
export interface CenteredXAxisConfig {
  anchorDate: string;
  axisLimit: number;
  tickStep: number;
  maxPastData: number;
}

/** Adaptive Y-axis min/max bounds derived from active series data. */
export interface AdaptiveYBounds {
  yMin: number;
  yMax: number;
}

/** Input parameters for deterministic same-day scatter dodge layout. */
export interface SingleDayLayoutInput {
  series: TrendSeriesDTO[];
  anchorDate: string;
  maxPastData: number;
  yMin: number;
  yMax: number;
  isCompact: boolean;
}

interface PlacedPoint {
  x: number;
  y: number;
}

interface SingleDayCandidate {
  eventId: number;
  date: string;
  dayOffset: number;
  hotIndex: number;
  dailyRank: number;
}

interface LayoutPolicy {
  candidates: number[];
  step: number;
  yClear: number;
}

const MS_PER_DAY = 86_400_000;
const SINGLE_DAY_DESKTOP_DODGE = [-0.14, 0.14, -0.29, 0.29, -0.42, 0.42];
const SINGLE_DAY_COMPACT_DODGE = [-0.18, 0.18, -0.38, 0.38];
const MULTI_DAY_DODGE = [0, -0.16, 0.16, -0.34, 0.34];

/** Return a consistent vivid color for an event series index. */
export function getEventColor(index: number): string {
  const len = TREND_EVENT_PALETTE.length;
  return TREND_EVENT_PALETTE[((index % len) + len) % len];
}

/** Parse an ISO date string (YYYY-MM-DD) into a UTC midnight timestamp. */
export function parseIsoDateUtc(iso: string): number {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso.trim());
  if (!match) return Number.NaN;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

/** Compute whole-day signed difference (isoA - isoB) in UTC calendar days. */
export function diffDaysUtc(isoA: string, isoB: string): number {
  const a = parseIsoDateUtc(isoA);
  const b = parseIsoDateUtc(isoB);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0;
  return Math.round((a - b) / MS_PER_DAY);
}

/** Shift an ISO date string by offsetDays and return YYYY-MM-DD. */
export function shiftIsoDateUtc(anchorIso: string, offsetDays: number): string {
  const base = parseIsoDateUtc(anchorIso);
  if (!Number.isFinite(base)) return anchorIso;
  const shifted = new Date(base + Math.round(offsetDays) * MS_PER_DAY);
  const year = shifted.getUTCFullYear();
  const month = String(shifted.getUTCMonth() + 1).padStart(2, "0");
  const day = String(shifted.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function resolveAnchorDate(dates: string[], series: TrendSeriesDTO[]): string {
  if (dates.length > 0) return dates[dates.length - 1];
  let latest = "";
  for (const s of series) {
    for (const pt of s.points) {
      if (pt.date > latest) latest = pt.date;
    }
  }
  return latest;
}

function resolveTickStep(halfSpan: number, isCompact: boolean): number {
  if (halfSpan <= 4) return 1;
  if (halfSpan <= 7) return isCompact ? 2 : 1;
  if (halfSpan <= 14) return isCompact ? 4 : 2;
  return isCompact ? 6 : 3;
}

/**
 * Compute symmetric X-axis bounds centered on anchorDate (x = 0) so today
 * always lies at exact 50% horizontal center and renders as an explicit tick.
 */
export function computeCenteredXAxis({
  dates,
  series,
  isCompact,
}: CenteredXAxisInput): CenteredXAxisConfig {
  const anchorDate = resolveAnchorDate(dates, series);
  let maxPastData = 0;

  if (anchorDate) {
    for (const s of series) {
      for (const pt of s.points) {
        const offset = diffDaysUtc(pt.date, anchorDate);
        if (-offset > maxPastData) maxPastData = -offset;
      }
    }
  }

  if (maxPastData === 0) {
    return { anchorDate, axisLimit: isCompact ? 2 : 3, tickStep: 1, maxPastData: 0 };
  }

  const halfSpan = Math.max(isCompact ? 2 : 3, maxPastData);
  const tickStep = resolveTickStep(halfSpan, isCompact);
  const rawLimit = Math.max(halfSpan, maxPastData + 1);
  const axisLimit = Math.ceil(rawLimit / tickStep) * tickStep;

  return { anchorDate, axisLimit, tickStep, maxPastData };
}

/** Compute padded Y-axis bounds zoomed around actual hot_index values. */
export function computeAdaptiveYBounds(series: TrendSeriesDTO[]): AdaptiveYBounds {
  let minVal = Number.POSITIVE_INFINITY;
  let maxVal = Number.NEGATIVE_INFINITY;

  for (const s of series) {
    for (const pt of s.points) {
      if (pt.hot_index < minVal) minVal = pt.hot_index;
      if (pt.hot_index > maxVal) maxVal = pt.hot_index;
    }
  }

  if (!Number.isFinite(minVal) || !Number.isFinite(maxVal)) {
    return { yMin: 0, yMax: 100 };
  }

  const dataSpan = maxVal - minVal;
  const snap = dataSpan <= 15 ? 2 : 5;
  const minSpan = snap === 2 ? 12 : 20;
  const pad = Math.max(2, dataSpan * 0.22);
  const upperCap = maxVal > 100 ? Math.ceil((maxVal + pad) / snap) * snap : 100;

  let yMin = Math.max(0, Math.floor((minVal - pad) / snap) * snap);
  let yMax = Math.min(upperCap, Math.ceil((maxVal + pad) / snap) * snap);

  while (yMax - yMin < minSpan && (yMin > 0 || yMax < upperCap)) {
    yMin = Math.max(0, yMin - snap);
    yMax = Math.min(upperCap, yMax + snap);
  }

  return { yMin, yMax };
}

function buildLayoutPolicy(
  maxPastData: number,
  ySpan: number,
  isCompact: boolean,
  singleCount: number,
  hasOccupied: boolean,
): LayoutPolicy {
  if (maxPastData === 0) {
    if (singleCount <= 1 && !hasOccupied) {
      return { candidates: [0], step: 0.15, yClear: Math.max(1.8, ySpan * 0.12) };
    }
    if (isCompact) {
      return {
        candidates: SINGLE_DAY_COMPACT_DODGE,
        step: 0.2,
        yClear: Math.max(2.0, ySpan * 0.14),
      };
    }
    return {
      candidates: SINGLE_DAY_DESKTOP_DODGE,
      step: 0.15,
      yClear: Math.max(1.8, ySpan * 0.12),
    };
  }
  return {
    candidates: MULTI_DAY_DODGE,
    step: 0.16,
    yClear: Math.max(1.8, ySpan * (isCompact ? 0.12 : 0.1)),
  };
}

function pickBestDodgeOffset(
  item: SingleDayCandidate,
  occupied: PlacedPoint[],
  policy: LayoutPolicy,
): number {
  let bestDx = policy.candidates[0] ?? 0;
  let bestScore = -1;

  for (const dx of policy.candidates) {
    const x = item.dayOffset + dx;
    let collides = false;
    let minNormDist = Number.POSITIVE_INFINITY;

    for (const pt of occupied) {
      const distX = Math.abs(x - pt.x);
      const distY = Math.abs(item.hotIndex - pt.y);
      if (distY < policy.yClear && distX < policy.step * 0.92) {
        collides = true;
      }
      const normDist = Math.hypot(distX / policy.step, distY / policy.yClear);
      if (normDist < minNormDist) minNormDist = normDist;
    }

    if (!collides) return dx;
    if (minNormDist > bestScore) {
      bestScore = minNormDist;
      bestDx = dx;
    }
  }

  return bestDx;
}

/**
 * Compute deterministic horizontal beeswarm offsets (`dx` in day units)
 * within each day's column so same-day events stay distinct and clickable.
 */
export function computeSingleDayLayout({
  series,
  anchorDate,
  maxPastData,
  yMin,
  yMax,
  isCompact,
}: SingleDayLayoutInput): Map<string, number> {
  const occupiedByDay = new Map<number, PlacedPoint[]>();
  const singleByDay = new Map<number, SingleDayCandidate[]>();

  for (const s of series) {
    for (const pt of s.points) {
      const dayOffset = anchorDate ? diffDaysUtc(pt.date, anchorDate) : 0;
      if (s.is_multi_day) {
        const list = occupiedByDay.get(dayOffset) ?? [];
        list.push({ x: dayOffset, y: pt.hot_index });
        occupiedByDay.set(dayOffset, list);
      } else {
        const list = singleByDay.get(dayOffset) ?? [];
        list.push({
          eventId: s.event_id,
          date: pt.date,
          dayOffset,
          hotIndex: pt.hot_index,
          dailyRank: pt.daily_rank,
        });
        singleByDay.set(dayOffset, list);
      }
    }
  }

  const ySpan = yMax - yMin;
  const offsets = new Map<string, number>();

  for (const [dayOffset, items] of singleByDay) {
    items.sort(
      (a, b) =>
        b.hotIndex - a.hotIndex || a.dailyRank - b.dailyRank || a.eventId - b.eventId,
    );
    const placed = [...(occupiedByDay.get(dayOffset) ?? [])];
    const policy = buildLayoutPolicy(
      maxPastData,
      ySpan,
      isCompact,
      items.length,
      placed.length > 0,
    );

    for (const item of items) {
      const dx = pickBestDodgeOffset(item, placed, policy);
      placed.push({ x: item.dayOffset + dx, y: item.hotIndex });
      offsets.set(`${item.eventId}:${item.date}`, dx);
    }
  }

  return offsets;
}

/** Truncate text with an ellipsis when exceeding maxChars. */
export function truncateLabel(text: string, maxChars: number): string {
  if (maxChars <= 0) return "";
  const chars = Array.from(text);
  if (chars.length <= maxChars) return text;
  return `${chars.slice(0, Math.max(1, maxChars - 1)).join("")}...`;
}

/** Escape HTML metacharacters before interpolating strings into ECharts tooltips. */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Build a unique ECharts series name so legend items toggle independently. */
export function buildUniqueSeriesName(
  title: string,
  domainLabel: string,
  usedNames: Set<string>,
): string {
  if (!usedNames.has(title)) {
    usedNames.add(title);
    return title;
  }
  const withDomain = `${title} (${domainLabel})`;
  if (!usedNames.has(withDomain)) {
    usedNames.add(withDomain);
    return withDomain;
  }
  let suffix = 2;
  while (usedNames.has(`${withDomain} #${suffix}`)) suffix += 1;
  const unique = `${withDomain} #${suffix}`;
  usedNames.add(unique);
  return unique;
}
