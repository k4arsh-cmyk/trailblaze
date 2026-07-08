"""
Script #3: labeled spend report. Addresses become NAMES where known.
Usage:  python3 spend_report.py 0xADDRESS
Labels come from Coinbase's Bazaar (public x402 service directory),
cached in labels.json, plus your manual entries in labels_manual.json.
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

API_URL = "https://base.blockscout.com/api"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BAZAAR = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
CACHE = Path(__file__).parent / "labels.json"          # auto-built, safe to delete
MANUAL = Path(__file__).parent / "labels_manual.json"  # yours; survives rebuilds


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def build_labels() -> dict:
    """payTo address -> service domain, from the Bazaar directory."""
    if CACHE.exists():  # cached from a previous run; delete labels.json to refresh
        labels = json.loads(CACHE.read_text())
    else:
        print("Fetching label directory from Coinbase Bazaar...")
        labels = {}
        data = fetch_json(BAZAAR + "?limit=100")
        # The directory's exact shape may change, so we parse defensively:
        # for each listed service, regex out its payTo address + its URL.
        items = data.get("items") or data.get("resources") or data.get("data") or []
        for item in items:
            blob = json.dumps(item)
            addrs = re.findall(r'"payTo"\s*:\s*"(0x[0-9a-fA-F]{40})"', blob)
            urls = re.findall(r'https?://[^"]+', blob)
            if addrs and urls:
                domain = urlparse(urls[0]).netloc or urls[0]
                for a in addrs:
                    labels.setdefault(a.lower(), domain)
        CACHE.write_text(json.dumps(labels, indent=1))
        print(f"Cached {len(labels)} labels to labels.json\n")
    if MANUAL.exists():  # manual labels override/extend the auto ones
        labels.update({k.lower(): v for k, v in json.loads(MANUAL.read_text()).items()})
    return labels


def name(addr: str, labels: dict) -> str:
    return labels.get(addr.lower(), addr[:8] + "…" + addr[-4:])  # name, else short addr


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 spend_report.py 0xADDRESS")
    wallet = sys.argv[1].lower()
    labels = build_labels()

    url = (f"{API_URL}?module=account&action=tokentx&contractaddress={USDC}"
           f"&address={wallet}&sort=desc&page=1&offset=200")
    data = fetch_json(url)
    txs = data["result"] if isinstance(data.get("result"), list) else []
    print(f"{len(txs)} recent USDC transfers for {name(wallet, labels)} on Base\n")

    total_in = total_out = 0.0
    partners = {}  # counterparty -> [in_total, out_total, count]

    for tx in txs:
        amount = int(tx["value"]) / 10**6
        outgoing = tx["from"].lower() == wallet
        other = tx["to"] if outgoing else tx["from"]
        p = partners.setdefault(other.lower(), [0.0, 0.0, 0])
        if outgoing:
            total_out += amount
            p[1] += amount
        else:
            total_in += amount
            p[0] += amount
        p[2] += 1

    for tx in txs[:15]:
        amount = int(tx["value"]) / 10**6
        when = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
        if tx["from"].lower() == wallet:
            line = f"OUT -> {name(tx['to'], labels)}"
        else:
            line = f"IN  <- {name(tx['from'], labels)}"
        print(f"{when:%Y-%m-%d %H:%M}  {line}  ${amount:,.4f}")

    print(f"\nTotal in: ${total_in:,.2f}   Total out: ${total_out:,.2f}")
    print("\nBy counterparty (top 10 by activity):")
    top = sorted(partners.items(), key=lambda x: -(x[1][0] + x[1][1]))[:10]
    for addr, (tin, tout, n) in top:
        flow = f"in ${tin:,.2f}" if tin else f"out ${tout:,.2f}"
        print(f"  {name(addr, labels):40s} {n:4d} txs  {flow}")


if __name__ == "__main__":
    main()
