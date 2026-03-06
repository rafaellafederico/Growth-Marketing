import os
import json
from datetime import date, timedelta

import requests
from dotenv import load_dotenv
import anthropic

load_dotenv()

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID")
GRAPH_API_VERSION = "v19.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# Keywords para classificação de formato (case-insensitive)
FORMAT_KEYWORDS = {
    "BEST-SELLER": [
        "best", "seller", "bestsell", "best-sell", "mais vendido",
        "mais-vendido", "top seller", "top-seller", "bs",
    ],
    "ACAO_PROMOCIONAL": [
        "promo", "promocao", "promoção", "desconto", "off", "sale",
        "oferta", "black", "cupom", "frete gratis", "frete-gratis",
        "liquidacao", "liquidação", "flash", "deal",
    ],
    "LANCAMENTO": [
        "lanc", "lançamento", "lancamento", "launch", "new", "novo",
        "nova", "estreia", "chegou", "chegando",
    ],
}


def get_previous_month_range() -> tuple[str, str]:
    """Retorna (since, until) referentes ao mês calendário anterior."""
    today = date.today()
    first_this_month = today.replace(day=1)
    last_prev = first_this_month - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return first_prev.strftime("%Y-%m-%d"), last_prev.strftime("%Y-%m-%d")


def get_top_creatives(ad_account_id: str, since: str, until: str, limit: int = 40) -> list[dict]:
    """Busca os top anúncios por compras no período informado (nível ad)."""
    url = f"{BASE_URL}/{ad_account_id}/insights"
    params = {
        "access_token": ACCESS_TOKEN,
        "level": "ad",
        "time_range": json.dumps({"since": since, "until": until}),
        "fields": ",".join([
            "ad_id",
            "ad_name",
            "spend",
            "impressions",
            "reach",
            "actions",
            "action_values",
            "purchase_roas",
            "video_p25_watched_actions",
            "video_thruplay_watched_actions",
            "inline_link_clicks",
            "ctr",
        ]),
        "sort": "spend:descending",
        "limit": limit,
    }
    response = requests.get(url, params=params)
    if not response.ok:
        try:
            error_detail = response.json()
        except Exception:
            error_detail = response.text
        raise ValueError(f"Meta API {response.status_code}: {error_detail}")
    return response.json().get("data", [])


def _extract_action(items: list, action_type: str) -> float:
    for item in items or []:
        if item.get("action_type") == action_type:
            return float(item.get("value", 0))
    return 0.0


def _extract_video_p25(video_p25: list) -> float:
    """Extrai total de views que chegaram a 25% do vídeo."""
    if not video_p25:
        return 0.0
    # A API retorna uma lista; somamos todos os action_types presentes
    return sum(float(item.get("value", 0)) for item in video_p25)


def calculate_metrics(ad: dict) -> dict:
    """Calcula COMPRAS, CAC, ROI, ROAS e Hook Rate a partir dos dados brutos."""
    spend = float(ad.get("spend", 0) or 0)
    impressions = int(ad.get("impressions", 0) or 0)
    reach = int(ad.get("reach", 0) or 0)
    ctr = float(ad.get("ctr", 0) or 0)
    clicks = int(ad.get("inline_link_clicks", 0) or 0)

    actions = ad.get("actions", [])
    action_values = ad.get("action_values", [])

    purchases = _extract_action(actions, "offsite_conversion.fb_pixel_purchase")
    purchase_value = _extract_action(action_values, "offsite_conversion.fb_pixel_purchase")

    # CAC = investimento / compras
    cac = round(spend / purchases, 2) if purchases > 0 else None

    # ROI = (receita - investimento) / investimento * 100
    roi = round(((purchase_value - spend) / spend) * 100, 2) if spend > 0 and purchase_value > 0 else None

    # ROAS direto da API Meta
    roas_list = ad.get("purchase_roas") or []
    roas = round(float(roas_list[0].get("value", 0)), 2) if roas_list else None

    # Hook Rate = (views chegando a 25% do vídeo / impressões) * 100
    p25_views = _extract_video_p25(ad.get("video_p25_watched_actions"))
    hook_rate = round((p25_views / impressions) * 100, 2) if impressions > 0 and p25_views > 0 else None

    return {
        "spend": spend,
        "impressions": impressions,
        "reach": reach,
        "purchases": purchases,
        "purchase_value": purchase_value,
        "cac": cac,
        "roi": roi,
        "roas": roas,
        "hook_rate": hook_rate,
        "ctr": ctr,
        "clicks": clicks,
    }


def classify_format(ad_name: str) -> str:
    """Classifica o formato do criativo com base em palavras-chave no nome."""
    name_lower = ad_name.lower()
    for fmt, keywords in FORMAT_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return fmt
    return "OUTROS"


def _build_summary_lines(creatives: list[dict]) -> list[str]:
    lines = []
    for i, c in enumerate(creatives, 1):
        m = c["metrics"]
        cac_str = f"R${m['cac']}" if m["cac"] is not None else "N/A"
        roi_str = f"{m['roi']}%" if m["roi"] is not None else "N/A"
        roas_str = str(m["roas"]) if m["roas"] is not None else "N/A"
        hook_str = f"{m['hook_rate']}%" if m["hook_rate"] is not None else "N/A"
        lines.append(
            f"{i}. [{c['format']}] {c['ad_name']}\n"
            f"   Compras: {m['purchases']:.0f} | Spend: R${m['spend']:.2f} | "
            f"Receita: R${m['purchase_value']:.2f} | CAC: {cac_str} | "
            f"ROI: {roi_str} | ROAS: {roas_str} | Hook Rate: {hook_str} | CTR: {m['ctr']:.2f}%"
        )
    return lines


def generate_ai_insights(creatives: list[dict], since: str, until: str) -> None:
    """Usa Claude Opus 4.6 com adaptive thinking para gerar análise e sugestões."""
    client = anthropic.Anthropic()

    summary = "\n".join(_build_summary_lines(creatives))
    month_label = date.fromisoformat(since).strftime("%B/%Y")

    prompt = f"""Você é um especialista sênior em Growth Marketing e Media Buying para e-commerce brasileiro.

Analise os TOP {len(creatives)} criativos campeões de {month_label} ({since} a {until}) e entregue um relatório completo:

## 1. RESUMO EXECUTIVO
Quais padrões explicam a performance destes criativos? O que eles têm em comum?

## 2. ANÁLISE POR FORMATO
Para cada formato presente (BEST-SELLER, ACAO_PROMOCIONAL, LANCAMENTO, OUTROS):
- Como o formato performou em média (CAC, ROI, ROAS)?
- O que funcionou bem?
- O que pode ser melhorado?

## 3. DESTAQUES DE MÉTRICAS
- **Melhor CAC**: qual criativo, por que é eficiente e o que podemos aprender?
- **Melhor ROI**: qual criativo e qual estratégia gerou esse resultado?
- **Melhor Hook Rate**: o que capturou a atenção do público?
- **Melhor ROAS**: qual a estratégia por trás desse retorno?

## 4. TOP 5 CRIATIVOS — O QUE PERFORMOU MELHOR
Liste os 5 melhores com análise detalhada de por que dominaram.

## 5. O QUE PODERIA MELHORAR
5 sugestões concretas e acionáveis baseadas nos dados.

## 6. RECOMENDAÇÕES PARA O PRÓXIMO MÊS
O que replicar, o que escalar, o que testar e o que descontinuar.

---
DADOS DOS CRIATIVOS:

{summary}
"""

    print("\n" + "=" * 70)
    print("  ANÁLISE DE IA — CLAUDE OPUS 4.6 (Adaptive Thinking)")
    print("=" * 70 + "\n")

    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
    print("\n")


def print_table(creatives: list[dict]) -> None:
    """Imprime tabela com métricas de cada criativo."""
    header = (
        f"{'#':<4} {'FORMATO':<18} {'COMPRAS':>8} {'SPEND':>11} "
        f"{'CAC':>9} {'ROI':>8} {'ROAS':>6} {'HOOK%':>7} {'CTR%':>6}  CRIATIVO"
    )
    print(header)
    print("-" * (len(header) + 20))

    for i, c in enumerate(creatives, 1):
        m = c["metrics"]
        print(
            f"{i:<4} {c['format']:<18} "
            f"{m['purchases']:>8.0f} "
            f"{'R$'+str(round(m['spend'])):<11} "
            f"{'R$'+str(m['cac']) if m['cac'] else 'N/A':>9} "
            f"{str(m['roi'])+'%' if m['roi'] else 'N/A':>8} "
            f"{str(m['roas']) if m['roas'] else 'N/A':>6} "
            f"{str(m['hook_rate'])+'%' if m['hook_rate'] else 'N/A':>7} "
            f"{m['ctr']:>6.2f}%  "
            f"{c['ad_name'][:55]}"
        )


def run(ad_account_id: str = None, since: str = None, until: str = None, limit: int = 40) -> None:
    """Ponto de entrada principal."""
    account_id = ad_account_id or AD_ACCOUNT_ID
    if not account_id:
        raise ValueError("META_AD_ACCOUNT_ID não configurado. Defina no .env ou passe como parâmetro.")

    if not since or not until:
        since, until = get_previous_month_range()

    print(f"\n{'='*70}")
    print(f"  TOP {limit} CRIATIVOS CAMPEÕES — {since} a {until}")
    print(f"  Conta: {account_id}")
    print(f"{'='*70}\n")

    print(f"Buscando top {limit} criativos por compras...")
    try:
        raw_ads = get_top_creatives(account_id, since, until, limit=limit)
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        print(f"Erro Meta API {e.response.status_code}: {body}")
        raise

    if not raw_ads:
        print("Nenhum criativo encontrado para o período.")
        return

    creatives = []
    for ad in raw_ads:
        ad_name = ad.get("ad_name") or ad.get("ad_id", "unknown")
        creatives.append({
            "ad_id": ad.get("ad_id"),
            "ad_name": ad_name,
            "format": classify_format(ad_name),
            "metrics": calculate_metrics(ad),
        })

    # Distribuição por formato
    formats: dict[str, int] = {}
    for c in creatives:
        formats[c["format"]] = formats.get(c["format"], 0) + 1

    print("DISTRIBUIÇÃO POR FORMATO:")
    for fmt, count in sorted(formats.items(), key=lambda x: -x[1]):
        bar = "█" * count
        print(f"  {fmt:<20} {count:>3} criativos  {bar}")
    print()

    print_table(creatives)

    generate_ai_insights(creatives, since, until)


if __name__ == "__main__":
    run()
