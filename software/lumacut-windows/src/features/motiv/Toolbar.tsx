import { type ReactNode, useEffect, useRef, useState } from 'react';
import {
  AlignCenterHorizontal, AlignCenterVertical, AlignEndHorizontal, AlignEndVertical, AlignHorizontalDistributeCenter, AlignStartHorizontal, AlignStartVertical, AlignVerticalDistributeCenter,
  Camera, ChevronDown, FlipHorizontal2, FlipVertical2, Grid3x3, Group, Magnet, Maximize, Redo2, Split, SquareDashed, SquaresIntersect, SquaresSubtract, SquaresUnite, Undo2, Ungroup, ZoomIn, ZoomOut,
} from 'lucide-react';
import { isImage } from '@/core/model';
import { fetchScanBlob } from '@/pi/workspace';
import { useDoc } from '@/store/doc';
import { Button, MenuButton, type MenuEntry, Note, Slider, toast } from '@/ui/kit';
import { fileActions, newProject } from './commands';
import { useEditor, zoomPercent } from './editor';
import * as ops from './ops';

const S = 16;
const Sep = () => <div className="mv-sep" />;
function Tool({ title, icon, onClick, disabled, pressed, testid }: { title: string; icon: ReactNode; onClick(): void; disabled?: boolean; pressed?: boolean; testid?: string }) {
  return <Button variant="ghost" iconOnly title={title} icon={icon} onClick={onClick} disabled={disabled} pressed={pressed} aria-label={title} data-testid={testid} />;
}

export function Toolbar() {
  const ref = useRef<HTMLDivElement>(null);
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setNarrow(e.contentRect.width < 1080));
    ro.observe(ref.current!);
    return () => ro.disconnect();
  }, []);
  const undoable = useDoc((s) => s.past.length > 0), redoable = useDoc((s) => s.future.length > 0), undo = useDoc((s) => s.undo), redo = useDoc((s) => s.redo);
  const selKey = useDoc((s) => s.selection); useDoc((s) => s.doc.elements);
  const ed = useEditor(); const zoom = ed.zoom;
  const sel = ops.selectedEls(), vectors = sel.filter((e) => !isImage(e)), units = new Set(sel.map((e) => e.groupId ?? e.id)).size;
  const fileItems: MenuEntry[] = [
    { label: 'Neu', kbd: 'Strg+N', onClick: () => void newProject() },
    { separator: true },
    { label: 'Öffnen vom Pi …', kbd: 'Strg+O', onClick: fileActions.open },
    { label: 'Datei öffnen …', onClick: fileActions.openLocal },
    { separator: true },
    { label: 'Speichern auf dem Pi', kbd: 'Strg+S', onClick: fileActions.save },
    { label: 'Als Datei speichern …', kbd: 'Strg+Umschalt+S', onClick: fileActions.saveLocal },
    { label: 'Umbenennen …', onClick: () => ed.set({ dialog: 'rename' }) },
    { separator: true },
    { label: 'Importieren …', kbd: 'Strg+I', onClick: fileActions.importFile },
    { label: 'Exportieren …', kbd: 'Strg+E', onClick: () => ed.set({ dialog: 'export' }) },
  ];
  const alignItems: MenuEntry[] = [
    { label: 'Links', icon: <AlignStartVertical size={15} />, onClick: () => ops.align('left') },
    { label: 'Mitte waagerecht', icon: <AlignCenterVertical size={15} />, onClick: () => ops.align('centerX') },
    { label: 'Rechts', icon: <AlignEndVertical size={15} />, onClick: () => ops.align('right') },
    { separator: true },
    { label: 'Oben', icon: <AlignStartHorizontal size={15} />, onClick: () => ops.align('top') },
    { label: 'Mitte senkrecht', icon: <AlignCenterHorizontal size={15} />, onClick: () => ops.align('centerY') },
    { label: 'Unten', icon: <AlignEndHorizontal size={15} />, onClick: () => ops.align('bottom') },
    { separator: true },
    { label: 'Waagerecht verteilen', icon: <AlignHorizontalDistributeCenter size={15} />, disabled: units < 3, onClick: () => ops.distribute(true) },
    { label: 'Senkrecht verteilen', icon: <AlignVerticalDistributeCenter size={15} />, disabled: units < 3, onClick: () => ops.distribute(false) },
  ];
  const any = selKey.length > 0;
  const hint = units > 1 ? '' : ' an der Arbeitsfläche';
  return <div className="mv-bar" ref={ref} role="toolbar" aria-label="Aktionen">
    <MenuButton variant="ghost" items={fileItems} data-testid="file-menu">Datei<ChevronDown size={14} /></MenuButton>
    <Sep />
    <Tool title="Rückgängig (Strg+Z)" icon={<Undo2 size={S} />} onClick={undo} disabled={!undoable} testid="undo" />
    <Tool title="Wiederholen (Strg+Y)" icon={<Redo2 size={S} />} onClick={redo} disabled={!redoable} testid="redo" />
    {any && <>
      <Sep />
      {narrow
        ? <MenuButton variant="ghost" items={alignItems} title="Ausrichten und verteilen" aria-label="Ausrichten und verteilen"><AlignCenterVertical size={S} /><ChevronDown size={13} /></MenuButton>
        : <div className="mv-group" role="group" aria-label="Ausrichten">
          <Tool title={`Links ausrichten${hint}`} icon={<AlignStartVertical size={S} />} onClick={() => ops.align('left')} testid="align-left" />
          <Tool title={`Waagerecht mittig${hint}`} icon={<AlignCenterVertical size={S} />} onClick={() => ops.align('centerX')} />
          <Tool title={`Rechts ausrichten${hint}`} icon={<AlignEndVertical size={S} />} onClick={() => ops.align('right')} />
          <Tool title={`Oben ausrichten${hint}`} icon={<AlignStartHorizontal size={S} />} onClick={() => ops.align('top')} />
          <Tool title={`Senkrecht mittig${hint}`} icon={<AlignCenterHorizontal size={S} />} onClick={() => ops.align('centerY')} />
          <Tool title={`Unten ausrichten${hint}`} icon={<AlignEndHorizontal size={S} />} onClick={() => ops.align('bottom')} />
          {units >= 3 && <>
            <Tool title="Waagerecht verteilen" icon={<AlignHorizontalDistributeCenter size={S} />} onClick={() => ops.distribute(true)} />
            <Tool title="Senkrecht verteilen" icon={<AlignVerticalDistributeCenter size={S} />} onClick={() => ops.distribute(false)} />
          </>}
        </div>}
      <Sep />
      <Tool title="Links und rechts spiegeln" icon={<FlipHorizontal2 size={S} />} onClick={() => ops.mirror(true)} />
      <Tool title="Oben und unten spiegeln" icon={<FlipVertical2 size={S} />} onClick={() => ops.mirror(false)} />
      {vectors.length >= 2 && <>
        <Sep />
        <Tool title="Verschweißen" icon={<SquaresUnite size={S} />} onClick={() => ops.booleanSel('union')} testid="bool-union" />
        <Tool title="Abziehen: vordere von der untersten Form" icon={<SquaresSubtract size={S} />} onClick={() => ops.booleanSel('subtract')} testid="bool-subtract" />
        <Tool title="Schnittmenge" icon={<SquaresIntersect size={S} />} onClick={() => ops.booleanSel('intersect')} testid="bool-intersect" />
      </>}
      <Sep />
      {sel.length >= 2 && <Tool title="Gruppieren (Strg+G)" icon={<Group size={S} />} onClick={ops.group} testid="group" />}
      {sel.some((e) => e.groupId) && <Tool title="Gruppe auflösen (Strg+Umschalt+G)" icon={<Ungroup size={S} />} onClick={ops.ungroup} />}
      {ops.canSplit(sel) && <Tool title="In einzelne Teile aufteilen" icon={<Split size={S} />} onClick={ops.splitSel} testid="split" />}
      <Tool title="Kontur erzeugen" icon={<SquareDashed size={S} />} onClick={() => ed.set({ dialog: 'contour' })} testid="contour" />
    </>}
    <div className="grow" />
    <BackgroundControl />
    <Sep />
    <Tool title={`Am Raster einrasten: ${ed.snapGrid ? 'an' : 'aus'}`} icon={<Grid3x3 size={S} />} pressed={ed.snapGrid} onClick={() => ed.setPref('snapGrid', !ed.snapGrid)} testid="snap-grid" />
    <Tool title={`An Objekten einrasten: ${ed.snapObjects ? 'an' : 'aus'} (Strg beim Ziehen setzt aus)`} icon={<Magnet size={S} />} pressed={ed.snapObjects} onClick={() => ed.setPref('snapObjects', !ed.snapObjects)} testid="snap-objects" />
    <Sep />
    <Tool title="Verkleinern (Strg+-)" icon={<ZoomOut size={S} />} onClick={() => ed.zoomCentered(0.8)} />
    <button type="button" className="mv-zoom tnum" title="Maßstab: 100 % ist echte Größe am Bildschirm. Klick: Arbeitsfläche einpassen." onClick={() => ed.fit()} data-testid="zoom-label">{zoomPercent(zoom)} %</button>
    <Tool title="Vergrößern (Strg++)" icon={<ZoomIn size={S} />} onClick={() => ed.zoomCentered(1.25)} />
    <Tool title="Einpassen (F), Auswahl einpassen (Umschalt+F)" icon={<Maximize size={S} />} onClick={() => ed.fit()} testid="fit" />
  </div>;
}

/** The camera scan as a background. It lives in the editor store only and never touches the document. */
function BackgroundControl() {
  const ed = useEditor(); const [open, setOpen] = useState(false); const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener('pointerdown', away, true);
    return () => window.removeEventListener('pointerdown', away, true);
  }, [open]);
  const load = async () => {
    setBusy(true);
    try {
      const r = await fetchScanBlob();
      if (!r) { toast('Auf dem Pi liegt noch kein Scan. Unter Maschine scannen.', 'info'); return; }
      const bmp = await createImageBitmap(r.blob);
      ed.bgImage?.close();
      ed.set({ bgImage: bmp, bgOn: true });
    } catch (e) { toast(`Scan nicht geladen: ${(e as Error).message}`, 'bad'); } finally { setBusy(false); }
  };
  return <div className="mv-pop-wrap" ref={box}>
    <Button variant="ghost" iconOnly icon={<Camera size={S} />} pressed={ed.bgOn && !!ed.bgImage} title="Kamerabild als Hintergrund" aria-label="Kamerabild als Hintergrund" onClick={() => setOpen(!open)} data-testid="bg-button" />
    {open && <div className="mv-pop" data-testid="bg-pop">
      <div className="mv-pop-title">Kamerabild als Hintergrund</div>
      <Button size="sm" disabled={busy} onClick={() => void load()}>{busy ? 'Lädt …' : ed.bgImage ? 'Neu vom Pi laden' : 'Scan vom Pi laden'}</Button>
      {ed.bgImage && <>
        <label className="check"><input type="checkbox" checked={ed.bgOn} onChange={(e) => ed.set({ bgOn: e.target.checked })} />Anzeigen</label>
        <div className="field"><label>Deckkraft</label>
          <Slider value={Math.round(ed.bgAlpha * 100)} min={10} max={100} unit="%" onChange={(v) => ed.set({ bgAlpha: v / 100 })} /></div>
      </>}
      <Note>Nur zur Orientierung, wird nie gelasert. Das Werkstück kann verschoben sein: vor dem Lasern neu scannen.</Note>
    </div>}
  </div>;
}
