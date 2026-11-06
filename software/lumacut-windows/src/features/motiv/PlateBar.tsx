import { useState } from 'react';
import { ChevronUp, Plus } from 'lucide-react';
import { useDoc } from '@/store/doc';
import { Button, confirmDialog, Menu, MenuButton, type MenuEntry } from '@/ui/kit';
import { useEditor } from './editor';
import * as ops from './ops';
import { fmt } from './render';

export function PlateBar() {
  const doc = useDoc((s) => s.doc), selCount = useDoc((s) => s.selection.length);
  const [menu, setMenu] = useState<{ x: number; y: number; plate: number } | null>(null);
  const count = (i: number) => doc.elements.filter((e) => e.plate === i).length;
  const askDelete = async (i: number) => {
    const n = count(i);
    if (n === 0 || await confirmDialog({ title: `Platte ${i + 1} entfernen?`, body: `${n} ${n === 1 ? 'Objekt wird' : 'Objekte werden'} mitgelöscht. Rückgängig holt alles zurück.`, okLabel: 'Entfernen', danger: true })) ops.deletePlate(i);
  };
  const moveItems: MenuEntry[] = [
    ...Array.from({ length: doc.plateCount }, (_, i) => ({ label: `Platte ${i + 1}`, disabled: i === doc.activePlate, onClick: () => ops.moveSelectionToPlate(i) })),
    { separator: true }, { label: 'Neue Platte', onClick: () => ops.moveSelectionToPlate(doc.plateCount) },
  ];
  return <div className="mv-plates" data-testid="plate-bar">
    <div className="mv-plate-list" role="tablist" aria-label="Platten">
      {Array.from({ length: doc.plateCount }, (_, i) => (
        <button key={i} type="button" role="tab" className="mv-plate" aria-selected={i === doc.activePlate} data-testid={`plate-${i}`}
          title={`Platte ${i + 1}: ${count(i)} ${count(i) === 1 ? 'Objekt' : 'Objekte'} (Bild auf, Bild ab). Rechtsklick: entfernen.`}
          onClick={() => ops.setPlate(i)}
          onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, plate: i }); }}>
          Platte {i + 1}
        </button>))}
    </div>
    <Button variant="ghost" size="sm" iconOnly icon={<Plus size={14} />} title="Platte hinzufügen" aria-label="Platte hinzufügen" onClick={ops.addPlate} data-testid="plate-add" />
    {selCount > 0 && <MenuButton variant="ghost" size="sm" items={moveItems} data-testid="plate-move">Auswahl verschieben auf<ChevronUp size={13} /></MenuButton>}
    <div className="grow" />
    <SelectionInfo />
    <MousePos />
    {menu && <Menu x={menu.x} y={menu.y} onClose={() => setMenu(null)} items={[
      { label: `Platte ${menu.plate + 1} entfernen`, disabled: doc.plateCount <= 1, onClick: () => void askDelete(menu.plate) },
    ]} />}
  </div>;
}

function SelectionInfo() {
  useDoc((s) => s.doc); const n = useDoc((s) => s.selection).length;
  if (!n) return null;
  const b = ops.selectionBox();
  return <span className="mv-readout mono" data-testid="sel-info">{n === 1 ? '1 Objekt' : `${n} Objekte`} · {b ? `${fmt(b.maxX - b.minX)} × ${fmt(b.maxY - b.minY)} mm` : ''}</span>;
}
function MousePos() {
  const m = useEditor((s) => s.mouse);
  return <span className="mv-readout mono mv-pos" data-testid="mouse-pos">{m ? `X ${fmt(m.x)}  Y ${fmt(m.y)} mm` : 'X –  Y –'}</span>;
}
