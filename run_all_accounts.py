"""Roda creative_champions.py para todas as contas Meta Ads."""
from creative_champions import run

ACCOUNTS = [
    "act_568162184127732",
    "act_670061628880862",
    "act_979740244075964",
]

for account_id in ACCOUNTS:
    try:
        run(ad_account_id=account_id)
    except Exception as e:
        print(f"\n[ERRO] Conta {account_id}: {e}\n")
