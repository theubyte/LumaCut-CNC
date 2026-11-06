import type { Doc } from './model';
export class JobBuildError extends Error {}
export interface Motion { accel: number; speed: number }
/** Port of android/core MarlinWriter. Filled by the core port. */
export function writeMarlin(_doc: Doc, _opts: { appVersion?: string; motion?: Motion } = {}): string { throw new JobBuildError('noch nicht portiert'); }
