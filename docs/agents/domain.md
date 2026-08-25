# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the
codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — single-context repo, no `CONTEXT-MAP.md` needed.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

## File structure

Single-context repo:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-communes-hors-dept-64.md
│   ├── 0002-dvf-brut-plus-geocodage-ban.md
│   ├── 0003-algorithme-appariement-dvf-dpe.md
│   └── 0004-carte-choroplethe-iris.md
├── config/
├── pipeline/
└── dashboard/
```

## Use the glossary's vocabulary

When your output names a domain concept (issue title, ticket, test name), use the term as
defined in `CONTEXT.md` — e.g. **Mutation**, **Vente appariée**, **DPE post-réforme**, **Taux
d'appariement**, **Ambigu**, **Commune ciblée**, **IRIS**. Don't drift to the synonyms the
glossary explicitly lists under `_Avoid_`.

If a concept isn't in the glossary yet, that's a signal — either you're inventing language the
project doesn't use, or there's a real gap worth flagging for `/domain-modeling`.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently
overriding it — e.g. "Contradicts ADR-0002 (DVF brut + géocodage BAN) — but worth reopening
because…".
