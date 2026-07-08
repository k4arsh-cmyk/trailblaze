"""
report.py - labeled spend report for every tracked wallet, from the DB.
No network calls: everything comes from trailblaze.db, so it's instant.
Usage:  python3 report.py
"""
from datetime import datetime, timezone
import db

con = db.connect()

# Load all labels once into a dict: {address: name}
labels = {r["address"]: r["name"] for r in con.execute("SELECT address, name FROM labels")}


def name(addr: str) -> str:
    return labels.get(addr, addr[:8] + "…" + addr[-4:])


for w in con.execute("SELECT address, nickname FROM wallets"):
    wallet, nick = w["address"], w["nickname"]
    print(f"\n{'='*62}\n{nick or wallet}  ({wallet[:10]}…)\n{'='*62}")

    # SQL does the math for us: GROUP BY collapses rows into summaries.
    # "For each counterparty: count payments, sum money in, sum money out."
    rows = con.execute("""
        SELECT
          CASE WHEN from_addr = :w THEN to_addr ELSE from_addr END AS other,
          COUNT(*)                                                  AS n,
          SUM(CASE WHEN from_addr = :w THEN amount ELSE 0 END)      AS out_usd,
          SUM(CASE WHEN from_addr != :w THEN amount ELSE 0 END)     AS in_usd,
          MAX(ts)                                                   AS last_ts
        FROM transfers
        WHERE wallet = :w
        GROUP BY other
        ORDER BY (out_usd + in_usd) DESC
        LIMIT 12
    """, {"w": wallet}).fetchall()

    tot = con.execute("""
        SELECT SUM(CASE WHEN from_addr = :w THEN amount ELSE 0 END) AS out_usd,
               SUM(CASE WHEN from_addr != :w THEN amount ELSE 0 END) AS in_usd,
               COUNT(*) AS n
        FROM transfers WHERE wallet = :w
    """, {"w": wallet}).fetchone()

    print(f"stored transfers: {tot['n']}   in: ${tot['in_usd']:,.2f}   out: ${tot['out_usd']:,.2f}\n")
    print(f"{'counterparty':38s} {'txs':>5s} {'in $':>9s} {'out $':>9s}  last seen")
    for r in rows:
        last = datetime.fromtimestamp(r["last_ts"], tz=timezone.utc).strftime("%b %d %H:%M")
        print(f"{name(r['other'])[:38]:38s} {r['n']:5d} {r['in_usd']:9.2f} {r['out_usd']:9.2f}  {last}")

con.close()
print()
