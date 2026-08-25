# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues on **Alex6460064/Immo**. Use the `gh` CLI
for all operations.

**Pas de repo git local pour l'instant** (`.git` absent) : `gh` ne peut pas inférer le repo via
`git remote -v` comme d'habitude. Passer `--repo Alex6460064/Immo` explicitement sur chaque
commande `gh` tant que le clone local n'existe pas.

## Conventions

- **Create an issue**: `gh issue create --repo Alex6460064/Immo --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --repo Alex6460064/Immo --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --repo Alex6460064/Immo --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --repo Alex6460064/Immo --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --repo Alex6460064/Immo --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --repo Alex6460064/Immo --comment "..."`

Once a local clone exists with the GitHub remote set, `--repo` becomes optional — `gh` infers
it from `git remote -v`.

## Pull requests as a triage surface

**PRs as a request surface: no.** Solo project, no external contributors — this repo does not
use PRs as a triage/request surface (confirmed during grilling: solo dev, no GitHub PR review
flow; code review happens locally per ticket instead).

## When a skill says "publish to the issue tracker"

Create a GitHub issue on `Alex6460064/Immo`.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --repo Alex6460064/Immo --comments`.

## Triage labels

The `triage` skill isn't installed in this plugin version, so the full 5-label vocabulary
isn't wired up. `to-spec` still applies a single `ready-for-agent` label to specs it publishes
— that label exists on the repo but isn't part of a configured triage workflow.
