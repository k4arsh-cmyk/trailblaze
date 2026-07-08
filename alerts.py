"""
alerts.py - Trailblaze alert engine (v1: two rules).
Run after the indexer:  python3 alerts.py
Alerts are stored in the DB so the same event never fires twice.

Rule 1  LOOP     : >= LOOP_N identical payments (same counterparty, same
                   amount) within LOOP_WINDOW minutes. The "stuck agent".
Rule 2  SILENCE  : tracked wallet with no activity for SILENT_DAYS days.
"""
import time
import db

LOOP_N = 10          # how many identical payments...
LOOP_WINDOW = 10     # ...within how many minutes
SILENT_DAYS = 3

con = db.connect()
con.executescript("""
CREATE TABLE IF NOT EXISTS alerts (
    rule       TEXT,     -- 'loop' | 'silence'
    wallet     TEXT,
    other      TEXT,     -- counterparty (loop only)
    detail     TEXT,     -- human-readable description
    first_ts   INTEGER,  -- when the event started
    created_at TEXT DEFAULT (datetime('now')),
    -- same rule + wallet + counterparty + start time = same event: fire once.
    UNIQUE(rule, wallet, other, first_ts)
);
""")

new_alerts = 0

# ---------- Rule 1: loops ----------
# Get every (wallet, counterparty, amount) group that even has enough
# payments to possibly be a loop, then check timing within each group.
groups = con.execute("""
    SELECT wallet,
           CASE WHEN from_addr = wallet THEN to_addr ELSE from_addr END AS other,
           amount, COUNT(*) AS n
    FROM transfers
    WHERE from_addr = wallet          -- outgoing payments only
    GROUP BY wallet, other, amount
    HAVING n >= :n
""", {"n": LOOP_N}).fetchall()

for g in groups:
    # timestamps of this exact repeated payment, oldest first
    ts_list = [r["ts"] for r in con.execute(
        "SELECT ts FROM transfers WHERE wallet=? AND from_addr=? AND to_addr=? AND amount=? ORDER BY ts",
        (g["wallet"], g["wallet"], g["other"], g["amount"]))]
    # sliding window: does any stretch of LOOP_N payments fit in LOOP_WINDOW min?
    for i in range(len(ts_list) - LOOP_N + 1):
        span = ts_list[i + LOOP_N - 1] - ts_list[i]
        if span <= LOOP_WINDOW * 60:
            detail = (f"{LOOP_N}+ identical payments of ${g['amount']:.4f} to "
                      f"{g['other'][:10]}… within {span//60}m{span%60}s "
                      f"(group total: {g['n']} payments)")
            cur = con.execute(
                "INSERT OR IGNORE INTO alerts(rule, wallet, other, detail, first_ts) "
                "VALUES ('loop', ?, ?, ?, ?)",
                (g["wallet"], g["other"], detail, ts_list[i]))
            new_alerts += cur.rowcount
            break  # one alert per group is enough

# ---------- Rule 2: silence ----------
now = int(time.time())
for w in con.execute("SELECT address, nickname FROM wallets"):
    last = con.execute("SELECT MAX(ts) t FROM transfers WHERE wallet=?",
                       (w["address"],)).fetchone()["t"]
    if last and now - last > SILENT_DAYS * 86400:
        days = (now - last) // 86400
        detail = f"No activity for {days} days (last: {time.strftime('%b %d %H:%M', time.gmtime(last))} UTC)"
        cur = con.execute(
            "INSERT OR IGNORE INTO alerts(rule, wallet, other, detail, first_ts) "
            "VALUES ('silence', ?, '', ?, ?)",
            (w["address"], detail, last))
        new_alerts += cur.rowcount

con.commit()
total = con.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"]
print(f"{new_alerts} new alert(s). {total} total in DB:")
for a in con.execute("SELECT rule, wallet, detail FROM alerts ORDER BY first_ts DESC"):
    print(f"  [{a['rule'].upper():7s}] {a['wallet'][:10]}…  {a['detail']}")
con.close()
