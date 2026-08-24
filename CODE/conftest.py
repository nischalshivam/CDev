"""pytest config for CDev's CODE/ tests.

`test_pipeline.py` is a previous session's broken scratch file (undefined vars, no real assertions —
flagged in review). It breaks collection, so it is ignored here until it is fixed or removed. All
foundation tests live in test_catalog / test_intake / test_schemas / test_coverage / test_project.
"""
collect_ignore = ["test_pipeline.py"]
