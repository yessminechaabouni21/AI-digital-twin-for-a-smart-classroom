"""OULAD preprocessing pipeline: raw CSVs -> validated, DB-ready tables.

One module per source file (preprocess_courses.py, preprocess_vle.py, ...),
executed in dependency order by load_oulad.py. See
docs/datasets/oulad-preprocessing-plan.md for the full plan each module
implements.
"""
