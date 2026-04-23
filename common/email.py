"""
CAO-XT – Email-Versand-Helper

Zentraler SMTP-Wrapper fuer das gesamte Projekt. Liest die Konfiguration ueber
``common.config.load_email_config()``.

Design-Entscheidungen:
  * Fehlt ``smtp_host`` oder ``from_addr``, ist Versand deaktiviert –
    ``email_senden`` gibt ``{'versendet': 0, 'modus': 'disabled'}`` zurueck,
    ohne Fehler zu werfen. Das blockiert Workflow-Aktionen (z.B. Schichtplan-
    Freigabe) nicht, wenn Mail noch nicht konfiguriert ist.
  * Der Helper ist bewusst "dumm": er kennt keinen Dev-Modus und leitet nichts
    um. Umleitung/Subject-Prefix (z.B. fuer Dev-Test "Empfaenger = Sender")
    entscheidet der Aufrufer – siehe
    ``modules/orga/personal/models.py::schichtplan_freigabe_emails_senden``.
  * Versand ist best-effort: SMTP-Fehler werden geloggt, nicht geworfen –
    der Aufrufer entscheidet per Return-Dict, ob alles geklappt hat.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Iterable

from common.config import load_email_config

log = logging.getLogger(__name__)


def email_senden(empfaenger: str | Iterable[str],
                 betreff: str,
                 text: str,
                 html: str | None = None,
                 reply_to: str | None = None,
                 from_addr: str | None = None,
                 from_name: str | None = None) -> dict:
    """Versendet eine Email (Plain + optional HTML).

    Args:
        empfaenger: Ein String oder Liste von Email-Adressen.
        betreff:    Mail-Subject.
        text:       Plain-Text-Body (fallback / primary).
        html:       Optionaler HTML-Body; wenn gesetzt → multipart/alternative.
        reply_to:   Optionale Reply-To-Adresse.
        from_addr:  Optionaler Override fuer die Absender-Adresse
                    (sonst aus ``load_email_config()['from_addr']``).
        from_name:  Optionaler Override fuer den Anzeige-Namen.

    Returns:
        dict ``{'versendet': int, 'modus': str, 'empfaenger': list[str]}``.
        Modus: ``'disabled'`` | ``'ok'`` | ``'fehler'``.
    """
    cfg = load_email_config()
    to_list = [empfaenger] if isinstance(empfaenger, str) else list(empfaenger)
    to_list = [e.strip() for e in to_list if e and e.strip()]

    effektiv_from = (from_addr or cfg['from_addr'] or '').strip()
    effektiv_name = from_name if from_name is not None else cfg.get('from_name', '')

    if not cfg['smtp_host'] or not effektiv_from:
        log.info('Email-Versand deaktiviert (SMTP/Absender nicht konfiguriert).')
        return {'versendet': 0, 'modus': 'disabled', 'empfaenger': []}
    if not to_list:
        return {'versendet': 0, 'modus': 'disabled', 'empfaenger': []}

    msg = _build_message(cfg, to_list, betreff, text, html, reply_to,
                         effektiv_from, effektiv_name)

    try:
        _smtp_senden(cfg, to_list, msg, effektiv_from)
    except Exception as exc:
        log.exception('SMTP-Versand fehlgeschlagen: %s', exc)
        return {'versendet': 0, 'modus': 'fehler', 'empfaenger': to_list,
                'fehler': str(exc)}

    return {'versendet': len(to_list), 'modus': 'ok', 'empfaenger': to_list}


def _build_message(cfg: dict, to_list: list[str], betreff: str,
                   text: str, html: str | None,
                   reply_to: str | None,
                   from_addr: str, from_name: str):
    """Baut MIME-Message (plain oder multipart/alternative)."""
    if html:
        msg = MIMEMultipart('alternative')
        msg.attach(MIMEText(text, 'plain', 'utf-8'))
        msg.attach(MIMEText(html, 'html', 'utf-8'))
    else:
        msg = MIMEText(text, 'plain', 'utf-8')

    msg['Subject'] = betreff
    msg['From'] = formataddr((from_name or '', from_addr))
    msg['To'] = ', '.join(to_list)
    if reply_to:
        msg['Reply-To'] = reply_to
    return msg


def _smtp_senden(cfg: dict, to_list: list[str], msg, from_addr: str) -> None:
    """SMTP-Connect + Send. Getrennt, damit in Tests mockbar."""
    with smtplib.SMTP(cfg['smtp_host'], cfg['smtp_port'], timeout=15) as smtp:
        smtp.ehlo()
        if cfg['smtp_tls']:
            smtp.starttls()
            smtp.ehlo()
        if cfg['smtp_user']:
            smtp.login(cfg['smtp_user'], cfg['smtp_pass'])
        smtp.send_message(msg, from_addr=from_addr, to_addrs=to_list)
