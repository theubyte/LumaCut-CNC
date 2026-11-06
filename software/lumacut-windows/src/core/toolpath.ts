import type { Box } from './model';
export interface Segment { x0: number; y0: number; x1: number; y1: number; power: number; cut: boolean; line: number }
export interface ToolpathStats { cutMm: number; travelMm: number; seconds: number; maxPower: number; warnings: string[] }
export interface Toolpath { segments: Segment[]; bounds: Box | null; stats: ToolpathStats; lineCount: number }
/** Port of android/core Toolpath.parse. Filled by the core port. */
export function parseToolpath(_text: string): Toolpath { throw new Error('noch nicht portiert'); }
export const formatDuration = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h > 0 ? `${h} h ${String(m).padStart(2, '0')} min` : m > 0 ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s`;
};
