"""
Kleiner Helfer für serverseitige Listen: Sortierung (Whitelist gegen
SQL-Injection), Paginierung, Template-Kontext.

Bewusst schlank — keine ORM-Schicht. ``allowed`` mappt UI-Schlüssel
auf den ERLAUBTEN SQL-Ausdruck; nur darüber kommt etwas in ORDER BY.
"""
from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Mapping


def parse_sort(args, allowed: Mapping[str, str],
               default_order: str) -> tuple[str, str, str]:
    """Returns ``(order_by_sql, sort_key, direction)``.

    Greift nur, wenn ``sort`` in ``allowed`` UND ``dir`` ∈
    {asc,desc} — sonst ``default_order`` (= Sortierung „aufgehoben").
    """
    sort = (args.get('sort') or '').strip()
    direction = (args.get('dir') or '').strip().lower()
    if sort in allowed and direction in ('asc', 'desc'):
        # Tie-Breaker für stabile Paginierung anhängen.
        return (f'{allowed[sort]} {direction.upper()}, '
                f'{default_order}'), sort, direction
    return default_order, '', ''


def parse_paging(args, *, default_per_page: int = 100,
                 max_per_page: int = 500) -> tuple[int, int]:
    """Returns ``(page, per_page)`` (1-basiert, geklemmt)."""
    page = args.get('page', type=int) or 1
    per_page = args.get('per_page', type=int) or default_per_page
    page = max(1, page)
    per_page = min(max(10, per_page), max_per_page)
    return page, per_page


def pager(total: int, page: int, per_page: int) -> dict[str, Any]:
    """Template-Kontext: clamped page, offset, von/bis, Seitenzahl."""
    total = max(0, int(total))
    seiten = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), seiten)
    offset = (page - 1) * per_page
    return {
        'total':   total,
        'page':    page,
        'per_page': per_page,
        'seiten':  seiten,
        'offset':  offset,
        'von':     0 if total == 0 else offset + 1,
        'bis':     min(total, offset + per_page),
        'hat_zurueck': page > 1,
        'hat_vor':     page < seiten,
    }


_MONATE = ('', 'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
           'Juli', 'August', 'September', 'Oktober', 'November',
           'Dezember')
GRAN = ('monat', 'quartal', 'jahr')


def periode(gran: str, anchor: str | None,
            heute: date | None = None) -> dict[str, Any]:
    """Berechnet Zeitraum-Navigation (Monat/Quartal/Jahr).

    ``anchor``-Format: Monat ``YYYY-MM`` · Quartal ``YYYY-Qn`` ·
    Jahr ``YYYY``. Ungültig/leer → aktueller Zeitraum.

    Returns ``{gran, anchor, von, bis (date), label, prev, next}``.
    """
    heute = heute or date.today()
    gran = gran if gran in GRAN else 'monat'

    def _monat_ende(y: int, m: int) -> date:
        return date(y, m, calendar.monthrange(y, m)[1])

    if gran == 'jahr':
        try:
            y = int((anchor or '').strip())
        except (TypeError, ValueError):
            y = heute.year
        von, bis = date(y, 1, 1), date(y, 12, 31)
        label = f'{y}'
        prev, nxt = str(y - 1), str(y + 1)

    elif gran == 'quartal':
        try:
            ys, qs = (anchor or '').upper().split('-Q')
            y, q = int(ys), int(qs)
            if not 1 <= q <= 4:
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            y, q = heute.year, (heute.month - 1) // 3 + 1
        m0 = (q - 1) * 3 + 1
        von, bis = date(y, m0, 1), _monat_ende(y, m0 + 2)
        label = f'Q{q} {y}'
        pq, py = (4, y - 1) if q == 1 else (q - 1, y)
        nq, ny = (1, y + 1) if q == 4 else (q + 1, y)
        prev, nxt = f'{py}-Q{pq}', f'{ny}-Q{nq}'

    else:  # monat
        try:
            ys, ms = (anchor or '').split('-')
            y, m = int(ys), int(ms)
            if not 1 <= m <= 12:
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            y, m = heute.year, heute.month
        von, bis = date(y, m, 1), _monat_ende(y, m)
        label = f'{_MONATE[m]} {y}'
        pm, py = (12, y - 1) if m == 1 else (m - 1, y)
        nm, ny = (1, y + 1) if m == 12 else (m + 1, y)
        prev, nxt = f'{py}-{pm:02d}', f'{ny}-{nm:02d}'

    return {'gran': gran, 'anchor': anchor or '', 'von': von,
            'bis': bis, 'label': label, 'prev': prev, 'next': nxt}
