"""Helpers de formatage des rapports de fin d'etape du pipeline.

`format_pct` etait duplique a l'identique dans 04_join.py et 04b_join_iris.py
(fonction locale `pct` fermant sur `total`) -- factorise ici (#22).
"""

from __future__ import annotations


def format_pct(n: int, total: int) -> str:
    """`n / total` en pourcentage a une decimale, ou "-" si `total` est nul."""
    return f"{n / total * 100:.1f}%" if total else "-"
