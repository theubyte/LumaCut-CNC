/** Rechenkern eines Auftrags: G-Code und Werkzeugweg für eine Platte. Läuft im Worker oder, ohne Worker, direkt. */
import { writeMarlin, type Motion } from './gcode';
import { configureBed, type Doc } from './model';
import { parseToolpathCompact, type CompactToolpath, type ToolpathStats } from './toolpath';

export interface JobRequest { doc: Doc; plate: number; motion?: Motion; appVersion?: string; bed: { width: number; height: number; parkX: number; parkY: number } }
export interface JobResult { gcode: string; toolpath: CompactToolpath; stats: ToolpathStats }

export function computeJob(req: JobRequest): JobResult {
  configureBed(req.bed.width, req.bed.height, req.bed.parkX, req.bed.parkY);
  const view: Doc = { ...req.doc, elements: req.doc.elements.filter((e) => e.plate === req.plate) };
  const gcode = writeMarlin(view, { appVersion: req.appVersion, motion: req.motion });
  const toolpath = parseToolpathCompact(gcode);
  return { gcode, toolpath, stats: toolpath.stats };
}
