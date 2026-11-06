/**
 * Zahlenformat wie Javas `%.nf`: Rundung HALF_UP auf den kürzesten Dezimalziffern
 * (nicht auf dem exakten Binärwert wie `toFixed`): 1.0005 wird zu "1.001".
 * Vorzeichen bleibt auch bei -0 und bei Werten, die auf 0 runden ("-0.000").
 */
function expand(s: string): string {
  const e = s.indexOf('e');
  if (e < 0) return s;
  const exp = Number(s.slice(e + 1));
  const mant = s.slice(0, e), dot = mant.indexOf('.');
  const digits = dot < 0 ? mant : mant.slice(0, dot) + mant.slice(dot + 1);
  const point = (dot < 0 ? mant.length : dot) + exp;
  if (point <= 0) return '0.' + '0'.repeat(-point) + digits;
  if (point >= digits.length) return digits + '0'.repeat(point - digits.length);
  return digits.slice(0, point) + '.' + digits.slice(point);
}

export function fmtFixed(v: number, digits: number, sep = '.'): string {
  if (Number.isNaN(v)) return 'NaN';
  const neg = v < 0 || Object.is(v, -0);
  const sign = neg ? '-' : '';
  const a = neg ? -v : v;
  if (a === Infinity) return sign + 'Infinity';
  const s = expand('' + a);
  const dot = s.indexOf('.');
  const int = dot < 0 ? s : s.slice(0, dot);
  const frac = dot < 0 ? '' : s.slice(dot + 1);
  if (frac.length <= digits) {
    const f = frac + '0'.repeat(digits - frac.length);
    return digits === 0 ? sign + int : sign + int + sep + f;
  }
  let head = int + frac.slice(0, digits);
  if (frac.charCodeAt(digits) >= 53) {
    const width = head.length;
    head = (head.length <= 15 ? String(Number(head) + 1) : String(BigInt(head) + 1n)).padStart(width, '0');
  }
  if (digits === 0) return sign + head;
  const cut = head.length - digits;
  return sign + head.slice(0, cut) + sep + head.slice(cut);
}

export const fmt3 = (v: number) => fmtFixed(v, 3);
