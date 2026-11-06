import { describe, expect, it } from 'vitest';
import { Bed, toMachine } from '@/core/model';
import type { MachineStatus } from '@/pi/types';
import { freeLock, headline, homeLock, jogCommand, moveLock, moveTarget, probeLock, zLock } from './locks';

const ready: MachineStatus = { connected: true, owner: 'Frei', state: 'Idle', homed: true, emergency_latched: false, config: { validated: true }, probe_xy_offset_mm: [-27.4, 13] };

describe('Jog as seen from the door', () => {
  it('matches the Android keys: right X−, left X+, up Y−, down Y+', () => {
    expect(jogCommand('right', 1)).toEqual({ axis: 'X', distance: -1 });
    expect(jogCommand('left', 10)).toEqual({ axis: 'X', distance: 10 });
    expect(jogCommand('up', 0.1)).toEqual({ axis: 'Y', distance: -0.1 });
    expect(jogCommand('down', 1)).toEqual({ axis: 'Y', distance: 1 });
  });
  it('only produces distances the Pi allows', () => {
    for (const dir of ['left', 'right', 'up', 'down'] as const) for (const step of [0.1, 1, 10] as const) {
      expect([-10, -1, -0.1, 0.1, 1, 10]).toContain(jogCommand(dir, step).distance);
    }
  });
});

describe('Locks explain themselves', () => {
  it('is free when ready', () => {
    expect(freeLock(ready, true)).toBeNull();
    expect(moveLock(ready, true)).toBeNull();
    expect(probeLock(ready, true)).toBeNull();
  });
  it('names the reason in order of importance', () => {
    expect(freeLock(ready, false)).toContain('nicht erreichbar');
    expect(freeLock({ ...ready, emergency_latched: true }, true)).toContain('Not-Aus');
    expect(freeLock({ ...ready, connected: false }, true)).toContain('USB');
    expect(freeLock({ ...ready, owner: 'lightburn' }, true)).toContain('LightBurn');
    expect(freeLock({ ...ready, owner: 'job' }, true)).toContain('belegt');
    expect(freeLock({ ...ready, job: { state: 'running', file: 'a.gcode' } }, true)).toContain('a.gcode');
    expect(freeLock({ ...ready, frame: { state: 'running' } }, true)).toContain('Rahmen');
  });
  it('does not flicker for the short internal owners', () => {
    expect(freeLock({ ...ready, owner: 'monitor' }, true)).toBeNull();
    expect(freeLock({ ...ready, owner: 'web' }, true)).toBeNull();
  });
  it('needs the release for homing, the reference for moves, the offset for probing', () => {
    expect(homeLock({ ...ready, config: { validated: false } }, true)).toContain('freigegeben');
    expect(moveLock({ ...ready, homed: false }, true)).toContain('referenziert');
    expect(moveLock({ ...ready, homed: false, reference: { lost: 'Kopf bewegt.' } }, true)).toContain('Kopf bewegt');
    expect(probeLock({ ...ready, probe_xy_offset_mm: null }, true)).toContain('Taster-Versatz');
    expect(probeLock({ ...ready, z_probe_supported: false }, true)).toContain('Taster');
  });
  it('needs a measured surface for Z', () => {
    expect(zLock(ready, true)).toContain('Abtasten');
    expect(zLock({ ...ready, workpiece_surface_z: 2 }, true)).toBeNull();
    expect(zLock({ ...ready, homed: false, workpiece_surface_z: 2 }, true)).toContain('referenziert');
  });
  it('headline follows the state', () => {
    expect(headline({ ...ready, emergency_latched: true }, true, 'http://x').title).toBe('Not-Aus aktiv');
    expect(headline({ ...ready, homed: false }, true, 'http://x').title).toBe('Nicht referenziert');
    expect(headline(ready, true, 'http://x').title).toBe('Bereit');
    expect(headline({}, false, 'http://1.2.3.4:8080').text).toContain('1.2.3.4:8080');
  });
});

describe('Zu Position fahren', () => {
  it('converts with toMachine and refuses targets outside the work area', () => {
    expect(moveTarget({ x: 10, y: 20 })).toEqual({ machine: toMachine({ x: 10, y: 20 }) });
    expect(moveTarget({ x: Bed.width + 1, y: 0 })).toHaveProperty('error');
    expect(moveTarget({ x: 0, y: -1 })).toHaveProperty('error');
  });
});
