"""(#24) Publie l'instantane de donnees lu par le dashboard sur un clone frais --
prealable au deploiement Streamlit Community Cloud (#25), qui deploie le repo
sans executer le pipeline.

Regenere `data/dashboard/` (tracke par git) depuis `data/processed/` +
`data/raw/iris_communes.geojson` : les 2 agregats + le geojson copies tels quels,
`dvf_dpe_matched.parquet` restreint aux 7 colonnes lues par le dashboard.

Idempotent et rejouable : deux executions successives produisent les memes
fichiers (cf. `pipeline/lib/publish_dashboard.py`). L'instantane est un produit
du pipeline, jamais pose a la main.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.publish_dashboard import (  # noqa: E402
    COPIED_AGGREGATES,
    IRIS_GEOJSON_NAME,
    MATCHED_NAME,
    publish_snapshot,
)

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "dashboard"

_REQUIRED = [
    *((PROCESSED / name, "05_aggregate.py") for name in COPIED_AGGREGATES),
    (PROCESSED / MATCHED_NAME, "04_join.py"),
    (RAW / IRIS_GEOJSON_NAME, "04b_join_iris.py"),
]


def main() -> None:
    missing = [(p, prev) for p, prev in _REQUIRED if not (p.exists() and p.stat().st_size > 0)]
    if missing:
        for path, prev in missing:
            print(f"ERREUR : fichier introuvable : {path}", file=sys.stderr)
            print(f"  Lancer d'abord : python pipeline/{prev}", file=sys.stderr)
        sys.exit(1)

    summary = publish_snapshot(PROCESSED, RAW, OUT)

    print("=== Publication instantane dashboard (data/dashboard/, #24) ===")
    for item in summary:
        rows = "        -" if item["rows"] is None else f"{item['rows']:>7} l."
        print(f"  {item['name']:<26} {rows}   {item['bytes'] / 1024:>8.1f} Ko")
    total_ko = sum(item["bytes"] for item in summary) / 1024
    print(f"\n  {OUT} regenere -- {len(summary)} fichiers, {total_ko:.1f} Ko au total.")


if __name__ == "__main__":
    main()
