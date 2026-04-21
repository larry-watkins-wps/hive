"""Hive operator debug tools (spec §H.3).

Thin CLI wrappers for observing and injecting traffic on the MQTT bus, plus
a filesystem peek at a region's short-term memory. Read-only by design
(P-III sovereignty); ``hive inject`` is the sole write surface and is
authorized explicitly by §H.3 as an operator tool.
"""
