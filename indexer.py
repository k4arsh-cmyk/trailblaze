"""
indexer.py - the heartbeat of Trailblaze.
For every tracked wallet: fetch its USDC transfers from Blockscout and store
any we haven't seen before. Run it as often as you like - it never duplicates.
Usage:  python3 indexer.py
"""
import json
import urllib.request
import db

API_URL = "https://base.blockscout.com/api"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def fetch_transfers(wallet: str) -> list:
    url = (f"{API_URL}?module=account&action=tokentx&contractaddress={USDC}"
           f"&address={wallet}&sort=desc&page=1&offset=500")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return data["result"] if isinstance(data.get("result"), list) else []


def index_wallet(con, wallet: str) -> int:
    """Store new transfers for one wallet. Returns how many were new."""
    new = 0
    for tx in fetch_transfers(wallet):
        # INSERT OR IGNORE + the UNIQUE rule in db.py = automatic de-duplication.
        # Seen it before? The insert silently does nothing. This property is
        # called idempotency: running the job twice changes nothing.
        cur = con.execute(
            "INSERT OR IGNORE INTO transfers(tx_hash, ts, from_addr, to_addr, amount, wallet) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tx["hash"], int(tx["timeStamp"]), tx["from"].lower(),
             tx["to"].lower(), int(tx["value"]) / 10**6, wallet))
        new += cur.rowcount  # 1 if inserted, 0 if ignored
    return new


def main():
    con = db.connect()
    wallets = [r["address"] for r in con.execute("SELECT address FROM wallets")]
    if not wallets:
        raise SystemExit("No wallets tracked yet. Add one: python3 track.py 0xADDR \"name\"")
    for w in wallets:
        new = index_wallet(con, w)
        total = con.execute("SELECT COUNT(*) c FROM transfers WHERE wallet=?", (w,)).fetchone()["c"]
        print(f"{w[:10]}...  +{new} new  ({total} total stored)")
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
