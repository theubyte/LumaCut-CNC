/**
 * Small XML reader without a browser DOM, so the parsers run in tests and in the app alike.
 * Not namespace-aware (tags keep their prefix, as the Android parser does). A DOCTYPE is skipped,
 * entities other than the five predefined ones and numeric ones are never expanded, so a file
 * cannot pull in anything external or blow up through entity expansion.
 */
export interface XmlNode { tag: string; attrs: Record<string, string>; children: XmlNode[]; text: string; parent: XmlNode | null }
export class XmlError extends Error {}

const NAMED: Record<string, string> = { lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" };
const decodeEntities = (s: string) => s.indexOf('&') < 0 ? s : s.replace(/&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);/g, (all, e: string) => {
  if (e[0] !== '#') return NAMED[e] ?? all;
  const cp = e[1] === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
  return cp > 0 && cp <= 0x10FFFF ? String.fromCodePoint(cp) : all;
});

const isSpace = (c: string) => c === ' ' || c === '\n' || c === '\t' || c === '\r';
const NAME_END = /[\s/>=]/;

export function parseXml(src: string): XmlNode {
  let i = 0;
  let root: XmlNode | null = null;
  let cur: XmlNode | null = null;
  const n = src.length;
  while (i < n) {
    const lt = src.indexOf('<', i);
    if (lt < 0) { if (cur) throw new XmlError('Unerwartetes Dateiende'); break; }
    if (cur && lt > i) cur.text += decodeEntities(src.slice(i, lt));
    i = lt;
    if (src.startsWith('<!--', i)) {
      const e = src.indexOf('-->', i + 4); if (e < 0) throw new XmlError('Kommentar ohne Ende'); i = e + 3; continue;
    }
    if (src.startsWith('<![CDATA[', i)) {
      const e = src.indexOf(']]>', i + 9); if (e < 0) throw new XmlError('CDATA ohne Ende');
      if (cur) cur.text += src.slice(i + 9, e); i = e + 3; continue;
    }
    if (src.startsWith('<?', i)) {
      const e = src.indexOf('?>', i + 2); if (e < 0) throw new XmlError('Anweisung ohne Ende'); i = e + 2; continue;
    }
    if (src.startsWith('<!', i)) {
      let depth = 0, k = i + 2;
      for (; k < n; k++) {
        const c = src[k];
        if (c === '[') depth++; else if (c === ']') depth--; else if (c === '>' && depth <= 0) break;
      }
      if (k >= n) throw new XmlError('DOCTYPE ohne Ende');
      i = k + 1; continue;
    }
    if (src[i + 1] === '/') {
      const e = src.indexOf('>', i); if (e < 0) throw new XmlError('Unerwartetes Dateiende');
      const name = src.slice(i + 2, e).trim();
      if (!cur || cur.tag !== name) throw new XmlError(`Schließendes Tag ${name} passt nicht`);
      cur = cur.parent; i = e + 1; continue;
    }
    let k = i + 1;
    while (k < n && !NAME_END.test(src[k])) k++;
    const tag = src.slice(i + 1, k);
    if (!tag) throw new XmlError('Leeres Tag');
    const node: XmlNode = { tag, attrs: {}, children: [], text: '', parent: cur };
    let selfClose = false;
    for (;;) {
      while (k < n && isSpace(src[k])) k++;
      if (k >= n) throw new XmlError('Unerwartetes Dateiende');
      if (src[k] === '>') { k++; break; }
      if (src[k] === '/' && src[k + 1] === '>') { selfClose = true; k += 2; break; }
      const nameStart = k;
      while (k < n && !NAME_END.test(src[k])) k++;
      const name = src.slice(nameStart, k);
      if (!name) throw new XmlError('Ungültiges Attribut');
      while (k < n && isSpace(src[k])) k++;
      if (src[k] !== '=') { node.attrs[name] = ''; continue; }
      k++;
      while (k < n && isSpace(src[k])) k++;
      const q = src[k];
      if (q !== '"' && q !== "'") throw new XmlError('Attribut ohne Anführungszeichen');
      const end = src.indexOf(q, k + 1);
      if (end < 0) throw new XmlError('Attribut ohne Ende');
      node.attrs[name] = decodeEntities(src.slice(k + 1, end));
      k = end + 1;
    }
    if (cur) cur.children.push(node);
    else if (root) throw new XmlError('Mehr als ein Wurzelelement');
    else root = node;
    if (!selfClose) cur = node;
    i = k;
  }
  if (cur) throw new XmlError(`Tag ${cur.tag} wird nicht geschlossen`);
  if (!root) throw new XmlError('Kein XML gefunden');
  return root;
}

export const attr = (n: XmlNode, name: string) => n.attrs[name] ?? '';
export const localName = (tag: string) => { const i = tag.indexOf(':'); return i >= 0 ? tag.slice(i + 1) : tag; };
export function allByTag(n: XmlNode, local: string, out: XmlNode[] = []): XmlNode[] {
  if (localName(n.tag) === local) out.push(n);
  for (const c of n.children) allByTag(c, local, out);
  return out;
}
export const childByTag = (n: XmlNode, tag: string) => n.children.find((c) => c.tag === tag) ?? null;
