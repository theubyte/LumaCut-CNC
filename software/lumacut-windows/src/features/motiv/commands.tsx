import type { ReactNode } from 'react';
import { BringToFront, ClipboardPaste, Copy, CopyPlus, FlipHorizontal2, FlipVertical2, Group, ImageOff, Scissors, SendToBack, Split, SquareDashed, SquaresIntersect, SquaresSubtract, SquaresUnite, Trash2, Type, Ungroup } from 'lucide-react';
import { isImage, layerLabel, newDoc, plateElements } from '@/core/model';
import { openLocal, openProjectDialog, saveLocal, saveProjectToPi } from '@/pi/sync';
import { useDoc } from '@/store/doc';
import { confirmDialog, type MenuEntry, toast } from '@/ui/kit';
import { type Tool, useEditor } from './editor';
import * as ops from './ops';
import { stage } from './stageRef';

const inputFocused = () => { const a = document.activeElement; return !!a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT' || (a as HTMLElement).isContentEditable); };
const icon = (n: ReactNode) => n;

const TOOL_KEYS: Record<string, Tool> = { v: 'select', a: 'node', r: 'rect', e: 'ellipse', l: 'poly', p: 'pen', t: 'text', m: 'measure' };

/** Wraps file actions so a failure is one sentence, not a silent rejection. */
export const guarded = (what: string, f: () => Promise<unknown>) => { f().catch((e) => toast(`${what}: ${(e as Error).message}`, 'bad')); };

export async function newProject() {
  const s = useDoc.getState();
  if (s.dirty && (s.doc.elements.length > 0) && !await confirmDialog({ title: 'Neues Projekt beginnen?', body: 'Nicht gespeicherte Änderungen gehen verloren.', okLabel: 'Neu beginnen', danger: true })) return;
  useDoc.getState().load(newDoc());
  useEditor.getState().set({ node: null, draft: null, measure: null });
}
export const fileActions = {
  open: () => guarded('Öffnen', openProjectDialog),
  openLocal: () => guarded('Öffnen', openLocal),
  save: () => guarded('Speichern', saveProjectToPi),
  saveLocal: () => guarded('Speichern', () => saveLocal(true)),
  importFile: () => guarded('Importieren', () => ops.importDialog()),
};

export function handleKey(e: KeyboardEvent) {
  const ed = useEditor.getState(), doc = useDoc.getState();
  if (document.querySelector('.scrim')) return;
  const ctrl = e.ctrlKey || e.metaKey, key = e.key.toLowerCase();
  if (inputFocused()) {
    if (e.key === 'Escape') (document.activeElement as HTMLElement).blur();
    return;
  }
  const hit = (f: () => void) => { e.preventDefault(); f(); };
  if (ctrl) {
    if (key === 'z' && !e.shiftKey) return hit(doc.undo);
    if (key === 'y' || (key === 'z' && e.shiftKey)) return hit(doc.redo);
    if (key === 'a') return hit(ops.selectAll);
    if (key === 'c') return hit(ops.copySel);
    if (key === 'x') return hit(ops.cutSel);
    if (key === 'v') return hit(ops.paste);
    if (key === 'd') return hit(() => ops.duplicate());
    if (key === 'g') return hit(e.shiftKey ? ops.ungroup : ops.group);
    if (key === 's') return hit(e.shiftKey ? fileActions.saveLocal : fileActions.save);
    if (key === 'o') return hit(fileActions.open);
    if (key === 'n') return hit(() => void newProject());
    if (key === 'i') return hit(fileActions.importFile);
    if (key === 'e') return hit(() => ed.set({ dialog: 'export' }));
    if (key === '=' || key === '+') return hit(() => ed.zoomCentered(1.25));
    if (key === '-') return hit(() => ed.zoomCentered(0.8));
    if (key === 'arrowleft' || key === 'arrowright' || key === 'arrowup' || key === 'arrowdown') return arrow(e, 10);
    return;
  }
  if (e.altKey) return;
  switch (e.key) {
    case 'ArrowLeft': case 'ArrowRight': case 'ArrowUp': case 'ArrowDown': arrow(e, e.shiftKey ? 1 : 0.1); return;
    case 'Delete': case 'Backspace': {
      if (ed.draft) { const n = ed.draft.nodes.slice(0, -1); hit(() => ed.set({ draft: n.length ? { ...ed.draft!, nodes: n } : null })); return; }
      if (ed.tool === 'node' && stage()?.deleteActiveNode()) { e.preventDefault(); return; }
      hit(ops.deleteSel); return;
    }
    case 'Escape': if (stage()?.escape()) e.preventDefault(); return;
    case 'Enter': if (ed.draft) hit(() => stage()?.finishDraft(false)); return;
    case 'PageUp': hit(() => ops.setPlate(doc.doc.activePlate - 1)); return;
    case 'PageDown': hit(() => ops.setPlate(doc.doc.activePlate + 1)); return;
  }
  if (key === 'f') { const b = e.shiftKey ? ops.selectionBox() : null; return hit(() => ed.fit(b)); }
  if (key === 'i' && !e.shiftKey) return hit(() => void ops.importDialog(ops.IMAGE_FILTERS));
  const tool = !e.shiftKey ? TOOL_KEYS[key] : undefined;
  if (tool) hit(() => ed.setTool(tool));
}

/** Repeating keys while held count as one undo step. */
function arrow(e: KeyboardEvent, step: number) {
  e.preventDefault();
  const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0, dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
  const s = useDoc.getState();
  if (!s.selection.length) return;
  if (!e.repeat) { ops.nudge(dx, dy); return; }
  const ids = new Set(s.selection);
  s.mutate((d) => ({ ...d, elements: d.elements.map((x) => (ids.has(x.id) ? ops.movedBy(x, dx, dy) : x)) }));
}

/** The right-click menu: same words and shortcuts as the toolbar. */
export function selectionMenu(): MenuEntry[] {
  const st = useDoc.getState(), sel = ops.selectedEls(), s = 15, ed = useEditor.getState();
  const vectors = sel.filter((e) => !isImage(e));
  if (!sel.length) return [
    { label: 'Einfügen', icon: icon(<ClipboardPaste size={s} />), kbd: 'Strg+V', onClick: ops.paste },
    { label: 'Alles auswählen', kbd: 'Strg+A', onClick: ops.selectAll, disabled: !plateElements(st.doc).length },
    { separator: true },
    { label: 'Arbeitsfläche einpassen', kbd: 'F', onClick: () => ed.fit() },
  ];
  const items: MenuEntry[] = [
    { label: 'Ausschneiden', icon: icon(<Scissors size={s} />), kbd: 'Strg+X', onClick: ops.cutSel },
    { label: 'Kopieren', icon: icon(<Copy size={s} />), kbd: 'Strg+C', onClick: ops.copySel },
    { label: 'Einfügen', icon: icon(<ClipboardPaste size={s} />), kbd: 'Strg+V', onClick: ops.paste },
    { label: 'Duplizieren', icon: icon(<CopyPlus size={s} />), kbd: 'Strg+D', onClick: () => ops.duplicate() },
    { separator: true },
    { label: 'Gruppieren', icon: icon(<Group size={s} />), kbd: 'Strg+G', onClick: ops.group, disabled: sel.length < 2 },
    { label: 'Gruppe auflösen', icon: icon(<Ungroup size={s} />), kbd: 'Strg+Umschalt+G', onClick: ops.ungroup, disabled: !sel.some((e) => e.groupId) },
    { label: 'Aufteilen', icon: icon(<Split size={s} />), onClick: ops.splitSel, disabled: !ops.canSplit(sel) },
    { separator: true },
    { label: 'Links und rechts spiegeln', icon: icon(<FlipHorizontal2 size={s} />), onClick: () => ops.mirror(true) },
    { label: 'Oben und unten spiegeln', icon: icon(<FlipVertical2 size={s} />), onClick: () => ops.mirror(false) },
    { label: 'Nach vorn', icon: icon(<BringToFront size={s} />), onClick: () => ops.toFront(true) },
    { label: 'Nach hinten', icon: icon(<SendToBack size={s} />), onClick: () => ops.toFront(false) },
  ];
  if (vectors.length >= 2) items.push({ separator: true },
    { label: 'Verschweißen', icon: icon(<SquaresUnite size={s} />), onClick: () => ops.booleanSel('union') },
    { label: 'Abziehen', icon: icon(<SquaresSubtract size={s} />), onClick: () => ops.booleanSel('subtract') },
    { label: 'Schnittmenge', icon: icon(<SquaresIntersect size={s} />), onClick: () => ops.booleanSel('intersect') });
  items.push({ separator: true }, { label: 'Kontur erzeugen …', icon: icon(<SquareDashed size={s} />), onClick: () => ed.set({ dialog: 'contour' }) });
  if (sel.some(isImage)) items.push({ label: 'Vektorisieren …', icon: icon(<ImageOff size={s} />), onClick: () => ed.set({ dialog: 'vectorize' }) });
  if (sel.some((e) => e.text != null)) items.push({ label: 'In Pfade umwandeln', icon: icon(<Type size={s} />), onClick: ops.textToPaths });
  const layers = ops.shownLayers(st.doc, st.activeLayerId).filter((l) => sel.some((e) => e.layerId !== l.id));
  if (layers.length) { items.push({ separator: true }); for (const l of layers) items.push({ label: `Auf Ebene ${layerLabel(l)}`, onClick: () => ops.moveSelectionToLayer(l.id) }); }
  items.push({ separator: true }, { label: 'Löschen', icon: icon(<Trash2 size={s} />), kbd: 'Entf', onClick: ops.deleteSel });
  return items;
}
