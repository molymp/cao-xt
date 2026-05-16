"""
CAO-XT – Hibiscus XML-RPC-Client (Phase E.2, read-only Einstieg).

Spricht den ``jameica.webadmin``-XML-RPC-Endpoint an. Authentifizierung:
HTTP-Basic, wobei der **Benutzername ignoriert** wird und das Passwort
das **Jameica-Master-Passwort** ist (siehe hibiscus_setup-Doku). Quelle
des Passworts: ``DORFKERN_KONFIG['hibiscus.master_passwort']``
(TYP=SECRET); URL/User aus ``caoxt.ini [Hibiscus]``.

SSL: Jameica nutzt ein selbstsigniertes Zertifikat. Wir nutzen **kein**
``verify=False``, sondern pinnen den SHA-256-Fingerprint des Leaf-Certs
(Trust-On-First-Use: beim ersten Connect wird der Fingerprint in
``DORFKERN_KONFIG['hibiscus.cert_sha256']`` abgelegt und danach
erzwungen). Ein Cert-Wechsel (z.B. Angreifer / Neuinstallation) fällt
damit laut auf.

Scope dieses Moduls: read-only Verifikation (``konto_list``,
``umsatz_find``). SEPA-Schreibvorgänge (E.2-Write) kommen separat.
"""
from __future__ import annotations

import hashlib
import http.client
import ssl
import xmlrpc.client
from typing import Any
from urllib.parse import quote


class HibiscusError(RuntimeError):
    """Konfig fehlt, Cert-Pin-Mismatch, oder XML-RPC-Fehler."""


# ── SSL: Fingerprint-pinnender Transport ────────────────────────────

class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS-Connection, die nach dem Handshake den Leaf-Cert-SHA-256
    gegen einen erwarteten Wert prüft. Für selbstsignierte Localhost-
    Certs: Handshake ohne CA-Validierung, Integrität via Pin."""

    def __init__(self, host, *, erwartet_sha256: str | None, **kw):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        super().__init__(host, context=ctx, timeout=kw.pop('timeout', 30))
        self._erwartet = (erwartet_sha256 or '').lower() or None
        self.gesehener_sha256: str | None = None

    def connect(self):
        super().connect()
        der = self.sock.getpeercert(binary_form=True)
        self.gesehener_sha256 = hashlib.sha256(der).hexdigest()
        if self._erwartet and self.gesehener_sha256 != self._erwartet:
            self.close()
            raise HibiscusError(
                "Hibiscus-TLS-Zertifikat hat sich geändert "
                f"(erwartet {self._erwartet[:16]}…, "
                f"erhalten {self.gesehener_sha256[:16]}…). "
                "Falls bewusst (Jameica-Neuinstallation): "
                "DORFKERN_KONFIG['hibiscus.cert_sha256'] löschen.")


class _PinnedTransport(xmlrpc.client.Transport):
    """xmlrpc.client-Transport, der :class:`_PinnedHTTPSConnection`
    nutzt und den tatsächlich gesehenen Fingerprint zugänglich macht
    (für den TOFU-Speicher)."""

    def __init__(self, erwartet_sha256: str | None, timeout: int = 30):
        super().__init__()
        self._erwartet = erwartet_sha256
        self._timeout = timeout
        self.gesehener_sha256: str | None = None

    def make_connection(self, host):
        chost, self._extra_headers, _ = self.get_host_info(host)
        conn = _PinnedHTTPSConnection(
            chost, erwartet_sha256=self._erwartet, timeout=self._timeout)
        # Fingerprint nach dem ersten Call abgreifen
        self._conn = conn
        return conn

    def request(self, host, handler, request_body, verbose=False):
        try:
            return super().request(host, handler, request_body, verbose)
        finally:
            c = getattr(self, '_conn', None)
            if c is not None and c.gesehener_sha256:
                self.gesehener_sha256 = c.gesehener_sha256


# ── Client ──────────────────────────────────────────────────────────

class HibiscusClient:
    """Dünner Wrapper um den Hibiscus-XML-RPC-Endpoint.

    Methodenname = ``<manifest>.<service>.<methode>`` weil
    ``xmlrpc.useinterfacenames=false`` (Quelle: jameica.xmlrpc
    ``XmlRpcServiceDescriptorImpl.getID() = manifest.getName()+"."+
    service.getName()``). Für Hibiscus also Präfix
    ``hibiscus.xmlrpc.`` → ``hibiscus.xmlrpc.konto.list`` usw.
    Live gegen Jameica 2.12/hibiscus.xmlrpc-2.11-nightly verifiziert
    (2026-05-16). Alles am Root-``/xmlrpc``-Endpoint (NICHT je Service).
    """

    _PRAEFIX = 'hibiscus.xmlrpc.'

    def __init__(self, url: str, user: str, password: str,
                 cert_sha256: str | None = None, timeout: int = 30):
        if not url or not password:
            raise HibiscusError(
                "Hibiscus nicht konfiguriert (URL/Passwort fehlt). "
                "Installer Phase 4c ausführen bzw. Master-Passwort in "
                "der Admin-UI hinterlegen.")
        # Basic-Auth in die URL einbetten (user wird serverseitig
        # ignoriert, aber Basic-Auth braucht formal ein Paar).
        # safe='' → '/', '@', ':' im Userinfo werden percent-codiert,
        # sonst zerlegt urllib die URL falsch (Passwort mit Sonderzeichen).
        proto, _, rest = url.partition('://')
        auth_url = f"{proto}://{quote(user or 'dorfkern', safe='')}:" \
                   f"{quote(password, safe='')}@{rest}"
        self._transport = _PinnedTransport(cert_sha256, timeout)
        self._proxy = xmlrpc.client.ServerProxy(
            auth_url, transport=self._transport, allow_none=True)

    @property
    def gesehener_cert_sha256(self) -> str | None:
        """SHA-256 des zuletzt gesehenen TLS-Certs (für TOFU-Speicher)."""
        return self._transport.gesehener_sha256

    # ---- read-only -------------------------------------------------

    def _ruf_abs(self, voll_methode: str, *args):
        """Ruft eine voll-qualifizierte XML-RPC-Methode am Root-Endpoint
        (handler-id = ``<manifest>.<service>``, useinterfacenames=false)."""
        m = getattr(self._proxy, voll_methode)
        try:
            return m(*args)
        except (xmlrpc.client.Fault, OSError) as e:
            raise HibiscusError(
                f"{voll_methode} fehlgeschlagen: {e}") from e

    def _ruf(self, methode: str, *args):
        """Ruft ``hibiscus.xmlrpc.<methode>`` am Root-Endpoint."""
        return self._ruf_abs(self._PRAEFIX + methode, *args)

    def konto_list(self) -> list[dict[str, Any]]:
        return list(self._ruf('konto.list') or [])

    def umsatz_find(self, konto_id: int, von: str = '',
                    bis: str = '') -> list[dict[str, Any]]:
        """``hibiscus.xmlrpc.umsatz.find`` – Umsätze eines Kontos.
        Datumsformat wie von Hibiscus erwartet (``dd.mm.yyyy``);
        leer = keine Grenze."""
        return list(
            self._ruf('umsatz.find', int(konto_id), von or '', bis or '')
            or [])

    # ---- SEPA-Write (queue-only) -----------------------------------
    #
    # ``hibiscus.xmlrpc.sepaueberweisung.create`` LEGT die Überweisung
    # nur in Hibiscus an (Status "offen"). Das SIGNIEREN/AUSFÜHREN
    # (PIN/TAN bzw. S-pushTAN) bleibt bewusst beim Menschen in der
    # Jameica-GUI — headless kann Jameica nicht signieren (TANDialog
    # ist SWT-GUI-gebunden, siehe project_zahlungsmanagement_hibiscus).
    # Es gibt in hibiscus.xmlrpc KEINE execute/send/sign-Methode.
    #
    # Map-Variante (robust ggü. Positions-Signaturänderungen). SEPA:
    # ``kontonummer`` = Empfänger-IBAN, ``blz`` = Empfänger-BIC.

    def sepa_ueberweisung_anlegen(self, *, debit_konto_id: int,
                                  iban: str, bic: str, name: str,
                                  betrag: float, zweck: str,
                                  termin: str = '',
                                  endtoendid: str = '') -> str:
        """Legt eine SEPA-Überweisung in Hibiscus an (Status „offen",
        NICHT ausgeführt). Gibt die Hibiscus-ID des Auftrags zurück.

        :param debit_konto_id: Hibiscus-Konto-ID des Belastungskontos.
        :param iban:  Empfänger-IBAN.
        :param bic:   Empfänger-BIC.
        :param name:  Empfängername.
        :param betrag: Betrag (EUR, > 0).
        :param zweck: Verwendungszweck.
        :param termin: Ausführungstermin ``dd.mm.yyyy`` (leer = sofort).
        :param endtoendid: optionale SEPA End-to-End-ID.
        """
        params: dict[str, Any] = {
            'konto':            int(debit_konto_id),
            'kontonummer':      str(iban).replace(' ', '').upper(),
            'blz':              str(bic).strip().upper(),
            'name':             str(name)[:70],
            'betrag':           round(float(betrag), 2),
            'verwendungszweck': str(zweck)[:140],
        }
        if termin:
            params['termin'] = termin
        if endtoendid:
            params['endtoendid'] = str(endtoendid)[:35]
        res = self._ruf('sepaueberweisung.create', params)
        return str(res)

    def sepa_ueberweisung_loeschen(self, auftrag_id: str) -> bool:
        """Löscht einen NOCH NICHT gesendeten SEPA-Auftrag in Hibiscus
        (``sepaueberweisung.delete``). Reines Queue-Delete — braucht
        **kein** Signieren. Gibt ``True`` zurück, wenn Hibiscus den
        Aufruf ohne Fehler quittiert.
        """
        self._ruf('sepaueberweisung.delete', str(auftrag_id))
        return True

    # Status der automatischen Synchronisierung. Hibiscus-CORE-Service
    # → handler-id 'hibiscus.synchronizescheduler' (NICHT hibiscus.xmlrpc).
    _SYNC_STATUS = {
        0: 'noch nie', 1: 'läuft', 2: 'OK', 3: 'Fehler', 4: 'abgebrochen',
    }

    def sync_status(self) -> dict[str, Any]:
        """Liest den read-only Status des Auto-Sync-Schedulers:
        ``letzter``/``naechster`` Lauf (ISO-String oder None) +
        ``status``/``status_text``. Wirft ``HibiscusError`` wenn der
        Service nicht erreichbar/freigegeben ist."""
        praefix = 'hibiscus.synchronizescheduler.'

        def _dt(v):
            # xmlrpc.client liefert DateTime; robust nach ISO wandeln.
            if v in (None, '', 0):
                return None
            try:
                return str(v)
            except Exception:
                return None

        letzter = _dt(self._ruf_abs(praefix + 'getLastExecution'))
        naechster = _dt(self._ruf_abs(praefix + 'getNextExecution'))
        st = self._ruf_abs(praefix + 'getStatus')
        try:
            st = int(st)
        except (TypeError, ValueError):
            st = -1
        return {
            'letzter':     letzter,
            'naechster':   naechster,
            'status':      st,
            'status_text': self._SYNC_STATUS.get(st, f'Code {st}'),
        }


# ── Factory: aus Dorfkern-Konfiguration ─────────────────────────────

def _ini_hibiscus() -> dict[str, str]:
    import configparser
    import os
    ini = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'caoxt', 'caoxt.ini')
    cfg = configparser.ConfigParser()
    if os.path.isfile(ini):
        cfg.read(ini, encoding='utf-8')
    if cfg.has_section('Hibiscus'):
        return dict(cfg.items('Hibiscus'))
    return {}


_LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1', '[::1]', '0.0.0.0'}


def _ist_loopback(url: str) -> bool:
    """True, wenn die XML-RPC-URL auf den lokalen Rechner zeigt."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or '').lower()
        return host in _LOOPBACK_HOSTS
    except Exception:
        return False


def aus_konfig(timeout: int = 30) -> HibiscusClient:
    """Baut einen :class:`HibiscusClient` aus caoxt.ini + DORFKERN_KONFIG.

    Cert-Pin-Logik:
    - **Remote-Host**: striktes TOFU — erster Fingerprint wird
      festgeschrieben, danach hart erzwungen (MITM-Schutz).
    - **Loopback** (127.0.0.1/localhost): KEIN harter Pin. Jameica
      erzeugt sein selbstsigniertes Cert bei Keystore-Neuanlage neu;
      ein Loopback-MITM setzt lokalen Root voraus (dann ist ohnehin
      alles kompromittiert) → der harte Pin brächte nur wiederkehrende
      Störung. Wir zeichnen den Fingerprint weiter auf (Audit) und
      re-pinnen automatisch bei Änderung, mit Warn-Log.
    """
    import logging
    from common import konfig

    ini = _ini_hibiscus()
    if ini.get('aktiv', '1') in ('0', 'false', 'False'):
        raise HibiscusError("Hibiscus ist in caoxt.ini deaktiviert.")
    url  = ini.get('xmlrpc_url') or 'https://127.0.0.1:8080/xmlrpc'
    user = ini.get('xmlrpc_user') or 'dorfkern'
    pw   = konfig.get('hibiscus.master_passwort') or ''
    pin  = konfig.get('hibiscus.cert_sha256') or None
    loopback = _ist_loopback(url)

    # Bei Loopback den Pin NICHT scharf schalten (Transport wirft sonst
    # bei jeder Keystore-Neuanlage). Remote: Pin erzwingen.
    erzwinge = None if loopback else pin
    client = HibiscusClient(url, user, pw, cert_sha256=erzwinge,
                            timeout=timeout)

    if loopback:
        # Aufzeichnen + auto-re-pin (Audit), kein Hard-Fail.
        client.konto_list()
        fp = client.gesehener_cert_sha256
        if fp and fp != pin:
            if pin:
                logging.getLogger(__name__).warning(
                    "Hibiscus-Loopback-Cert geändert (%s… → %s…) — "
                    "auto-re-pin (Keystore-Neuanlage, erwartet bei "
                    "localhost).", (pin or '')[:16], fp[:16])
            konfig.set('hibiscus.cert_sha256', fp, typ='STRING',
                       kategorie='HIBISCUS',
                       beschreibung='Loopback-Cert-SHA-256 (Audit; '
                                    'auto-re-pin bei Keystore-Neuanlage).')
    elif pin is None:
        # Remote, noch kein Pin: striktes TOFU festschreiben.
        client.konto_list()
        fp = client.gesehener_cert_sha256
        if fp:
            konfig.set('hibiscus.cert_sha256', fp, typ='STRING',
                       kategorie='HIBISCUS',
                       beschreibung='TOFU-gepinnter SHA-256 des Jameica-'
                                    'TLS-Zertifikats (Remote, strikt).')
    return client
