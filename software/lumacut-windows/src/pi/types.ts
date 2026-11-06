/** /api/status as in docs/PI_API_REFERENZ.md §3. While `busy` some fields may be missing, so all are optional. */
export type JobState = 'idle' | 'homing' | 'probing' | 'focusing' | 'running' | 'finishing' | 'parking' | 'complete' | 'aborted' | 'error' | (string & {});
export interface JobInfo { state: JobState; file?: string | null; line?: number; total?: number; error?: string; phase?: string | null; probe?: { done: number; total: number } | null }
export interface FrameInfo { state: string; mode?: string; line?: number; total?: number; error?: string }
export type QueueItem = Record<string, unknown>;
export interface QueueInfo { state: string; current: unknown; items: QueueItem[]; max?: number }
export interface MachineConfig {
  machine_name?: string; validated?: boolean; travels?: { x: number; y: number; z: number };
  motion?: { accel: number; speed: number }; frame_power_pct?: number; focus_gap_mm?: number; light_brightness?: number;
  exhaust_auto?: boolean; exhaust_after_s?: number; z_clearance_mm?: number; thickness_tolerance_mm?: number; probe_offset_x_mm?: number; probe_offset_y_mm?: number;
  [k: string]: unknown;
}
export interface MachineStatus {
  connected?: boolean; state?: string; owner?: string; busy?: boolean; stale_ms?: number | null; activity?: string;
  homed?: boolean; z_homed?: boolean; home_needs_confirm?: boolean; emergency_latched?: boolean; laser_armed?: boolean; fault?: string;
  position?: [number, number, number]; identity?: string; firmware?: string; lights?: boolean; light_brightness?: number; light_dimmable?: boolean; exhaust?: boolean;
  job?: JobInfo; frame?: FrameInfo; queue?: QueueInfo; config?: MachineConfig; camera?: { available: boolean; device?: string };
  park_corner_mm?: { x: number; y: number }; workpiece_surface_z?: number | null; workpiece_above_bed_mm?: number | null; bed_map?: unknown; origin?: unknown;
  firmware_release?: unknown; firmware_update?: unknown; panel?: unknown; features?: string[]; sync?: { project?: number; scan?: number; workspace?: number };
  disk_free_mb?: number; serial_errors?: number; recent?: string[];
  [k: string]: unknown;
}
export class PiError extends Error { constructor(message: string, public status: number) { super(message); } }
