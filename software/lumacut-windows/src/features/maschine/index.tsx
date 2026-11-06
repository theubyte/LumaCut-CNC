import { useState } from 'react';
import { Tabs } from '@/ui/kit';
import { Steuerung } from './steuerung';
import { Kamera } from './kamera';
import { Kalibrieren } from './kalibrieren';
import { SystemTab } from './system';
import './maschine.css';

type Tab = 'steuerung' | 'kamera' | 'kalibrieren' | 'system';
const TABS: { value: Tab; label: string }[] = [
  { value: 'steuerung', label: 'Steuerung' }, { value: 'kamera', label: 'Kamera' },
  { value: 'kalibrieren', label: 'Kalibrieren' }, { value: 'system', label: 'System' },
];
const load = (): Tab => { try { const v = localStorage.getItem('lc.maschine.tab') as Tab | null; return v && TABS.some((t) => t.value === v) ? v : 'steuerung'; } catch { return 'steuerung'; } };

export default function Maschine() {
  const [tab, setTab] = useState<Tab>(load);
  const choose = (t: Tab) => { setTab(t); try { localStorage.setItem('lc.maschine.tab', t); } catch { /* per-device convenience */ } };
  return <div className="m-root">
    <Tabs tabs={TABS} value={tab} onChange={choose} />
    <div className="m-body">
      {tab === 'steuerung' && <Steuerung />}
      {tab === 'kamera' && <Kamera />}
      {tab === 'kalibrieren' && <Kalibrieren />}
      {tab === 'system' && <SystemTab />}
    </div>
  </div>;
}
