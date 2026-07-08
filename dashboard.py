"""
dashboard.py - Trailblaze: self-serve agent spend intelligence.
Run:   streamlit run dashboard.py
"""
import re
import time
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import db
import indexer  # reuse the indexing logic - one implementation, everywhere (DRY)

st.set_page_config(page_title="Trailblaze", page_icon="🔥", layout="wide")

con = db.connect()
# guest-wallet bookkeeping (exists only if missing; harmless re-run)
con.executescript("""
CREATE TABLE IF NOT EXISTS index_log (
    wallet     TEXT PRIMARY KEY,
    indexed_at INTEGER
);
""")

labels = {r["address"]: r["name"] for r in con.execute("SELECT address, name FROM labels")}


def name(addr: str) -> str:
    return labels.get(addr, addr[:8] + "…" + addr[-4:])


REINDEX_SECONDS = 10 * 60  # don't re-fetch the same wallet more often than this


def ensure_indexed(wallet: str) -> str | None:
    """Index a wallet if we haven't (recently). Returns error message or None."""
    row = con.execute("SELECT indexed_at FROM index_log WHERE wallet=?", (wallet,)).fetchone()
    fresh = row and (time.time() - row["indexed_at"]) < REINDEX_SECONDS
    if fresh:
        return None  # cached - instant
    try:
        with st.spinner("Reading the chain…"):
            indexer.index_wallet(con, wallet)
        con.execute("INSERT OR REPLACE INTO index_log(wallet, indexed_at) VALUES (?, ?)",
                    (wallet, int(time.time())))
        con.commit()
        return None
    except Exception as e:
        return f"Couldn't fetch chain data right now ({type(e).__name__}). Try again in a minute."


def find_loops(wallet: str, n: int = 10, window_min: int = 10) -> list[str]:
    """On-the-fly loop scan for one wallet (same rule as alerts.py)."""
    out = []
    groups = con.execute("""
        SELECT to_addr, amount, COUNT(*) AS c, GROUP_CONCAT(ts) AS times
        FROM transfers WHERE wallet=:w AND from_addr=:w
        GROUP BY to_addr, amount HAVING c >= :n
    """, {"w": wallet, "n": n}).fetchall()
    for g in groups:
        ts = sorted(int(t) for t in g["times"].split(","))
        for i in range(len(ts) - n + 1):
            span = ts[i + n - 1] - ts[i]
            if span <= window_min * 60:
                out.append(f"{n}+ identical ${g['amount']:.4f} payments to "
                           f"{name(g['to_addr'])} within {span // 60}m{span % 60}s "
                           f"({g['c']} total) — possible loop")
                break
    return out


def render_wallet(wallet: str):
    """The full per-wallet view. Used by featured tabs AND guest lookups."""
    tot = con.execute("""
        SELECT SUM(CASE WHEN from_addr = :w THEN amount ELSE 0 END) AS out_usd,
               SUM(CASE WHEN from_addr != :w THEN amount ELSE 0 END) AS in_usd,
               COUNT(*) AS n, MAX(ts) AS last_ts
        FROM transfers WHERE wallet = :w
    """, {"w": wallet}).fetchone()

    if not tot["n"]:
        st.info("No USDC transfers found for this address on Base.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Transfers analyzed", f"{tot['n']:,}")
    c2.metric("Money in", f"${tot['in_usd']:,.2f}")
    c3.metric("Money out", f"${tot['out_usd']:,.2f}")
    last = datetime.fromtimestamp(tot["last_ts"], tz=timezone.utc)
    c4.metric("Last activity", last.strftime("%b %d, %H:%M UTC"))

    # anomalies for this wallet, computed live
    for msg in find_loops(wallet):
        st.error(f"**LOOP** — {msg}")
    idle_days = (time.time() - tot["last_ts"]) / 86400
    if idle_days >= 3:
        st.warning(f"**SILENCE** — no activity for {idle_days:.1f} days "
                   "(crashed, out of funds, or stuck?)")

    rows = con.execute("""
        SELECT CASE WHEN from_addr = :w THEN to_addr ELSE from_addr END AS other,
               COUNT(*) AS n,
               SUM(CASE WHEN from_addr = :w THEN amount ELSE 0 END) AS out_usd,
               SUM(CASE WHEN from_addr != :w THEN amount ELSE 0 END) AS in_usd
        FROM transfers WHERE wallet = :w GROUP BY other
    """, {"w": wallet}).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    df["counterparty"] = df["other"].map(name)
    by_name = (df.groupby("counterparty", as_index=False)
                 .agg(payments=("n", "sum"), in_usd=("in_usd", "sum"),
                      out_usd=("out_usd", "sum"))
                 .sort_values(["out_usd", "in_usd"], ascending=False))

    left, right = st.columns([3, 2])
    with left:
        st.subheader("By counterparty")
        st.dataframe(by_name, use_container_width=True, hide_index=True,
                     column_config={
                         "in_usd": st.column_config.NumberColumn("in $", format="$%.2f"),
                         "out_usd": st.column_config.NumberColumn("out $", format="$%.2f"),
                     })
    with right:
        st.subheader("Where the money goes")
        spend = (by_name[by_name["out_usd"] > 0].head(10)
                 .set_index("counterparty")["out_usd"])
        if len(spend):
            st.bar_chart(spend)
        else:
            st.info("No outgoing spend — this address only receives (a merchant).")

    st.subheader("Daily activity")
    daily = con.execute("""
        SELECT date(ts, 'unixepoch') AS day,
               SUM(CASE WHEN from_addr = :w THEN amount ELSE 0 END) AS out_usd,
               SUM(CASE WHEN from_addr != :w THEN amount ELSE 0 END) AS in_usd
        FROM transfers WHERE wallet = :w GROUP BY day ORDER BY day
    """, {"w": wallet}).fetchall()
    st.bar_chart(pd.DataFrame([dict(r) for r in daily]).set_index("day"))

    st.subheader("Recent transfers")
    recent = con.execute("""
        SELECT ts, from_addr, to_addr, amount FROM transfers
        WHERE wallet = :w ORDER BY ts DESC LIMIT 50
    """, {"w": wallet}).fetchall()
    st.dataframe(pd.DataFrame([{
        "time": datetime.fromtimestamp(r["ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "direction": "OUT" if r["from_addr"] == wallet else "IN",
        "counterparty": name(r["to_addr"] if r["from_addr"] == wallet else r["from_addr"]),
        "amount": r["amount"],
    } for r in recent]), use_container_width=True, hide_index=True,
        column_config={"amount": st.column_config.NumberColumn(format="$%.4f")})


# ---------------- page ----------------
st.title("Trailblaze")
st.caption("The expense ledger of the agent economy — read-only, live from Base. "
           "We hold no keys and move no money.")

st.subheader("Analyze any wallet")
query = st.text_input("Paste a Base wallet address (agent, merchant — anything that pays "
                      "or gets paid in USDC):", placeholder="0x…")

if query:
    addr = query.strip().lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", addr):
        st.error("That doesn't look like a wallet address (must be 0x + 40 hex characters).")
    else:
        err = ensure_indexed(addr)
        if err:
            st.error(err)
        else:
            st.markdown(f"#### Report for `{addr}`")
            render_wallet(addr)
            st.caption("Want alerts and weekly statements for your agents? "
                       "Email k4arsh@gmail.com — early access.")

st.divider()
st.subheader("Featured wallets")
wallets = con.execute("SELECT address, nickname FROM wallets").fetchall()
if wallets:
    tabs = st.tabs([w["nickname"] or w["address"][:10] for w in wallets])
    for tab, w in zip(tabs, wallets):
        with tab:
            render_wallet(w["address"])

con.close()
