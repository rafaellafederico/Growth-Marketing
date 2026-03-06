import os
import json
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

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
        "sort": ["spend_descending"],
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


def _fmt_brl(value: float | None) -> str:
    return f"R${value:.2f}" if value is not None else "N/A"


def _fmt_pct(value: float | None) -> str:
    return f"{value:.2f}%" if value is not None else "N/A"


def _avg(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def generate_ai_insights(creatives: list[dict], since: str, until: str) -> None:
    """Gera análise completa de criativos com motor local — sem API externa."""
    month_label = date.fromisoformat(since).strftime("%B/%Y")

    print("\n" + "=" * 70)
    print(f"  ANÁLISE DE CRIATIVOS CAMPEÕES — {month_label}")
    print("=" * 70)

    # ── 1. RESUMO EXECUTIVO ───────────────────────────────────────────────
    total = len(creatives)
    with_purchases = [c for c in creatives if c["metrics"]["purchases"] > 0]
    total_spend = sum(c["metrics"]["spend"] for c in creatives)
    total_revenue = sum(c["metrics"]["purchase_value"] for c in creatives)
    total_purchases = sum(c["metrics"]["purchases"] for c in creatives)
    overall_cac = round(total_spend / total_purchases, 2) if total_purchases > 0 else None
    overall_roi = round(((total_revenue - total_spend) / total_spend) * 100, 2) if total_spend > 0 and total_revenue > 0 else None

    print(f"\n{'─'*70}")
    print("  1. RESUMO EXECUTIVO")
    print(f"{'─'*70}")
    print(f"  Período analisado : {since} → {until}")
    print(f"  Total criativos   : {total}")
    print(f"  Com compras       : {len(with_purchases)} ({round(len(with_purchases)/total*100)}%)")
    print(f"  Investimento total: {_fmt_brl(total_spend)}")
    print(f"  Receita total     : {_fmt_brl(total_revenue)}")
    print(f"  Compras totais    : {total_purchases:.0f}")
    print(f"  CAC médio geral   : {_fmt_brl(overall_cac)}")
    print(f"  ROI geral         : {_fmt_pct(overall_roi)}")

    # ── 2. ANÁLISE POR FORMATO ────────────────────────────────────────────
    print(f"\n{'─'*70}")
    print("  2. ANÁLISE POR FORMATO")
    print(f"{'─'*70}")

    formats_map: dict[str, list[dict]] = {}
    for c in creatives:
        fmt = c["format"]
        formats_map.setdefault(fmt, []).append(c)

    for fmt, items in sorted(formats_map.items(), key=lambda x: -len(x[1])):
        m_list = [c["metrics"] for c in items]
        avg_cac = _avg([m["cac"] for m in m_list])
        avg_roi = _avg([m["roi"] for m in m_list])
        avg_roas = _avg([m["roas"] for m in m_list])
        avg_hook = _avg([m["hook_rate"] for m in m_list])
        avg_ctr = _avg([m["ctr"] for m in m_list])
        fmt_purchases = sum(m["purchases"] for m in m_list)
        fmt_spend = sum(m["spend"] for m in m_list)

        print(f"\n  [{fmt}]  {len(items)} criativos")
        print(f"    Compras totais : {fmt_purchases:.0f}   |  Investimento: {_fmt_brl(fmt_spend)}")
        print(f"    CAC médio      : {_fmt_brl(avg_cac)}   |  ROI médio: {_fmt_pct(avg_roi)}")
        print(f"    ROAS médio     : {avg_roas if avg_roas else 'N/A'}   |  Hook Rate médio: {_fmt_pct(avg_hook)}   |  CTR médio: {_fmt_pct(avg_ctr)}")

        # Diagnóstico automático
        if avg_roi is not None:
            if avg_roi >= 200:
                print(f"    ✔  ROI excelente — formato altamente rentável.")
            elif avg_roi >= 50:
                print(f"    ✔  ROI positivo — formato saudável, há espaço para escalar.")
            else:
                print(f"    ⚠  ROI baixo — revisar oferta ou público deste formato.")
        if avg_hook is not None:
            if avg_hook >= 40:
                print(f"    ✔  Hook Rate forte — criativos prendem atenção logo no início.")
            elif avg_hook >= 20:
                print(f"    ~  Hook Rate moderado — testar variações de abertura.")
            else:
                print(f"    ⚠  Hook Rate fraco — primeiros 3 segundos precisam de melhoria.")

    # ── 3. DESTAQUES DE MÉTRICAS ──────────────────────────────────────────
    print(f"\n{'─'*70}")
    print("  3. DESTAQUES DE MÉTRICAS")
    print(f"{'─'*70}")

    def _best(creatives, key, reverse=False):
        filtered = [c for c in creatives if c["metrics"].get(key) is not None]
        if not filtered:
            return None
        return sorted(filtered, key=lambda c: c["metrics"][key], reverse=not reverse)[0]

    best_cac = _best(creatives, "cac", reverse=True)   # menor CAC = melhor
    best_roi = _best(creatives, "roi")
    best_hook = _best(creatives, "hook_rate")
    best_roas = _best(creatives, "roas")
    best_purchases = _best(creatives, "purchases")

    highlights = [
        ("Melhor CAC (menor custo por compra)", best_cac, "cac", _fmt_brl),
        ("Melhor ROI", best_roi, "roi", _fmt_pct),
        ("Melhor Hook Rate", best_hook, "hook_rate", _fmt_pct),
        ("Melhor ROAS", best_roas, "roas", lambda v: str(v) if v else "N/A"),
        ("Mais Compras", best_purchases, "purchases", lambda v: f"{v:.0f}" if v else "N/A"),
    ]

    for label, c, key, fmt_fn in highlights:
        if c:
            val = fmt_fn(c["metrics"][key])
            name = c["ad_name"][:55]
            print(f"\n  {label}: {val}")
            print(f"    → {name}  [{c['format']}]")

    # ── 4. TOP 5 CRIATIVOS ────────────────────────────────────────────────
    print(f"\n{'─'*70}")
    print("  4. TOP 5 CRIATIVOS — O QUE MAIS PERFORMOU")
    print(f"{'─'*70}")

    # Ordena por compras (principal métrica de resultado)
    top5 = sorted(creatives, key=lambda c: c["metrics"]["purchases"], reverse=True)[:5]
    for i, c in enumerate(top5, 1):
        m = c["metrics"]
        print(f"\n  #{i} [{c['format']}] {c['ad_name'][:60]}")
        print(f"      Compras: {m['purchases']:.0f}  |  CAC: {_fmt_brl(m['cac'])}  |  ROI: {_fmt_pct(m['roi'])}  |  ROAS: {m['roas'] if m['roas'] else 'N/A'}")
        print(f"      Hook Rate: {_fmt_pct(m['hook_rate'])}  |  CTR: {_fmt_pct(m['ctr'])}  |  Spend: {_fmt_brl(m['spend'])}")

        # Por que performou
        reasons = []
        if m["cac"] and overall_cac and m["cac"] < overall_cac * 0.8:
            reasons.append("CAC abaixo da média (eficiente em custo)")
        if m["roi"] and m["roi"] >= 100:
            reasons.append(f"ROI de {_fmt_pct(m['roi'])} — alta rentabilidade")
        if m["hook_rate"] and m["hook_rate"] >= 35:
            reasons.append("Hook Rate alto — criativo prende atenção")
        if m["ctr"] and m["ctr"] >= 2.0:
            reasons.append("CTR forte — anúncio gera cliques qualificados")
        if reasons:
            print(f"      Por que performou: {' | '.join(reasons)}")

    # ── 5. O QUE PODERIA MELHORAR ─────────────────────────────────────────
    print(f"\n{'─'*70}")
    print("  5. O QUE PODERIA MELHORAR")
    print(f"{'─'*70}")

    suggestions = []

    # CAC acima da média
    high_cac = [c for c in creatives if c["metrics"]["cac"] and overall_cac and c["metrics"]["cac"] > overall_cac * 1.3]
    if high_cac:
        suggestions.append(
            f"  {len(high_cac)} criativos com CAC 30%+ acima da média ({_fmt_brl(overall_cac)}). "
            "Revisar segmentação de público ou oferta nesses anúncios."
        )

    # Hook Rate baixo
    low_hook = [c for c in creatives if c["metrics"]["hook_rate"] is not None and c["metrics"]["hook_rate"] < 20]
    if low_hook:
        suggestions.append(
            f"  {len(low_hook)} criativos com Hook Rate < 20%. "
            "Testar abertura mais direta: mostrar o produto ou resultado nos primeiros 3 segundos."
        )

    # CTR baixo
    low_ctr = [c for c in creatives if c["metrics"]["ctr"] < 1.0]
    if low_ctr:
        suggestions.append(
            f"  {len(low_ctr)} criativos com CTR < 1%. "
            "Revisar CTA, thumbnail ou copy do anúncio — o criativo não está convertendo visualização em clique."
        )

    # Sem hook rate (provavelmente estático/imagem)
    no_hook = [c for c in creatives if c["metrics"]["hook_rate"] is None]
    if no_hook:
        suggestions.append(
            f"  {len(no_hook)} criativos sem Hook Rate (provavelmente imagens estáticas). "
            "Testar versões em vídeo desses criativos — vídeos tendem a ter melhor Hook e CTR."
        )

    # Formato com ROI negativo
    for fmt, items in formats_map.items():
        fmt_spend = sum(c["metrics"]["spend"] for c in items)
        fmt_revenue = sum(c["metrics"]["purchase_value"] for c in items)
        if fmt_spend > 0 and fmt_revenue < fmt_spend:
            suggestions.append(
                f"  Formato [{fmt}] está com ROI negativo ({_fmt_brl(fmt_revenue)} receita vs {_fmt_brl(fmt_spend)} gasto). "
                "Considerar pausar ou reformular a abordagem deste formato."
            )

    if not suggestions:
        suggestions.append("  Todos os criativos apresentam métricas dentro do esperado. Continue monitorando tendências mês a mês.")

    for s in suggestions:
        print(s)

    # ── 6. RECOMENDAÇÕES PARA O PRÓXIMO MÊS ──────────────────────────────
    print(f"\n{'─'*70}")
    print("  6. RECOMENDAÇÕES PARA O PRÓXIMO MÊS")
    print(f"{'─'*70}")

    # Melhor formato por ROI
    best_fmt_roi = None
    best_fmt_roi_val = None
    for fmt, items in formats_map.items():
        rois = [c["metrics"]["roi"] for c in items if c["metrics"]["roi"] is not None]
        if rois:
            avg = sum(rois) / len(rois)
            if best_fmt_roi_val is None or avg > best_fmt_roi_val:
                best_fmt_roi = fmt
                best_fmt_roi_val = avg

    print(f"\n  REPLICAR:")
    if best_fmt_roi:
        print(f"    • Formato [{best_fmt_roi}] teve o melhor ROI médio ({_fmt_pct(best_fmt_roi_val)}) — aumentar volume de produção deste tipo.")
    if best_hook:
        print(f"    • Estrutura de abertura do criativo '{best_hook['ad_name'][:45]}' — Hook Rate {_fmt_pct(best_hook['metrics']['hook_rate'])}.")

    print(f"\n  ESCALAR (aumentar budget):")
    scale_candidates = [c for c in creatives if c["metrics"]["roi"] and c["metrics"]["roi"] >= 150 and c["metrics"]["purchases"] >= 10]
    if scale_candidates:
        for c in scale_candidates[:3]:
            print(f"    • {c['ad_name'][:55]}  [{c['format']}]  ROI: {_fmt_pct(c['metrics']['roi'])}")
    else:
        print("    • Identificar criativos com ROI > 150% e aumentar budget gradualmente (+20% por semana).")

    print(f"\n  TESTAR:")
    print(f"    • Variações de copy nos top 5 criativos (manter visual, mudar headline).")
    print(f"    • Formatos ausentes ou com poucos criativos no mix — diversificar.")
    if low_hook:
        print(f"    • Abertura em vídeo para os {len(low_hook)} criativos com Hook Rate fraco.")

    print(f"\n  DESCONTINUAR:")
    if high_cac:
        print(f"    • {len(high_cac)} criativos com CAC muito acima da média — pausar se não melhorarem em 7 dias.")
    else:
        print(f"    • Monitorar criativos com CAC crescente semana a semana — pausar antes de sangrar budget.")

    print(f"\n{'='*70}\n")


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
