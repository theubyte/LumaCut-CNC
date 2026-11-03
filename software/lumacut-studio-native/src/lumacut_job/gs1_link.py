"""GS1 Digital Link URIs (GS1 Digital Link URI Syntax 1.x) – the content of a "GS1 QR" for
products that a phone camera opens as a web page and a GS1 scanner reads as GTIN, lot, expiry ….

:func:`build` turns an element string "(01)09501101530003(10)AB-12(17)261231" into
``https://id.gs1.org/01/09501101530003/10/AB-12?17=261231``: exactly one primary key (GTIN,
SSCC, GLN, …) in the path, its key qualifiers in the prescribed order behind it (for a GTIN:
consumer product variant 22, lot 10, serial 21), every other AI as a query parameter (data
attribute). Values are percent-encoded where the GS1 character set contains URI delimiters.

:func:`parse` reads such a URI back (any domain, an optional path prefix before the primary key,
non-numeric query parameters such as ``linkType`` are kept out of the element list) and checks
the values with the rules of :mod:`lumacut_job.gs1` (fixed lengths, digits, check digits).

Pure Python, no Qt. Errors are German ``ValueError`` messages for the dialog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

from . import gs1

DEFAULT_DOMAIN = "https://id.gs1.org"
EXAMPLE = "(01)09501101530003(10)AB-12(17)261231"

# Primary key → allowed key qualifiers in path order (GS1 Digital Link 1.x, table 4).
# A tuple inside the list means "one of" (e.g. GTIN: serial 21 or TPX 235).
PRIMARY_KEYS: dict[str, tuple] = {
    "01": ("22", "10", ("21", "235")),
    "8006": ("22", "10", "21"),
    "8013": (),
    "8010": ("8011",),
    "414": (("254", "7040"),),
    "415": ("8020",),
    "417": ("7040",),
    "00": (),
    "253": (),
    "255": (),
    "401": (),
    "402": (),
    "8003": (),
    "8004": (),
    "8017": ("8019",),
    "8018": ("8019",),
}
KEY_LABELS = {"01": "GTIN", "8006": "ITIP", "8013": "GMN", "8010": "CPID", "414": "GLN",
              "415": "GLN Rechnungssteller", "417": "Party-GLN", "00": "SSCC", "253": "GDTI",
              "255": "GCN", "401": "GINC", "402": "GSIN", "8003": "GRAI", "8004": "GIAI",
              "8017": "GSRN Anbieter", "8018": "GSRN Empfänger"}
# RFC 3986 unreserved characters stay literal in path and query values.
_SAFE = "-._~"
_DOMAIN = re.compile(r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?$")
MAX_URI = 2000


@dataclass(frozen=True)
class Link:
    domain: str                     # scheme + host (+ path prefix), no trailing slash
    elements: tuple[gs1.Element, ...]
    extra: tuple[tuple[str, str], ...] = ()   # non-AI query parameters, kept verbatim

    @property
    def key(self) -> gs1.Element:
        return self.elements[0]

    def element_string(self) -> str:
        return gs1.hri(list(self.elements))


def _qualifier_slots(key: str) -> list[tuple[str, ...]]:
    return [q if isinstance(q, tuple) else (q,) for q in PRIMARY_KEYS[key]]


def normalize_domain(domain: str) -> str:
    """``https://host[/prefix]`` without trailing slash; ``ValueError`` if not usable."""
    d = "".join(str(domain or "").split()) or DEFAULT_DOMAIN
    if "://" not in d:
        d = "https://" + d
    scheme, _, rest = d.partition("://")
    d = scheme.lower() + "://" + rest.rstrip("/")
    if "?" in d or "#" in d or not _DOMAIN.match(d):
        raise ValueError(f"Domain „{d}“ ungültig – z. B. {DEFAULT_DOMAIN} oder "
                         "https://marke.example")
    scheme, rest = d.split("://", 1)
    host = rest.split("/", 1)[0].split(":", 1)[0]
    if "." not in host or host.startswith(".") or host.endswith(".") or ".." in host:
        raise ValueError(f"Domain „{d}“ ungültig – Hostname mit Punkt erwartet, z. B. id.gs1.org")
    return scheme.lower() + "://" + rest[:len(host)].lower() + rest[len(host):]


def _split(elements: list[gs1.Element]):
    """(key, qualifiers in path order, attributes) of an element list; ``ValueError``."""
    keys = [e for e in elements if e.ai in PRIMARY_KEYS]
    if not keys:
        raise ValueError("GS1 Digital Link braucht einen Primärschlüssel, z. B. (01) GTIN, "
                         "(00) SSCC oder (414) GLN")
    if len(keys) > 1:
        raise ValueError("Nur ein Primärschlüssel erlaubt, gefunden: "
                         + ", ".join(f"({e.ai})" for e in keys))
    key = keys[0]
    seen: set[str] = set()
    for e in elements:
        if e.ai in seen:
            raise ValueError(f"({e.ai}) kommt doppelt vor")
        seen.add(e.ai)
    slots = _qualifier_slots(key.ai)
    by_ai = {e.ai: e for e in elements}
    quals = []
    for slot in slots:
        found = [by_ai[a] for a in slot if a in by_ai]
        if len(found) > 1:
            raise ValueError(f"({found[0].ai}) und ({found[1].ai}) schließen sich aus")
        quals += found
    in_path = {key.ai} | {q.ai for q in quals}
    attrs = [e for e in elements if e.ai not in in_path]
    for e in attrs:
        if e.ai in PRIMARY_KEYS:          # pragma: no cover - excluded above
            raise ValueError(f"({e.ai}) ist ein Primärschlüssel")
    return key, quals, attrs


def build(text: str, domain: str = DEFAULT_DOMAIN) -> str:
    """GS1 Digital Link URI for the element string ``text``; ``ValueError`` (German)."""
    elements = gs1.parse(text)
    key, quals, attrs = _split(elements)
    d = normalize_domain(domain)
    path = "".join(f"/{e.ai}/{quote(e.data, safe=_SAFE)}" for e in [key] + quals)
    query = "&".join(f"{e.ai}={quote(e.data, safe=_SAFE)}" for e in attrs)
    uri = d + path + ("?" + query if query else "")
    if len(uri) > MAX_URI:
        raise ValueError(f"Adresse zu lang ({len(uri)} Zeichen)")
    return uri


def looks_like_uri(text: str) -> bool:
    t = str(text or "").strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def parse(uri: str) -> Link:
    """Elements of a GS1 Digital Link URI (key first, then path qualifiers, then attributes)."""
    u = str(uri or "").strip()
    if not looks_like_uri(u):
        raise ValueError("GS1 Digital Link beginnt mit https:// oder http://")
    if any(c.isspace() for c in u):
        raise ValueError("Leerzeichen in der Adresse – Sonderzeichen als %20 usw. schreiben")
    if len(u) > MAX_URI:
        raise ValueError(f"Adresse zu lang ({len(u)} Zeichen)")
    u = u.split("#", 1)[0]
    base, _, query = u.partition("?")
    scheme, rest = base.split("://", 1)
    host, _, path = rest.partition("/")
    segs = path.split("/") if path else []
    if segs and segs[-1] == "":
        segs = segs[:-1]
    start = None
    for i, seg in enumerate(segs):
        if seg in PRIMARY_KEYS and (len(segs) - i) % 2 == 0:
            start = i
            break
    if start is None:
        raise ValueError("Kein GS1-Primärschlüssel im Pfad gefunden, z. B. …/01/09501101530003")
    domain = normalize_domain(scheme + "://" + "/".join([host] + segs[:start]))
    pairs = [(segs[i], unquote(segs[i + 1])) for i in range(start, len(segs), 2)]
    key_ai = pairs[0][0]
    slots = _qualifier_slots(key_ai)
    pos = 0
    for ai, _ in pairs[1:]:
        while pos < len(slots) and ai not in slots[pos]:
            pos += 1
        if pos >= len(slots):
            raise ValueError(f"({ai}) ist hinter ({key_ai}) im Pfad nicht erlaubt oder steht in "
                             "der falschen Reihenfolge")
        pos += 1
    attrs: list[tuple[str, str]] = []
    extra: list[tuple[str, str]] = []
    for part in filter(None, query.split("&")):
        name, _, value = part.partition("=")
        if name.isascii() and name.isdigit() and 2 <= len(name) <= 4:
            if name in PRIMARY_KEYS:
                raise ValueError(f"Primärschlüssel ({name}) gehört in den Pfad, nicht in die Abfrage")
            attrs.append((name, unquote(value)))
        else:
            extra.append((name, value))
    text = "".join(f"({ai}){val}" for ai, val in pairs + attrs)
    elements = gs1.parse(text)
    _split(elements)
    return Link(domain, tuple(elements), tuple(extra))


def resolve(text: str, domain: str = DEFAULT_DOMAIN) -> tuple[str, Link]:
    """Content of a Digital Link QR code: (URI, parsed link).

    ``text`` is either an element string (built with ``domain``) or a complete Digital Link URI
    (encoded as typed, after validation).
    """
    t = str(text or "").strip()
    if not t:
        raise ValueError("Keine GS1-Daten – Elementstring wie " + EXAMPLE + " oder eine "
                         "Digital-Link-Adresse")
    if looks_like_uri(t):
        return t, parse(t)
    uri = build(t, domain)
    return uri, parse(uri)


def describe(link: Link) -> str:
    """Short German summary, e.g. „GTIN 09501101530003, (10) AB-12, (17) 261231“."""
    key = link.key
    parts = [f"{KEY_LABELS.get(key.ai, key.ai)} {key.data}"]
    parts += [f"({e.ai}) {e.data}" for e in link.elements[1:]]
    return ", ".join(parts)


__all__ = ["DEFAULT_DOMAIN", "EXAMPLE", "KEY_LABELS", "Link", "PRIMARY_KEYS", "build", "describe",
           "looks_like_uri", "normalize_domain", "parse", "resolve"]
