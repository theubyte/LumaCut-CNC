import { create } from 'zustand';

export type Dest = 'material' | 'motiv' | 'start' | 'platine' | 'werkstatt' | 'maschine' | 'einstellungen';
export type ThemePref = 'system' | 'light' | 'dark';

const load = <T,>(k: string, d: T): T => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
const save = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* per-device convenience only */ } };

export function applyTheme(p: ThemePref) {
  const dark = p === 'dark' || (p === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

interface UiState {
  dest: Dest; theme: ThemePref; piUrl: string;
  go(d: Dest): void; setTheme(t: ThemePref): void; setPiUrl(u: string): void;
}
export const useUi = create<UiState>((set) => ({
  dest: load<Dest>('lc.dest', 'motiv'), theme: load<ThemePref>('lc.theme', 'system'), piUrl: load('lc.piUrl', 'http://192.168.2.89:8080'),
  go: (dest) => { save('lc.dest', dest); set({ dest }); },
  setTheme: (theme) => { save('lc.theme', theme); applyTheme(theme); set({ theme }); },
  setPiUrl: (piUrl) => { save('lc.piUrl', piUrl); set({ piUrl }); },
}));
