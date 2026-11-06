/** Pi address as typed: "192.168.2.89", "lumacut.local", "http://x:8081". Same rules as PiClient.baseUrl on Android. */
export const DEFAULT_PI = 'http://192.168.2.89:8080';

const LOCAL_SUFFIXES = ['.local', '.lan', '.home', '.fritz.box', '.internal', '.home.arpa'];
function isLocalIpv4(host: string) {
  const parts = host.split('.');
  if (parts.length !== 4) return false;
  const n = parts.map(Number);
  if (n.some((v, i) => !/^\d+$/.test(parts[i]) || v > 255)) return false;
  return n[0] === 10 || n[0] === 127 || (n[0] === 192 && n[1] === 168) || (n[0] === 172 && n[1] >= 16 && n[1] <= 31);
}
export function isHomeNetwork(host: string) {
  const h = host.toLowerCase();
  return isLocalIpv4(h) || h === 'localhost' || (!h.includes('.') && /[a-z]/.test(h)) || LOCAL_SUFFIXES.some((s) => h.endsWith(s));
}

/** The normalized base URL, or a sentence that says what is wrong. */
export function parseAddress(text: string): { url: string } | { error: string } {
  const t = text.trim().replace(/\/+$/, '');
  if (!t) return { error: 'Adresse fehlt.' };
  const hasScheme = t.includes('://');
  let u: URL;
  try { u = new URL(hasScheme ? t : `http://${t}`); }
  catch { return { error: 'Adresse nicht lesbar. Beispiele: 192.168.2.89, lumacut.local, https://…' }; }
  if (!['http:', 'https:'].includes(u.protocol) || !u.hostname) return { error: 'Adresse nicht lesbar. Beispiele: 192.168.2.89, lumacut.local, https://…' };
  if (u.username || u.password || u.search || u.hash) return { error: 'Adresse ohne Benutzer, ? oder #.' };
  if (u.protocol === 'http:' && !isHomeNetwork(u.hostname)) return { error: 'Unverschlüsselt (http) nur im Heimnetz. Für Adressen im Internet https:// verwenden.' };
  const explicitPort = /:\d+/.test(t.split('://').pop()!.split('/')[0]);
  const port = hasScheme || explicitPort ? (u.port ? `:${u.port}` : '') : ':8080';
  return { url: `${u.protocol}//${u.hostname}${port}${u.pathname === '/' ? '' : u.pathname}` };
}
