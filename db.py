"""
db.py - creates (or opens) the Trailblaze database.
Run once:  python3 db.py
Safe to re-run anytime: CREATE TABLE IF NOT EXISTS never destroys data.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "trailblaze.db"


def connect():
    """Open the database file (creates it if missing)."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row  # lets us read columns by name, not position
    return con


def init():
    con = connect()
    con.executescript("""
    -- Wallets we are tracking (our users' agent wallets)
    CREATE TABLE IF NOT EXISTS wallets (
        address   TEXT PRIMARY KEY,   -- PRIMARY KEY = no duplicates allowed
        nickname  TEXT,
        added_at  TEXT DEFAULT (datetime('now'))
    );

    -- Every USDC transfer we have ever seen for tracked wallets.
    CREATE TABLE IF NOT EXISTS transfers (
        tx_hash   TEXT,               -- on-chain transaction id
        ts        INTEGER,            -- unix timestamp
        from_addr TEXT,
        to_addr   TEXT,
        amount    REAL,               -- in dollars (already divided by 10^6)
        wallet    TEXT,               -- which tracked wallet this row belongs to
        -- one tx can contain several transfers, so uniqueness = whole row:
        UNIQUE(tx_hash, from_addr, to_addr, amount, wallet)
    );

    -- Address -> human name. The moat, in table form.
    CREATE TABLE IF NOT EXISTS labels (
        address TEXT PRIMARY KEY,
        name    TEXT,
        source  TEXT                  -- 'bazaar' | 'manual' | 'probe' | 'behavior'
    );

    -- Speeds up "all transfers for wallet X ordered by time"
    CREATE INDEX IF NOT EXISTS idx_transfers_wallet_ts ON transfers(wallet, ts);
    """)
    con.commit()
    con.close()
    print(f"Database ready: {DB_PATH.name}")


if __name__ == "__main__":
    init()
