"""
Kleiner Helfer für serverseitige Listen: Sortierung (Whitelist gegen
SQL-Injection), Paginierung, Template-Kontext.

Bewusst schlank — keine ORM-Schicht. ``allowed`` mappt UI-Schlüssel
auf den ERLAUBTEN SQL-Ausdruck; nur darüber kommt etwas in ORDER BY.
"""
from __future__ import annotations

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
