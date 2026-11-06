import { useEffect, useRef, useState } from 'react';
import { loadFont } from '@/core/text';
import { FileUp, ImagePlus, type LucideIcon, MousePointer2, PenLine, PenTool, RectangleHorizontal, Circle, Ruler, Shapes, Spline, Type } from 'lucide-react';
import { plateElements } from '@/core/model';
import { useDoc } from '@/store/doc';
import { useUi } from '@/store/ui';
import { Button, Menu, type MenuEntry, toast } from '@/ui/kit';
import { type Tool, useEditor } from './editor';
import { MotivDialogs } from './Dialogs';
import { handleKey, selectionMenu } from './commands';
import { LayersPanel } from './LayersPanel';
import * as ops from './ops';
import { PlateBar } from './PlateBar';
import { PropsPanel } from './PropsPanel';
import { Stage } from './stage';
import { setStage } from './stageRef';
import { Toolbar } from './Toolbar';
import './motiv.css';

const TOOLS: { key: Tool; label: string; icon: LucideIcon; kbd: string; gap?: boolean }[] = [
  { key: 'select', label: 'Auswählen', icon: MousePointer2, kbd: 'V' },
  { key: 'node', label: 'Knoten bearbeiten', icon: Spline, kbd: 'A' },
  { key: 'rect', label: 'Rechteck', icon: RectangleHorizontal, kbd: 'R', gap: true },
  { key: 'ellipse', label: 'Ellipse', icon: Circle, kbd: 'E' },
  { key: 'poly', label: 'Linie und Polygon', icon: PenLine, kbd: 'L' },
  { key: 'pen', label: 'Stift mit Kurven', icon: PenTool, kbd: 'P' },
  { key: 'text', label: 'Text', icon: Type, kbd: 'T', gap: true },
  { key: 'image', label: 'Bild einfügen', icon: ImagePlus, kbd: 'I' },
  { key: 'measure', label: 'Messen', icon: Ruler, kbd: 'M', gap: true },
];
const HINTS: Partial<Record<Tool, string>> = {
  node: 'Knoten ziehen. Doppelklick auf die Linie fügt einen Knoten ein, Doppelklick auf einen Knoten macht ihn rund oder eckig, Entf löscht ihn.',
  rect: 'Rechteck aufziehen. Umschalt: Quadrat, Alt: von der Mitte aus.',
  ellipse: 'Ellipse aufziehen. Umschalt: Kreis, Alt: von der Mitte aus.',
  poly: 'Punkte setzen. Klick auf den ersten Punkt schließt die Form, Doppelklick oder Enter beendet, Rücktaste nimmt den letzten zurück.',
  pen: 'Klick setzt eine Ecke, Ziehen eine runde Stelle. Klick auf den ersten Punkt schließt, Enter beendet.',
  text: 'Klicken, wo der Text beginnen soll.',
  measure: 'Von Punkt zu Punkt ziehen. Ecken und Mitten rasten ein.',
};

export default function MotivView() {
  // Schrift gleich laden: nach T und Klick muss sofort getippt werden können.
  useEffect(() => { void loadFont('sans-serif', false).catch(() => undefined); }, []);
  useEffect(() => {
    const h = (e: KeyboardEvent) => handleKey(e);
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);
  return (
    <div className="mv">
      <Toolbar />
      <div className="mv-body">
        <ToolColumn />
        <CanvasHost />
        <aside className="mv-side" aria-label="Ebenen und Eigenschaften">
          <LayersPanel />
          <PropsPanel />
        </aside>
      </div>
      <PlateBar />
      <MotivDialogs />
      <ContextMenu />
    </div>
  );
}

function ToolColumn() {
  const tool = useEditor((s) => s.tool);
  return <div className="mv-tools" role="toolbar" aria-orientation="vertical" aria-label="Werkzeuge">
    {TOOLS.map((t) => { const I = t.icon; return <div key={t.key} className={t.gap ? 'mv-tool-wrap gap' : 'mv-tool-wrap'}>
      <button type="button" className="mv-tool" data-testid={`tool-${t.key}`} aria-pressed={tool === t.key} title={`${t.label} (${t.kbd})`} onClick={() => pickTool(t.key)}>
        <I size={17} strokeWidth={1.8} /><span className="mv-tool-key">{t.kbd}</span>
      </button></div>; })}
  </div>;
}
export function pickTool(t: Tool) {
  if (t === 'image') { useEditor.getState().setTool('select'); void ops.importDialog(ops.IMAGE_FILTERS); return; }
  useEditor.getState().setTool(t);
}

function CanvasHost() {
  const host = useRef<HTMLDivElement>(null), scene = useRef<HTMLCanvasElement>(null), overlay = useRef<HTMLCanvasElement>(null);
  const [dropping, setDropping] = useState(false);
  useEffect(() => {
    const stage = new Stage(scene.current!, overlay.current!, host.current!);
    setStage(stage);
    if (import.meta.env.DEV) (window as unknown as { __lc: unknown }).__lc = { useDoc, useEditor, stage };
    const keys = (e: KeyboardEvent | PointerEvent) => stage.trackKeys(e);
    window.addEventListener('keydown', keys); window.addEventListener('keyup', keys); window.addEventListener('pointermove', keys);
    return () => { window.removeEventListener('keydown', keys); window.removeEventListener('keyup', keys); window.removeEventListener('pointermove', keys); setStage(null); stage.destroy(); };
  }, []);
  const tool = useEditor((s) => s.tool);
  return <div ref={host} className="mv-canvas" data-testid="canvas-host"
    onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setDropping(true); }}
    onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDropping(false); }}
    onDrop={async (e) => {
      e.preventDefault(); setDropping(false);
      for (const f of [...e.dataTransfer.files]) {
        try { await ops.importBytes(f.name, new Uint8Array(await f.arrayBuffer())); } catch (x) { toast(`${f.name}: ${(x as Error).message}`, 'bad'); }
      }
    }}>
    <canvas ref={scene} className="mv-layer" />
    <canvas ref={overlay} className="mv-layer" data-testid="canvas" tabIndex={-1} />
    <EmptyState />
    {HINTS[tool] && <div className="mv-hint" data-testid="tool-hint">{HINTS[tool]}</div>}
    {dropping && <div className="mv-drop"><FileUp size={22} />Datei hier ablegen</div>}
  </div>;
}

function EmptyState() {
  const empty = useDoc((s) => plateElements(s.doc).length === 0), tool = useEditor((s) => s.tool), plate = useDoc((s) => s.doc.activePlate), go = useUi((s) => s.go);
  if (!empty || tool !== 'select') return null;
  return <div className="mv-empty" data-testid="empty-state">
    <div className="mv-empty-title">{plate > 0 ? `Platte ${plate + 1} ist noch leer` : 'Was soll auf die Platte?'}</div>
    <div className="mv-empty-text">Eine Form zeichnen, eine Datei hierher ziehen oder mit einer Vorlage beginnen.</div>
    <div className="mv-empty-actions">
      <Button icon={<RectangleHorizontal size={15} />} onClick={() => pickTool('rect')}>Form zeichnen</Button>
      <Button icon={<FileUp size={15} />} onClick={() => void ops.importDialog()}>Datei öffnen</Button>
      <Button icon={<Shapes size={15} />} onClick={() => go('werkstatt')}>Vorlage aus der Werkstatt</Button>
    </div>
  </div>;
}

function ContextMenu() {
  const menu = useEditor((s) => s.menu), set = useEditor((s) => s.set);
  if (!menu) return null;
  const items: MenuEntry[] = selectionMenu();
  return <Menu x={menu.x} y={menu.y} items={items} onClose={() => set({ menu: null })} />;
}
