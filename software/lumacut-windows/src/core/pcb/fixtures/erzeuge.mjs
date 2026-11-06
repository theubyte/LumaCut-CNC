// Erzeugt die Beispielplatine (LED-Blinker mit Timer, 60 x 40 mm) als Gerber und Excellon.
// Aufruf im Ordner software/lumacut-windows: node src/core/pcb/fixtures/erzeuge.mjs
// Die Schaltung ist nur plausibles Testmaterial, sie wurde nie gebaut.
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const out = dirname(fileURLToPath(import.meta.url));
const c = (v) => String(Math.round(v * 1e5)); // Format 4.5 mm
const xy = (x, y) => `X${c(x)}Y${c(y)}`;
const head = (fn) => `G04 LumaCut Beispielplatine, selbst erzeugt*\n%TF.FileFunction,${fn}*%\n%FSLAX45Y45*%\n%MOMM*%\n%LPD*%\nG75*\nG01*\n`;
const end = 'M02*\n';
const line = (pts) => `${xy(...pts[0])}D02*\n` + pts.slice(1).map((p) => `${xy(...p)}D01*\n`).join('');
const flash = (p) => `${xy(...p)}D03*\n`;

// Bauteile
const U = { 1: [26.19, 23.81], 2: [26.19, 21.27], 3: [26.19, 18.73], 4: [26.19, 16.19], 5: [33.81, 16.19], 6: [33.81, 18.73], 7: [33.81, 21.27], 8: [33.81, 23.81] };
const J1 = [[6, 24], [6, 18.92]];
const R1 = [[38, 34], [48.16, 34]];
const R2 = [[48.16, 13], [38, 13]];
const R3 = [[16, 18.73], [16, 8.57]];
const C1 = [[20, 21.27], [20, 26.35]];
const C2 = [[33.81, 10.19], [28.73, 10.19]];
const LED = [[24, 6], [26.54, 6]];
const HOLES = [[4, 4], [56, 4], [56, 36], [4, 36]];
const gndPads = [U[1], J1[1], C1[1], C2[1], LED[1]];
const roundPads = [U[2], U[3], U[4], U[5], U[6], U[7], U[8], R1[0], R1[1], R2[0], R2[1], R3[0], R3[1], C1[0], C1[1], C2[0], C2[1], LED[0], LED[1]];
const signalPadsBottom = [U[2], U[3], U[4], U[5], U[6], U[7], U[8], R1[0], R1[1], R2[0], R2[1], R3[0], R3[1], C1[0], C2[0], LED[0], J1[0]];

// Kupfer oben: Makro mit Variablen und Rechnung (abgerundetes Pad), Bögen G02/G03 in Leiterbahnen
let top = head('Copper,L1,Top');
top += '%AMRUNDPAD*0 Abgerundetes Rechteck: Breite, Hoehe, Radius*$4=$1-2x$3*$5=$2-2x$3*21,1,$4,$2,0,0,0*21,1,$1,$5,0,0,0*1,1,2x$3,$4/2,$5/2*1,1,2x$3,-$4/2,$5/2*1,1,2x$3,$4/2,-$5/2*1,1,2x$3,-$4/2,-$5/2*%\n';
top += '%ADD10C,0.6*%\n%ADD11C,0.9*%\n%ADD12C,1.7*%\n%ADD13RUNDPAD,1.7X1.7X0.35*%\n%ADD14O,2.4X1.7*%\n%ADD15R,2.2X2.2*%\n';
// Versorgung, 0,9 mm, mit gerundeter Ecke
top += 'D11*\n' + xy(6, 24) + 'D02*\n' + xy(6, 32) + 'D01*\n' + 'G02*\n' + xy(8, 34) + 'I200000J0D01*\nG01*\n' + xy(38, 34) + 'D01*\n';
top += line([U[8], [33.81, 34]]);
top += line([U[4], [30, 16.19], [30, 26], [33.81, 26]]);
// Signale, 0,6 mm
top += 'D10*\n';
top += line([R1[1], [50, 34]]) + 'G02*\n' + xy(52, 32) + 'I0J-200000D01*\nG01*\n' + xy(52, 15) + 'D01*\n' + 'G02*\n' + xy(50, 13) + 'I-200000J0D01*\nG01*\n' + xy(...R2[0]) + 'D01*\n';
top += line([U[7], [52, 21.27]]);
top += line([R2[1], [38, 18.73], U[6]]);
top += line([U[5], C2[0]]);
top += line([U[2], C1[0]]);
top += line([U[3], R3[0]]);
top += line([R3[1], [16, 8]]) + 'G03*\n' + xy(18, 6) + 'I200000J0D01*\nG01*\n' + xy(...LED[0]) + 'D01*\n';
// Pads
top += 'D13*\n' + flash(U[1]);
top += 'D12*\n' + roundPads.filter((p) => !C2.includes(p) && !C1.includes(p)).map(flash).join('');
top += 'D14*\n' + [C1[0], C1[1], C2[0], C2[1]].map(flash).join('');
top += 'D15*\n' + J1.map(flash).join('');
top += end;

// Kupfer unten: Massefläche als Region, Freistellungen mit LPC, Wärmefallen als Makro, Pads wieder mit LPD
let bot = head('Copper,L2,Bot');
bot += '%AMWAERME*7,0,0,3.4,2.2,0.7,45*%\n';
bot += '%ADD20C,2.8*%\n%ADD21WAERME*%\n%ADD22C,1.7*%\n%ADD23C,0.6*%\n%ADD24C,1.6*%\n%ADD25C,5.0*%\n';
bot += 'G36*\n' + xy(2, 1) + 'D02*\n' + xy(58, 1) + 'D01*\n' + 'G03*\n' + xy(59, 2) + 'I0J100000D01*\nG01*\n' + xy(59, 38) + 'D01*\n' + 'G03*\n' + xy(58, 39) + 'I-100000J0D01*\nG01*\n' + xy(2, 39) + 'D01*\n' + 'G03*\n' + xy(1, 38) + 'I0J-100000D01*\nG01*\n' + xy(1, 2) + 'D01*\n' + 'G03*\n' + xy(2, 1) + 'I100000J0D01*\nG01*\nG37*\n';
bot += '%LPC*%\n';
bot += 'D25*\n' + HOLES.map(flash).join('');
bot += 'D20*\n' + signalPadsBottom.map(flash).join('');
bot += 'D24*\n' + line([U[6], [30, 20], U[2]]);
bot += 'D21*\n' + gndPads.map(flash).join('');
bot += '%LPD*%\n';
bot += 'D23*\n' + line([U[6], [30, 20], U[2]]);
bot += 'D22*\n' + [...signalPadsBottom, ...gndPads].map(flash).join('');
bot += end;

// Lötstopp: Öffnungen sind die Pads plus Zugabe
const mask = (fn) => {
  let s = head(fn) + '%ADD30C,1.9*%\n%ADD31R,2.4X2.4*%\n%ADD32O,2.6X1.9*%\n%ADD33P,2.2X8*%\n';
  s += 'D30*\n' + [U[2], U[3], U[4], U[5], U[6], U[7], U[8], R1[0], R1[1], R2[0], R2[1], R3[0], R3[1], LED[0], LED[1]].map(flash).join('');
  s += 'D33*\n' + flash(U[1]);
  s += 'D32*\n' + [C1[0], C1[1], C2[0], C2[1]].map(flash).join('');
  s += 'D31*\n' + J1.map(flash).join('');
  return s + end;
};

// Beschriftung: kleine Strichschrift auf 4 x 6 Raster
const FONT = {
  A: [[[0, 0], [0, 4], [2, 6], [4, 4], [4, 0]], [[0, 3], [4, 3]]], B: [[[0, 0], [0, 6], [3, 6], [4, 5], [3, 3], [0, 3]], [[3, 3], [4, 1], [3, 0], [0, 0]]],
  C: [[[4, 1], [3, 0], [1, 0], [0, 1], [0, 5], [1, 6], [3, 6], [4, 5]]], D: [[[0, 0], [0, 6], [3, 6], [4, 5], [4, 1], [3, 0], [0, 0]]],
  E: [[[4, 0], [0, 0], [0, 6], [4, 6]], [[0, 3], [3, 3]]], G: [[[4, 5], [3, 6], [1, 6], [0, 5], [0, 1], [1, 0], [3, 0], [4, 1], [4, 3], [2, 3]]],
  I: [[[2, 0], [2, 6]]], J: [[[0, 1], [1, 0], [3, 0], [4, 1], [4, 6]]], K: [[[0, 0], [0, 6]], [[4, 6], [0, 2]], [[1, 3], [4, 0]]],
  L: [[[0, 6], [0, 0], [4, 0]]], M: [[[0, 0], [0, 6], [2, 3], [4, 6], [4, 0]]], N: [[[0, 0], [0, 6], [4, 0], [4, 6]]],
  R: [[[0, 0], [0, 6], [3, 6], [4, 5], [4, 4], [3, 3], [0, 3]], [[2, 3], [4, 0]]], T: [[[0, 6], [4, 6]], [[2, 6], [2, 0]]],
  U: [[[0, 6], [0, 1], [1, 0], [3, 0], [4, 1], [4, 6]]], V: [[[0, 6], [2, 0], [4, 6]]],
  1: [[[1, 5], [2, 6], [2, 0]], [[1, 0], [3, 0]]], 2: [[[0, 5], [1, 6], [3, 6], [4, 5], [4, 4], [0, 0], [4, 0]]], 3: [[[0, 5], [1, 6], [3, 6], [4, 5], [4, 4], [3, 3], [4, 2], [4, 1], [3, 0], [1, 0], [0, 1]], [[1, 3], [3, 3]]],
  '+': [[[0, 3], [4, 3]], [[2, 1], [2, 5]]], '-': [[[0, 3], [4, 3]]],
};
const text = (str, x, y, h) => {
  const k = h / 6; let s = '';
  [...str].forEach((ch, i) => {
    for (const st of FONT[ch] ?? []) s += line(st.map(([u, v]) => [x + (u + i * 5.4) * k, y + v * k]));
  });
  return s;
};
let silk = head('Legend,Top') + '%ADD40C,0.18*%\nD40*\n';
silk += text('LUMACUT BLINKER', 12, 36.6, 1.8);
silk += text('U1', 26, 25.6, 1.3) + text('R1', 41.5, 35.2, 1.3) + text('R2', 41.5, 14.2, 1.3) + text('R3', 11.3, 13, 1.3);
silk += text('C1', 22, 23, 1.3) + text('C2', 29.5, 12, 1.3) + text('LED', 23.2, 2.6, 1.3) + text('+', 8.8, 23.3, 1.3) + text('-', 8.8, 18.2, 1.3);
for (const [a, b] of [[R1[0], R1[1]], [R2[1], R2[0]]]) silk += line([[a[0] + 2, a[1] + 1], [b[0] - 2, b[1] + 1], [b[0] - 2, b[1] - 1], [a[0] + 2, a[1] - 1], [a[0] + 2, a[1] + 1]]);
silk += line([[15, 16.7], [17, 16.7], [17, 10.6], [15, 10.6], [15, 16.7]]);
silk += end;

// Umriss mit gerundeten Ecken (G75-Bögen), dünn gezeichnet
const r = 2, W = 60, H = 40;
let edge = head('Profile,NP') + '%ADD50C,0.1*%\nD50*\n' + xy(r, 0) + 'D02*\n';
edge += xy(W - r, 0) + 'D01*\nG03*\n' + xy(W, r) + `I0J${c(r)}D01*\nG01*\n`;
edge += xy(W, H - r) + 'D01*\nG03*\n' + xy(W - r, H) + `I-${c(r)}J0D01*\nG01*\n`;
edge += xy(r, H) + 'D01*\nG03*\n' + xy(0, H - r) + `I0J-${c(r)}D01*\nG01*\n`;
edge += xy(0, r) + 'D01*\nG03*\n' + xy(r, 0) + `I${c(r)}J0D01*\nG01*\n` + end;

// Bohrdatei, metrisch mit Dezimalpunkt
const f3 = (v) => v.toFixed(3);
const hit = ([x, y]) => `X${f3(x)}Y${f3(y)}\n`;
const small = [...Object.values(U), R1[0], R1[1], R2[0], R2[1], R3[0], R3[1], C1[0], C1[1], C2[0], C2[1], LED[0], LED[1]];
let drl = 'M48\n; LumaCut Beispielplatine, selbst erzeugt\nMETRIC,TZ\nT1C0.800\nT2C1.200\nT3C3.200\n%\nG90\nG05\n';
drl += 'T1\n' + small.map(hit).join('') + 'T2\n' + J1.map(hit).join('') + 'T3\n' + HOLES.map(hit).join('') + 'T0\nM30\n';

const files = {
  'beispiel.GTL': top, 'beispiel.GBL': bot, 'beispiel.GTS': mask('Soldermask,Top'), 'beispiel.GBS': mask('Soldermask,Bot'),
  'beispiel.GTO': silk, 'beispiel.GKO': edge, 'beispiel.DRL': drl,
};
for (const [n, s] of Object.entries(files)) writeFileSync(join(out, n), s);
console.log('geschrieben:', Object.keys(files).join(', '));
