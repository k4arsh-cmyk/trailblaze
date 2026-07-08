"""
track.py - add a wallet to the watch list.
Usage:  python3 track.py 0xADDRESS "nickname"
"""
import sys
import db

if len(sys.argv) < 2:
    raise SystemExit('Usage: python3 track.py 0xADDRESS "nickname"')

address = sys.argv[1].lower()
nickname = sys.argv[2] if len(sys.argv) > 2 else ""

con = db.connect()
# INSERT OR IGNORE: if the address is already tracked, do nothing instead of crashing.
con.execute("INSERT OR IGNORE INTO wallets(address, nickname) VALUES (?, ?)",
            (address, nickname))
con.commit()

rows = con.execute("SELECT address, nickname FROM wallets").fetchall()
print(f"Tracking {len(rows)} wallet(s):")
for r in rows:
    print(f"  {r['address']}  {r['nickname']}")
con.close()
