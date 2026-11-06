import type { ResistMethod } from '@/core/pcb/job';

/** What a 10 W, 450 nm diode can and cannot do on a circuit board. From physics and hobby reports, not tested on this machine. */
export const GEHT_NICHT = [
  { titel: 'Kupfer direkt abtragen', text: 'Kupfer wirft den Großteil von 450 nm zurück und leitet die Wärme sofort weg. Das Kupfer wird heiß, aber nicht abgetragen. Deshalb wird hier nur Lack entfernt und danach geätzt.' },
  { titel: 'FR4 schneiden', text: 'Das Epoxid verbrennt und qualmt giftig, die Glasfaser bleibt. Der Rand verkohlt und leitet. Platine sägen oder ritzen und brechen, im Freien oder mit Staubabsaugung.' },
  { titel: 'Löcher bohren', text: 'Aus demselben Grund geht auch das nicht. Der Laser setzt nur eine Marke, gebohrt wird von Hand oder mit der Bohrmaschine.' },
];

export const METHODEN: Record<ResistMethod, { name: string; kurz: string; text: string; braucht: string }> = {
  raster: {
    name: 'Raster negativ', kurz: 'Empfohlen',
    text: 'Der Laser entfernt den Lack überall außer auf den Leiterbahnen. Das Ätzbad trägt danach alles Kupfer außer den Leiterbahnen ab. Der übliche Weg bei Lack.',
    braucht: 'Kupferplatine, matten dunklen Sprühlack, Ätzmittel. Laufzeit ist länger als bei Isolation.',
  },
  isolation: {
    name: 'Isolation', kurz: 'Schneller',
    text: 'Nur Trennlinien um die Leiterbahnen. Das restliche Kupfer bleibt als Inseln ohne Verbindung stehen. Das spart Zeit und Ätzmittel. Mit „Restkupfer auch entfernen“ wird der Rest zusätzlich gerastert.',
    braucht: 'Dasselbe wie beim Rastern. Mehrere Durchgänge machen die Trennung breiter und sicherer.',
  },
  expose: {
    name: 'Fotofilm belichten', kurz: 'Nicht erprobt',
    text: 'Eigene Methode: Der Laser brennt nichts, er belichtet Negativ-Trockenfilm mit wenig Energie. Belichtet wird das Kupfer, entwickelt wird in Sodalösung. Solcher Film ist meist für 365 bis 405 nm ausgelegt, ob er bei 450 nm reagiert, steht im Datenblatt oder zeigt nur der Test.',
    braucht: 'Trockenfilm, Laminator, Sodalösung, abgedunkelter Raum. Für positiv beschichtete Platten stattdessen „Raster negativ“ wählen. Die Leistungsuntergrenze von 8 % kann für Film schon zu viel sein: dann nur über hohe Geschwindigkeit regeln.',
  },
};

export const TEXT_BOHRMARKEN = 'Ein kleiner Punkt in der Padmitte wird mitgeätzt. Der Bohrer findet dort von selbst die Mitte. Die Marke ersetzt das Ankörnen, nicht das Bohren.';
export const BRAUCHT_BOHRMARKEN = 'Denselben Lack und dieselbe Leistung wie der Ätzresist, danach einen Bohrer.';
export const TEXT_LOETSTOPP = 'Nach dem Ätzen wird die ganze Platine mit UV-Lötstopplack beschichtet und ausgehärtet. Der Laser legt danach die Pads frei. Ob das sauber bis aufs Kupfer geht, hängt vom Lack ab, Reste auf den Pads lassen sich mit einem Glasfaserstift entfernen.';
export const BRAUCHT_LOETSTOPP = 'UV-Lötstopplack, UV-Lampe, ein eigenes Probestück mit demselben Lack.';
export const TEXT_BESCHRIFTUNG = 'Bauteilnamen und Logos werden mit wenig Leistung in den Lötstopplack markiert. Sie erscheinen als hellere oder dunklere Spur, nicht als weißer Druck. Text auf Pads wird ausgespart.';
export const BRAUCHT_BESCHRIFTUNG = 'Eine ausgehärtete Lackschicht auf der Platine. Auf blankem FR4 gibt es nur braune, leicht verkohlte Schrift.';

export const LACK_HINWEIS = 'Matter schwarzer Lack nimmt 450 nm am besten auf. Blauer oder weißer Lack wirft das Licht zurück und geht schlecht ab. Bastler berichten, dass billiger Lack leichter abgeht als hochwertiger.';

export const SICHERHEIT = [
  'Lack- und Epoxiddampf nicht einatmen: Abluft an, Deckel zu, Brille für 450 nm auf.',
  'Ätzmittel: Handschuhe und Schutzbrille, gut lüften, nur Kunststoff- oder Glasschale. Persulfat gast aus, also nie dicht verschließen. Eisen(III)-chlorid greift Metall an und färbt dauerhaft.',
  'Verbrauchte Ätzlösung enthält gelöstes Kupfer: nicht in den Ausguss, sondern zur Schadstoffsammlung.',
];

export interface Schritt { titel: string; text: string; laser?: boolean }

export function arbeitsablauf(method: ResistMethod, mask: boolean, silk: boolean): Schritt[] {
  const film = method === 'expose';
  const out: Schritt[] = [
    { titel: 'Zuschneiden', text: 'Platine mit Zugabe sägen, nicht mit dem Laser. Passmarken liegen außerhalb des Umrisses.' },
    { titel: 'Reinigen', text: 'Kupfer mit Schleifvlies blank machen, mit Isopropanol entfetten, danach nicht mehr mit den Fingern berühren.' },
    film
      ? { titel: 'Film auflaminieren', text: 'Bei gedämpftem Licht ohne Blauanteil auflaminieren, Herstellerangaben beachten.' }
      : { titel: 'Lackieren', text: 'Mehrere dünne Schichten matt schwarz, im Freien oder unter Absaugung.' },
    film
      ? { titel: 'Ruhen lassen', text: 'Lichtgeschützt auskühlen lassen.' }
      : { titel: 'Trocknen', text: 'So lange, wie die Dose sagt, eher länger. Weicher Lack schmiert unter dem Strahl.' },
    { titel: 'Materialtest', text: 'Auf einem Probestück mit demselben Lack, derselben Schicht. Leistung und Geschwindigkeit in Schritt 5 eintragen.', laser: true },
    { titel: 'Lasern', text: 'Flach auflegen und fixieren, neu scannen, Höhe abtasten, Go-Abfrage bestätigen.', laser: true },
  ];
  out.push(film
    ? { titel: 'Entwickeln', text: 'In Sodalösung nach Herstellerangabe, bis die unbelichteten Bereiche ganz weg sind.' }
    : { titel: 'Prüfen', text: 'Mit der Lupe: Kupfer muss blank sein. Ruß vorsichtig abtupfen. Rückstände verhindern das Ätzen an dieser Stelle.' });
  out.push(
    { titel: 'Ätzen', text: 'Natriumpersulfat oder Eisen(III)-chlorid nach Herstellerangabe. Regelmäßig nachsehen, zu lange Ätzzeit frisst die Leiterbahnen von der Seite an.' },
    { titel: 'Reste entfernen', text: film ? 'Film nach Herstellerangabe strippen.' : 'Lack mit Aceton abwaschen.' },
    { titel: 'Bohren', text: 'An den Marken bohren, dann Passmarken als Löcher durchbohren, wenn eine zweite Seite folgt.' },
  );
  if (mask) out.push({ titel: 'Lötstopp', text: 'Lack auftragen, aushärten, Pads mit der Ebene „Platine Lötstopp“ freilegen. Vorher Probestück lasern, Platine auf die Passmarken setzen und neu scannen.', laser: true });
  if (silk) out.push({ titel: 'Beschriftung', text: 'Mit der Ebene „Platine Beschriftung“ markieren. Vorher Probestück, Lage prüfen und neu scannen.', laser: true });
  return out;
}
