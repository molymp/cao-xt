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

    def _ruf(self, methode: str, *args):
        """Ruft ``hibiscus.xmlrpc.<methode>`` am Root-Endpoint."""
        m = getattr(self._proxy, self._PRAEFIX + methode)
        try:
            return m(*args)
        except (xmlrpc.client.Fault, OSError) as e:
            raise HibiscusError(
                f"{self._PRAEFIX}{methode} fehlgeschlagen: {e}") from e

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


def aus_konfig(timeout: int = 30) -> HibiscusClient:
    """Baut einen :class:`HibiscusClient` aus caoxt.ini + DORFKERN_KONFIG.

    Pin-Logik (TOFU): ist ``hibiscus.cert_sha256`` noch nicht gesetzt,
    wird der beim ersten erfolgreichen Call gesehene Fingerprint
    persistiert. Danach wird er erzwungen.
    """
    from common import konfig

    ini = _ini_hibiscus()
    if ini.get('aktiv', '1') in ('0', 'false', 'False'):
        raise HibiscusError("Hibiscus ist in caoxt.ini deaktiviert.")
    url  = ini.get('xmlrpc_url') or 'https://127.0.0.1:8080/xmlrpc'
    user = ini.get('xmlrpc_user') or 'dorfkern'
    pw   = konfig.get('hibiscus.master_passwort') or ''
    pin  = konfig.get('hibiscus.cert_sha256') or None

    client = HibiscusClient(url, user, pw, cert_sha256=pin, timeout=timeout)

    if pin is None:
        # TOFU: ersten Call machen, Fingerprint festschreiben.
        client.konto_list()
        fp = client.gesehener_cert_sha256
        if fp:
            konfig.set('hibiscus.cert_sha256', fp, typ='STRING',
                       kategorie='HIBISCUS',
                       beschreibung='TOFU-gepinnter SHA-256 des Jameica-'
                                    'TLS-Zertifikats.')
    return client
