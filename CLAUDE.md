# CLAUDE.md

This file provides guidance to Claude Code when working with code in this
repository.

## Workflow Rules

**IMPORTANT: Always plan first, then wait for the user's literal "go" before
implementing anything.**

## Project Overview

AmSC (American Science Cloud) is an early prototype of DOE's Genesis Mission
platform: federating DOE compute and experimental data so that AI workloads
(training, inference, foundation models) run where the simulation data
already lives.

This repository holds the documentation side of the effort: use-case recipes,
setup/run guides, FAQs, presentations, and issue write-ups. It is not a
software package — there is no build system, package metadata, or test suite.
The Python scripts under `use-cases/` are self-contained driver examples that
accompany the docs.

## Repo conventions

- `use-cases/` — one directory per recipe (`hello-world`, `fine-tuning`,
  `heat`, `m3dc1`). Each typically contains `README.md`, `SETUP.md`,
  `RUN.md`, `FAQ.md`, and a driver script named `amsc.py`. Shared docs
  (`SETUP.md`, `FAQ.md`, `AMSC-MLFLOW-SETUP.md`) live at the `use-cases/`
  top level.
- `presentations/` — slide decks, named `YYYY-MM-DD-<topic>.html`.
- `issues-enhancements/` — one markdown file per issue or enhancement topic
  (e.g. `connectivity.md`).
- Keep new material in the matching directory; new use-cases follow the
  README/SETUP/RUN/FAQ + `amsc.py` pattern.
- Do not commit credentials, tokens, or key files (`*.tok`, `*.pem`, `*.id`,
  `token_*`) — some exist untracked in the working tree; leave them out of
  git.

## Verify loop

There is no test suite. Verification means reviewing the artifact you edited:
render/preview changed markdown, open changed HTML presentations in a
browser, and for driver scripts check they still parse
(`python -m py_compile <file>`). No repo-wide build or test command exists.
