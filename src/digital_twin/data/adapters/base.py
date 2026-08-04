"""Base interface all real data-source adapters must implement.

Keeping this as an explicit interface is what lets the project start on
synthetic data and later plug in real LMS/sensor sources without
redesigning the twin/analytics/agent layers.
"""

# TODO: define DataSourceAdapter protocol (fetch_students, fetch_interactions, ...).
