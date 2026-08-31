#!/bin/bash
# tomtom-recon.sh — identifiziert ein per USB angeschlossenes TomTom-Navi (macOS).
#
# NUR LESEND: schreibt nichts auf das Geraet, aendert nichts, flasht nichts.
#
# Hintergrund: Geraete der NAV4-Generation (u.a. START 42/52/62, START 40/50/60,
# GO 40..6100, VIA 52/62) melden sich NICHT als USB-Massenspeicher, sondern als
# USB-Netzwerkadapter (RNDIS bzw. CDC-ECM). Sie sprechen ueber einen kleinen
# HTTP-Server, mit dem sonst MyDrive Connect redet. Nur die ALTE Generation
# (GO/ONE/XL bis ca. 2010) mountet ein Volume mit Dateien wie 'ttsystem'.
# Das Skript prueft daher beide Faelle und sagt am Ende, welche Generation vorliegt.
#
# Aufruf:  bash tomtom-recon.sh

set -u

OUT="$HOME/Desktop/tomtom-recon.txt"
: > "$OUT"

say() { printf '%s\n' "$*" | tee -a "$OUT"; }
sec() { printf '\n\n===== %s =====\n' "$*" | tee -a "$OUT"; }
run() { printf '\n$ %s\n' "$*" >> "$OUT"; eval "$*" >> "$OUT" 2>&1 < /dev/null; }
fsize() { wc -c < "$1" 2>/dev/null | tr -d ' ' || echo 0; }
hexhead() { if command -v xxd >/dev/null; then xxd -l "$2" "$1"; else od -A x -t x1z -N "$2" "$1"; fi; }

say "TomTom Recon — $(date)"
say "macOS $(sw_vers -productVersion 2>/dev/null) / $(uname -m)"
say "Bericht: $OUT"
say ""
say "Bitte das Geraet JETZT eingeschaltet per USB angeschlossen lassen."

FOUND_USB=0; FOUND_NET=0; FOUND_VOL=0; FOUND_HTTP=0

# ============================================================ 1. USB
sec "1. USB — TomTom-Geraet suchen (Vendor-ID 0x1390)"
if system_profiler SPUSBDataType 2>/dev/null | grep -qiE 'tomtom|0x1390'; then
  FOUND_USB=1
  say "OK: TomTom am USB erkannt."
  run "system_profiler SPUSBDataType 2>/dev/null | grep -iE -B 4 -A 14 'tomtom|0x1390'"
else
  say "!! Kein TomTom am USB gefunden."
  say "   Pruefen: Geraet eingeschaltet? Datenkabel (kein reines Ladekabel)?"
  say "   Anderen USB-Port / anderes Kabel probieren."
fi

sec "2. Vollstaendige USB-Liste (zur Kontrolle)"
run "system_profiler SPUSBDataType 2>/dev/null"

sec "3. USB-Deskriptoren roh (Vendor/Product/Serial)"
run "ioreg -p IOUSB -w0 -l 2>/dev/null | grep -E 'USB (Vendor|Product) Name|idVendor|idProduct|USB Serial Number|bcdDevice'"

# ============================================================ 4. Netzwerk (NAV4)
sec "4. Netzwerk-Schnittstellen — NAV4 meldet sich als Netzwerkadapter"
run "networksetup -listallhardwareports 2>/dev/null"
run "ifconfig -a 2>/dev/null | grep -E '^[a-z0-9]+:|inet '"

# Link-local 169.254.x auf einer nicht-WLAN-Schnittstelle = starker NAV4-Hinweis
LLIF=$(ifconfig 2>/dev/null | awk '/^[a-z]/{ifn=$1} /inet 169\.254\./{print ifn}' | tr -d ':' | grep -v '^en0$' | head -1)
if [ -n "${LLIF:-}" ]; then
  FOUND_NET=1
  say "OK: Link-local-Adresse auf Schnittstelle '$LLIF' — passt zu NAV4 (USB-Ethernet)."
  run "ifconfig '$LLIF'"
else
  say "(keine 169.254.x-Adresse auf einer USB-Netzwerkschnittstelle gefunden)"
fi

sec "5. NAV4-Geraeteserver ansprechen (169.254.255.1)"
say "Teste HTTP-Endpunkte des Geraets (nur lesende GETs, Timeout 5s)..."
for ep in / /mpnd/status /mpnd/settings /sa/hello; do
  code=$(curl -s --noproxy '*' -o /tmp/tt_ep.$$ -w '%{http_code}' --max-time 5 "http://169.254.255.1${ep}" 2>/dev/null)
  sz=$( [ -f /tmp/tt_ep.$$ ] && fsize /tmp/tt_ep.$$ || echo 0 )
  say "  GET ${ep}  ->  HTTP ${code:-000}  (${sz} Bytes)"
  {
    printf '\n--- GET http://169.254.255.1%s -> %s ---\n' "$ep" "${code:-000}"
    [ -f /tmp/tt_ep.$$ ] && head -c 4000 /tmp/tt_ep.$$
  } >> "$OUT" 2>&1
  case "${code:-000}" in 2*) FOUND_HTTP=1 ;; esac
  rm -f /tmp/tt_ep.$$
done
if [ "$FOUND_HTTP" = 1 ] && { [ "$FOUND_USB" = 1 ] || [ "$FOUND_NET" = 1 ]; }; then
  say "OK: Geraet antwortet per HTTP — NAV4 bestaetigt."
elif [ "$FOUND_HTTP" = 1 ]; then
  say "ACHTUNG: HTTP-Antwort OHNE erkanntes USB-/Netzwerkgeraet."
  say "  -> Das kommt vermutlich NICHT vom Navi (Proxy/VPN/anderes Geraet im Netz)."
  FOUND_HTTP=0
else
  say "(keine HTTP-Antwort; ggf. laeuft MyDrive Connect nicht / anderes Subnetz)"
fi

# ============================================================ 6. Massenspeicher (alte Generation)
sec "6. Massenspeicher — nur die ALTE Generation mountet ein Volume"
run "diskutil list"
run "ls -1 /Volumes"

TTVOL=""
for v in /Volumes/*; do
  [ -d "$v" ] || continue
  if ls "$v" 2>/dev/null | grep -qiE '^(ttsystem|ttgo\.bif|loopback\.txt|currentmap\.dat)'; then TTVOL="$v"; break; fi
done
if [ -z "$TTVOL" ]; then
  for v in /Volumes/*; do
    [ -d "$v" ] || continue
    case "$(basename "$v" | tr '[:lower:]' '[:upper:]')" in *TOMTOM*|*INTERNAL*) TTVOL="$v"; break ;; esac
  done
fi

if [ -z "$TTVOL" ]; then
  say "Kein TomTom-Volume gemountet."
  say "-> Das ist bei einem START 62 das ERWARTETE Verhalten (NAV4)."
else
  FOUND_VOL=1
  say "Volume gefunden: $TTVOL  (deutet auf die ALTE Generation hin!)"
  run "df -h '$TTVOL'"
  run "ls -la '$TTVOL'"
  run "find '$TTVOL' -maxdepth 2 -type d 2>/dev/null | head -60"
  {
    printf '\n$ groesste Dateien\n'
    find "$TTVOL" -type f -not -name '._*' -print0 2>/dev/null \
      | while IFS= read -r -d '' f; do printf '%12s  %s\n' "$(fsize "$f")" "$f"; done \
      | sort -rn | head -30
  } >> "$OUT" 2>&1 < /dev/null
  for f in ttsystem ttgo.bif LOOPBACK.TXT currentmap.dat; do
    [ -e "$TTVOL/$f" ] && { run "ls -l '$TTVOL/$f'"; run "file '$TTVOL/$f'"; }
  done
  # ttgo.bif enthaelt bei der alten Generation Seriennummer + NavCore-Version
  [ -f "$TTVOL/ttgo.bif" ] && run "cat '$TTVOL/ttgo.bif'"
  [ -f "$TTVOL/ttsystem" ] && { run "hexhead '$TTVOL/ttsystem' 256"; run "strings -n 6 '$TTVOL/ttsystem' | head -40"; }
fi

# ============================================================ 7. Fazit
sec "7. AUSWERTUNG"
say ""
if [ "$FOUND_USB" = 0 ] && [ "$FOUND_NET" = 0 ] && [ "$FOUND_VOL" = 0 ]; then
  say "ERGEBNIS: Geraet nicht erkannt. Ohne USB-Kontakt geht nichts weiter."
  say "  -> Anderes Kabel (Datenkabel!), anderer Port, Geraet einschalten."
  say "  -> Notfalls Reset: Ein-/Aus-Taste ~20 s halten, bis ein Trommelwirbel kommt."
elif [ "$FOUND_VOL" = 1 ]; then
  say "ERGEBNIS: Es wurde ein Massenspeicher-Volume gefunden."
  say "  -> Das spricht fuer die ALTE TomTom-Generation (vor NAV4), NICHT fuer ein"
  say "     typisches START 62. Bitte Modellnummer auf dem Typenschild pruefen."
  say "  -> Fuer diese alte Generation existieren echte Custom-Linux-Projekte"
  say "     (OpenTom, NavitTom) — die Lage waere dann deutlich besser."
elif [ "$FOUND_USB" = 1 ] || [ "$FOUND_NET" = 1 ]; then
  say "ERGEBNIS: NAV4-Verhalten (Netzwerkadapter statt Massenspeicher)."
  say "  -> Passt zum START 62 (interne Modellnummer 4AA63)."
  say "  -> Kein Dateizugriff per USB. Eigener Code erfordert Root ueber den"
  say "     Recovery-/SD-Karten-Weg der Community — siehe README.md."
else
  say "ERGEBNIS: unklar — bitte den vollstaendigen Bericht zur Auswertung schicken."
fi
say ""
say "Bitte $OUT hierher kopieren oder hochladen."
say "Zusaetzlich hilfreich: die Modellnummer vom Typenschild auf der Geraeterueckseite"
say "(Format 4AAxx / 4ENxx / 4FCxx) sowie die Softwareversion aus dem Geraetemenue."
