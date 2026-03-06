import os
from dotenv import load_dotenv
import requests

load_dotenv()

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
GRAPH_API_VERSION = "v19.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def get_me():
    """Retorna informações do usuário/token atual."""
    url = f"{BASE_URL}/me"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name",
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def get_ad_accounts():
    """Lista as contas de anúncios disponíveis para o token."""
    url = f"{BASE_URL}/me/adaccounts"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,account_status,currency,timezone_name",
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def get_campaigns(ad_account_id: str):
    """Lista campanhas de uma conta de anúncios."""
    url = f"{BASE_URL}/{ad_account_id}/campaigns"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,status,objective,daily_budget,lifetime_budget,start_time,stop_time",
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def get_campaign_insights(campaign_id: str, date_preset: str = "last_30d"):
    """Retorna métricas de desempenho de uma campanha."""
    url = f"{BASE_URL}/{campaign_id}/insights"
    params = {
        "access_token": ACCESS_TOKEN,
        "date_preset": date_preset,
        "fields": "impressions,clicks,spend,ctr,cpm,cpp,reach,actions",
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def get_adsets(ad_account_id: str):
    """Lista conjuntos de anúncios de uma conta."""
    url = f"{BASE_URL}/{ad_account_id}/adsets"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,status,daily_budget,campaign_id,targeting,start_time,end_time",
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def get_ads(ad_account_id: str):
    """Lista anúncios de uma conta."""
    url = f"{BASE_URL}/{ad_account_id}/ads"
    params = {
        "access_token": ACCESS_TOKEN,
        "fields": "id,name,status,adset_id,campaign_id,creative",
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    import json

    print("=== Conectando à Meta Ads API ===\n")

    try:
        me = get_me()
        print(f"Autenticado como: {me.get('name')} (ID: {me.get('id')})\n")
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        print(f"Erro ao autenticar: {e.response.status_code} - {body}")
        exit(1)
    except requests.ConnectionError as e:
        print(f"Erro de conexão (verifique rede/token): {e}")
        exit(1)

    print("=== Contas de Anúncios ===")
    try:
        ad_accounts = get_ad_accounts()
        accounts = ad_accounts.get("data", [])
        if not accounts:
            print("Nenhuma conta de anúncios encontrada.")
        for account in accounts:
            print(json.dumps(account, indent=2, ensure_ascii=False))
    except requests.HTTPError as e:
        print(f"Erro ao buscar contas: {e}")

    account_id = AD_ACCOUNT_ID
    if account_id:
        print(f"\n=== Campanhas da conta {account_id} ===")
        try:
            campaigns = get_campaigns(account_id)
            for campaign in campaigns.get("data", []):
                print(json.dumps(campaign, indent=2, ensure_ascii=False))
        except requests.HTTPError as e:
            print(f"Erro ao buscar campanhas: {e}")
