"""
dashboard.py - Trailblaze v1 dashboard.
Run:   streamlit run dashboard.py
Stop:  Ctrl+C in the terminal.
"""
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import db

st.set_page_config(page_title="Trailblaze", page_icon="🔥", layout="wide")

con = db.connect()
labels = {r["address"]: r["name"] for r in con.execute("SELECT address, name FROM labels")}


def name(addr: str) -> str:
    return labels.get(addr, addr[:8] + "…" + addr[-4:])


st.title("Trailblaze")
st.caption("The expense ledger of the agent economy — read-only, live from Base.")

# ---- Alerts panel (from alerts.py; table may not exist on first run)
try:
    alerts = con.execute(
        "SELECT rule, wallet, detail, created_at FROM alerts ORDER BY first_ts DESC LIMIT 20"
    ).fetchall()
except Exception:
    alerts = []
if alerts:
    st.subheader(f"⚠ Alerts ({len(alerts)})")
    for a in alerts:
        nick = con.execute("SELECT nickname FROM wallets WHERE address=?",
                           (a["wallet"],)).fetchone()
        who = (nick["nickname"] if nick and nick["nickname"] else a["wallet"][:10] + "…")
        line = f"**{a['rule'].upper()}** · {who} — {a['detail']}"
        (st.error if a["rule"] == "loop" else st.warning)(line)

wallets = con.execute("SELECT address, nickname FROM wallets").fetchall()
if not wallets:
    st.warning("No wallets tracked. Add one: python3 track.py 0xADDR \"name\"")
    st.stop()

# One tab per tracked wallet
tabs = st.tabs([w["nickname"] or w["address"][:10] for w in wallets])

for tab, w in zip(tabs, wallets):
    wallet = w["address"]
    with tab:
        # ---- headline numbers
        tot = con.execute("""
            SELECT SUM(CASE WHEN from_addr = :w THEN amount ELSE 0 END) AS out_usd,
                   SUM(CASE WHEN from_addr != :w THEN amount ELSE 0 END) AS in_usd,
                   COUNT(*) AS n, MAX(ts) AS last_ts
            FROM transfers WHERE wallet = :w
        """, {"w": wallet}).fetchone()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Transfers stored", f"{tot['n']:,}")
        c2.metric("Money in", f"${tot['in_usd']:,.2f}")
        c3.metric("Money out", f"${tot['out_usd']:,.2f}")
        last = datetime.fromtimestamp(tot["last_ts"], tz=timezone.utc)
        c4.metric("Last activity", last.strftime("%b %d, %H:%M UTC"))

        # ---- spend by counterparty (grouped by NAME -> fixes the double-label bug)
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
            spend = by_name[by_name["out_usd"] > 0].set_index("counterparty")["out_usd"]
            if len(spend):
                st.bar_chart(spend)
            else:
                st.info("No outgoing spend for this wallet (it's a merchant — money only comes in).")

        # ---- daily activity
        st.subheader("Daily activity")
        daily = con.execute("""
            SELECT date(ts, 'unixepoch') AS day,
                   SUM(CASE WHEN from_addr = :w THEN amount ELSE 0 END) AS out_usd,
                   SUM(CASE WHEN from_addr != :w THEN amount ELSE 0 END) AS in_usd
            FROM transfers WHERE wallet = :w GROUP BY day ORDER BY day
        """, {"w": wallet}).fetchall()
        ddf = pd.DataFrame([dict(r) for r in daily]).set_index("day")
        st.bar_chart(ddf)

        # ---- recent transfers, labeled
        st.subheader("Recent transfers")
        recent = con.execute("""
            SELECT ts, from_addr, to_addr, amount FROM transfers
            WHERE wallet = :w ORDER BY ts DESC LIMIT 50
        """, {"w": wallet}).fetchall()
        rdf = pd.DataFrame([{
            "time": datetime.fromtimestamp(r["ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "direction": "OUT" if r["from_addr"] == wallet else "IN",
            "counterparty": name(r["to_addr"] if r["from_addr"] == wallet else r["from_addr"]),
            "amount": r["amount"],
        } for r in recent])
        st.dataframe(rdf, use_container_width=True, hide_index=True,
                     column_config={"amount": st.column_config.NumberColumn(format="$%.4f")})

con.close()
