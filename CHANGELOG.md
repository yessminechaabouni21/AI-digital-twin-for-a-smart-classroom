# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once a first release is tagged.

## [Unreleased]

### Added

- `docs/DATASETS.md`: research and comparison of 27 public datasets against
  the project's 8 objectives, with a scored ranking table and a recommended
  dataset combination (OULAD as spine + 7 targeted supplements).
- DECISIONS.md ADR-008 recording the dataset combination decision.
- Initial project scaffolding: directory structure for `src/digital_twin/`
  (api, core, domain, twin_engine, analytics, agents, data, schemas), tests,
  notebooks, scripts, docs, data folders.
- Documentation: README.md, CLAUDE.md, PROJECT_PLAN.md, TODO.md,
  DECISIONS.md (ADR-001 through ADR-007).
- Tooling: requirements.txt, pyproject.toml (hatchling build, ruff/black/mypy
  config, pytest config), .gitignore, .env.example.
- Git repository initialized.
