import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatShortTime(iso: string | null | undefined): string {
  if (!iso) return "";
  if (iso.length >= 16 && iso.includes("T")) {
    return `${iso.slice(5, 10)} ${iso.slice(11, 16)}`;
  }
  return iso.slice(0, 16);
}

export function formatMetricLabel(metrics: Record<string, number | string> | undefined): string {
  if (!metrics) return "";
  const pairs: string[] = [];
  if (metrics.score !== undefined) pairs.push(`Score ${metrics.score}`);
  if (metrics.ups !== undefined) pairs.push(`Ups ${metrics.ups}`);
  if (metrics.stars !== undefined) pairs.push(`Stars ${metrics.stars}`);
  if (metrics.views !== undefined) pairs.push(`Views ${metrics.views}`);
  if (metrics.upvotes !== undefined) pairs.push(`Upvotes ${metrics.upvotes}`);
  return pairs.join(" · ");
}
