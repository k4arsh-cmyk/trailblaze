"""
Script #1: USDC spend report for any wallet on Base.
Usage:  python3 usdc_report.py 0xWALLET_ADDRESS
"""

import json
import sys
import urllib.request
from datetime import datetime, timezone

# Etherscan paywalled Base, so we use Blockscout: an open-source, free
# indexer with an Etherscan-compatible API. No key needed.
API_URL = "https://base.blockscout.com/api"

# USDC isn't "built into" the chain — it's a token contract (a program) living
# at this address. All USDC balances/transfers are bookkeeping inside it.
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def fetch_transfers(wallet: str) -> list:
    """Ask Etherscan for every USDC transfer in/out of this wallet."""
    url = (
        f"{API_URL}"
        "?module=account&action=tokentx"      # tokentx = token transfer history
        f"&contractaddress={USDC}"            # only USDC, ignore other tokens
        f"&address={wallet}"
        "&sort=desc"                          # newest first
        "&page=1&offset=200"                  # only latest 200 — full history can choke the server
    )
    # Servers often block Python's default identity ("Python-urllib") as
    # anti-bot protection. Sending a normal User-Agent header fixes it.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:  # give up after 30s instead of hanging
        data = json.load(r)
    if data["status"] != "1" and data["message"] != "No transactions found":
        raise SystemExit(f"API error: {data.get('result') or data.get('message')}")
    return data["result"] if isinstance(data["result"], list) else []


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 usdc_report.py 0xADDRESS")
    wallet = sys.argv[1].lower()

    txs = fetch_transfers(wallet)
    print(f"\n{len(txs)} USDC transfers for {wallet} on Base\n")

    total_in = total_out = 0.0
    counterparties = {}  # address -> total $ sent to it

    for tx in txs[:25]:  # print the 25 most recent
        # Amounts come as integers in "base units". USDC uses 6 decimals,
        # so 20000 means $0.02. This is how all tokens work on-chain.
        amount = int(tx["value"]) / 10**6
        when = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
        if tx["from"].lower() == wallet:
            direction, other = "OUT ->", tx["to"]
        else:
            direction, other = "IN  <-", tx["from"]
        print(f"{when:%Y-%m-%d %H:%M}  {direction} {other}  ${amount:,.4f}")

    for tx in txs:  # totals over full history
        amount = int(tx["value"]) / 10**6
        if tx["from"].lower() == wallet:
            total_out += amount
            counterparties[tx["to"]] = counterparties.get(tx["to"], 0) + amount
        else:
            total_in += amount

    print(f"\nTotal in:  ${total_in:,.2f}")
    print(f"Total out: ${total_out:,.2f}")

    if counterparties:
        print("\nTop 5 recipients of this wallet's money:")
        for addr, amt in sorted(counterparties.items(), key=lambda x: -x[1])[:5]:
            print(f"  {addr}  ${amt:,.2f}")
        print("\n^ These are just addresses. Turning them into NAMES")
        print("  (Firecrawl, Browserbase...) is your entire startup.")


if __name__ == "__main__":
    main()
