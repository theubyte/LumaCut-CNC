// Runs each browser spec against its own fresh simulator: specs change machine state (home, NOT-AUS, jobs).
// node tools/e2e_all.mjs [--python <path>] [spec-name ...]
import { spawn, spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';

const args = process.argv.slice(2);
const pyAt = args.indexOf('--python');
const python = pyAt >= 0 ? args.splice(pyAt, 2)[1] : 'python';
const wanted = args;
const slow = new Set(['start']);
const specs = readdirSync('tests/e2e').filter((f) => f.endsWith('.spec.ts')).map((f) => f.replace('.spec.ts', '')).filter((s) => !wanted.length || wanted.includes(s));
const failed = [];
let port = 8110;

for (const spec of specs) {
  port += 1;
  const sim = spawn(python, ['tools/sim_pi.py', '--port', String(port), ...(slow.has(spec) ? ['--slow'] : [])], { env: { ...process.env, PYTHONUTF8: '1' }, stdio: 'ignore' });
  await new Promise((r) => setTimeout(r, 6000));
  const r = spawnSync('npx', ['playwright', 'test', `tests/e2e/${spec}.spec.ts`], {
    shell: true, stdio: 'inherit', env: { ...process.env, LC_PORT: process.env.LC_PORT ?? String(port - 8110 + 5200), LUMACUT_DEV_PI: `http://127.0.0.1:${port}` },
  });
  sim.kill();
  if (r.status !== 0) failed.push(spec);
}
console.log(failed.length ? `FEHLER in: ${failed.join(', ')}` : `Alle ${specs.length} Bereiche grün`);
process.exit(failed.length ? 1 : 0);
