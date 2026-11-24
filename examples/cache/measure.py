"""Writes hit_rates.csv: how often TTLCache answers from memory, for a few sizes, on one fixed workload.

20,000 lookups over 500 keys; key k is asked for in proportion to 1/k (a few keys are popular, most are rare).
Nothing expires during the run, so only the size limit makes the cache forget.  Run:  python measure.py
"""
import csv
import random

from ttl_cache import TTLCache

random.seed(7)
KEYS = list(range(1, 501))
WEIGHTS = [1 / k for k in KEYS]
LOOKUPS = random.choices(KEYS, WEIGHTS, k=20_000)

with open("hit_rates.csv", "w", newline="") as out:
    rows = csv.writer(out)
    rows.writerow(["maxsize", "hits", "misses", "hit rate"])
    for size in (4, 8, 16, 32, 64, 128, 256, 512):
        cache = TTLCache(maxsize=size, ttl=3600)
        for key in LOOKUPS:
            cache.get_or_load(key, lambda: key)
        rows.writerow([size, cache.hits, cache.misses, f"{100 * cache.hit_rate():.1f}%"])
