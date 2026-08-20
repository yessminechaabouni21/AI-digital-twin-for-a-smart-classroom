# Dataset documentation index

This file used to be a single 484-line comparative research document (27
candidate datasets scored against the project's 8 objectives). That research
is summarized in [DECISIONS.md](../DECISIONS.md) ADR-008 (adopted
combination, explicit rejections, and why); the original line-by-line catalog
was not preserved when the per-dataset documentation below was split out. If
you need the full original comparison, it's in git history at commit
`cb92deb` (`git show cb92deb:docs/DATASETS.md`).

This file now just indexes the per-dataset inspection/preprocessing docs that
came out of that decision — one plan per dataset actually loaded into
Postgres:

- [oulad.md](datasets/oulad.md) — OULAD raw-file inspection and the
  relational schema derived from it.
- [oulad-preprocessing-plan.md](datasets/oulad-preprocessing-plan.md) — OULAD
  load pipeline.
- [xapi-preprocessing-plan.md](datasets/xapi-preprocessing-plan.md) —
  xAPI-Edu-Data load pipeline.
- [assist-preprocessing-plan.md](datasets/assist-preprocessing-plan.md) —
  ASSISTments 2019–2020 load pipeline.
- [spanish-co2-preprocessing-plan.md](datasets/spanish-co2-preprocessing-plan.md)
  — Spanish Classroom CO2 sensor dataset load pipeline.
- [occupancy-preprocessing-plan.md](datasets/occupancy-preprocessing-plan.md)
  — UCI Occupancy Detection load pipeline.
- [schema-validation.md](datasets/schema-validation.md) — check that the
  OULAD-derived schema generalizes to the other adopted datasets.
- [data-quality-audit.md](datasets/data-quality-audit.md) — keep/delete/
  replace pass over everything under `data/raw/`.
- [dropout-prediction-feature-design.md](datasets/dropout-prediction-feature-design.md)
  — feature/target design for the OULAD dropout-risk model (first ML
  experiment built on the loaded data).

See [PROJECT_PLAN.md](../PROJECT_PLAN.md) M1 for how these fed
implementation and the current load status/row counts per dataset.
