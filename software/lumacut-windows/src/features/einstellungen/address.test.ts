import { describe, expect, it } from 'vitest';
import { parseAddress } from './address';

describe('Pi-Adresse', () => {
  it('adds scheme and port to a bare address', () => {
    expect(parseAddress('192.168.2.89')).toEqual({ url: 'http://192.168.2.89:8080' });
    expect(parseAddress(' lumacut.local/ ')).toEqual({ url: 'http://lumacut.local:8080' });
    expect(parseAddress('lumacut')).toEqual({ url: 'http://lumacut:8080' });
  });
  it('keeps what was given explicitly', () => {
    expect(parseAddress('192.168.2.89:8081')).toEqual({ url: 'http://192.168.2.89:8081' });
    expect(parseAddress('http://192.168.2.89')).toEqual({ url: 'http://192.168.2.89' });
    expect(parseAddress('https://laser.example.com')).toEqual({ url: 'https://laser.example.com' });
  });
  it('refuses what cannot be right', () => {
    expect(parseAddress('')).toHaveProperty('error');
    expect(parseAddress('http://u:p@192.168.2.89')).toHaveProperty('error');
    expect(parseAddress('192.168.2.89?a=1')).toHaveProperty('error');
    expect(parseAddress('ftp://192.168.2.89')).toHaveProperty('error');
    expect(parseAddress('http://laser.example.com')).toHaveProperty('error');
  });
});
