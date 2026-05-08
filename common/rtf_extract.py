"""
Minimaler RTF→Plain-Text-Konverter.

CAO-Faktura speichert manche Memo-Felder (z.B. EKBESTELL.INFO, KOPFTEXT,
FUSSTEXT) als RTF. In der XT-UI brauchen wir den lesbaren Text — Stil-
information werfen wir weg. Diese Implementierung deckt die in der
CAO-Praxis vorkommenden Konstrukte ab (Standard-RTF 1.0 mit Unicode-
Escapes), keine Tabellen, keine Bilder, kein Stylesheet-Lookup.

Nicht vollstaendig RFC-konform — wenn ein Feld komplexer ist, lieber
striprtf als Library nehmen statt diesen Parser auszubauen.
"""
from __future__ import annotations

import re


# Gruppen, deren Inhalt komplett verworfen wird (Header-Tabellen).
_DROP_GROUPS = (
    'fonttbl', 'colortbl', 'stylesheet', 'info', 'pict',
    'header', 'footer', 'rxe', 'tc', 'object',
    # \*\…  Erweiterungsgruppen (Generator, Background, Themedata, …)
    'generator', 'background', 'themedata', 'datastore',
    'shp', 'shpinst', 'shppict', 'nonshppict', 'falt',
    'mmathPr', 'wgrffmtfilter', 'listtable', 'listoverridetable',
    'rsidtbl', 'latentstyles', 'wpsCustomData',
)

# Control-Words, die in Plain-Text-Aequivalente uebersetzt werden.
_KONVERTIERE = {
    'par':       '\n',
    'line':      '\n',
    'tab':       '\t',
    'emdash':    '—',
    'endash':    '–',
    'bullet':    '•',
    'lquote':    '‘',
    'rquote':    '’',
    'ldblquote': '“',
    'rdblquote': '”',
}


def rtf_to_text(rtf: str | None) -> str:
    """Wandelt einen RTF-String in lesbaren Plain-Text.

    Args:
        rtf: RTF-Quelle als String. ``None`` oder leer → ``""``.

    Returns:
        Plain-Text mit ``\\n`` als Absatz-Trenner. Whitespace wird am
        Anfang/Ende getrimmt; mehrere Leerzeilen am Stueck werden auf
        eine reduziert.
    """
    if not rtf:
        return ''
    # Falls der String gar kein RTF ist, gib ihn unveraendert zurueck.
    if not rtf.lstrip().startswith('{\\rtf'):
        return rtf

    out: list[str] = []
    i = 0
    n = len(rtf)
    # Wenn group_depth >= 1 von einer "drop"-Gruppe → Inhalt skippen,
    # bis die zugehoerige schliessende Klammer kommt.
    drop_until_depth = -1
    depth = 0
    # Unicode-Skip-Counter aus \uc<n> (Default 1).
    uc_skip_default = 1
    uc_stack: list[int] = [uc_skip_default]

    while i < n:
        ch = rtf[i]

        if ch == '{':
            depth += 1
            uc_stack.append(uc_stack[-1])
            i += 1
            continue
        if ch == '}':
            if drop_until_depth == depth:
                drop_until_depth = -1
            depth -= 1
            if uc_stack:
                uc_stack.pop()
            i += 1
            continue

        if ch == '\\':
            i += 1
            if i >= n:
                break
            c = rtf[i]
            # Escape-Sonderzeichen
            if c in ('\\', '{', '}'):
                if drop_until_depth < 0:
                    out.append(c)
                i += 1
                continue
            # Hex-Byte:  \'XX
            if c == "'":
                hexstr = rtf[i + 1:i + 3]
                i += 3
                if drop_until_depth < 0:
                    try:
                        b = int(hexstr, 16)
                        # CP1252 ist die Standard-ANSI-Codepage in CAO-RTF.
                        out.append(bytes([b]).decode('cp1252', errors='replace'))
                    except ValueError:
                        pass
                continue
            # Unicode:  \uXXXX  (gefolgt von uc_skip Fallback-Bytes/Worten)
            if c == 'u' and i + 1 < n and (rtf[i + 1] == '-' or rtf[i + 1].isdigit()):
                m = re.match(r'-?\d+', rtf[i + 1:])
                if m:
                    code = int(m.group())
                    if code < 0:
                        code += 0x10000  # Negative → 16-bit unsigned.
                    i += 1 + len(m.group())
                    # Optionaler Delimiter-Space — gehoert per RTF-Spec
                    # zum Control-Word, NICHT zum Skip-Count. Ohne dieses
                    # Konsumieren wuerde nach \u228 das Trenner-Space als
                    # einziges Skip-Zeichen verbraucht und das eigentliche
                    # Fallback-Zeichen (z.B. 'ä') doppelt im Output landen.
                    if i < n and rtf[i] == ' ':
                        i += 1
                    if drop_until_depth < 0:
                        try:
                            out.append(chr(code))
                        except ValueError:
                            pass
                    # Fallback-Chars ueberspringen (uc_skip).
                    skip = uc_stack[-1] if uc_stack else 1
                    while skip > 0 and i < n:
                        if rtf[i] == '\\':
                            i += 1
                            if i >= n:
                                break
                            if rtf[i] == "'":
                                # \'XX = 1 Hex-Byte (3 Zeichen total)
                                i += 3
                            elif rtf[i].isalpha():
                                # Control-Word \name[Zahl][\s?]
                                m2 = re.match(r'[A-Za-z]+(?:-?\d+)?\s?', rtf[i:])
                                if m2:
                                    i += len(m2.group())
                            else:
                                # Control-Symbol \\, \{, \}
                                i += 1
                        elif rtf[i] in ('{', '}'):
                            break
                        else:
                            i += 1
                        skip -= 1
                    continue
            # Wenn folgendes Zeichen kein Buchstabe → Control-Symbol.
            if not c.isalpha():
                # \-, \_, \~, \: usw. — meistens visuell unwichtig.
                i += 1
                continue
            # Control-Word einlesen
            m = re.match(r'([A-Za-z]+)(-?\d+)?\s?', rtf[i:])
            if not m:
                i += 1
                continue
            word = m.group(1)
            param = m.group(2)
            i += len(m.group())

            # Sollen wir die naechste Gruppe komplett verwerfen?
            if word == '*':
                # \*\<x> → naechstes Control-Word ist Erweiterung;
                # wenn es zu einer Drop-Gruppe gehoert, droppen.
                # Wir nehmen einfach an, dass alles hinter \* zur
                # aktuellen Gruppe gehoert — und verwerfen sie.
                if drop_until_depth < 0:
                    drop_until_depth = depth
                continue
            if word in _DROP_GROUPS:
                if drop_until_depth < 0:
                    drop_until_depth = depth
                continue
            if word == 'uc':
                if param is not None:
                    try:
                        uc_stack[-1] = int(param)
                    except (ValueError, IndexError):
                        pass
                continue
            if drop_until_depth < 0 and word in _KONVERTIERE:
                out.append(_KONVERTIERE[word])
            # Andere Control-Words sind reine Stil-Anweisungen → ignorieren.
            continue

        # Normales Zeichen (incl. Zeilenumbruch im Source) — uebernehmen
        # wenn nicht in Drop-Gruppe. Wir filtern \r und \n im Source raus,
        # weil RTF nur \par als Absatztrenner kennt.
        if drop_until_depth < 0 and ch not in '\r\n':
            out.append(ch)
        i += 1

    text = ''.join(out)
    # Mehrfache Leerzeilen reduzieren, Rand-Whitespace entfernen.
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
