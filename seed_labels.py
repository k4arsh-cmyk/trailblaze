"""
seed_labels.py - move existing labels (labels.json + labels_manual.json)
into the database. Run once; safe to re-run.
Usage:  python3 seed_labels.py
"""
import json
from pathlib import Path
import db

HERE = Path(__file__).parent
con = db.connect()
count = 0

for fname, source in [("labels.json", "bazaar"), ("labels_manual.json", "manual")]:
    f = HERE / fname
    if not f.exists():
        continue
    for addr, name in json.loads(f.read_text()).items():
        # manual runs second so it overwrites bazaar on conflicts (REPLACE)
        con.execute("INSERT OR REPLACE INTO labels(address, name, source) VALUES (?, ?, ?)",
                    (addr.lower(), name, source))
        count += 1

con.commit()
total = con.execute("SELECT COUNT(*) c FROM labels").fetchone()["c"]
print(f"Imported {count} labels. Label table now has {total} entries.")
con.close()
