import type { Stage } from './stage';

/** The mounted canvas, for commands that act on it from outside (keyboard, menus). */
let current: Stage | null = null;
export const setStage = (s: Stage | null) => { current = s; };
export const stage = () => current;
