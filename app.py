"""Dashboard web para análise de criativos campeões — Growth Marketing."""
import os
import json
from datetime import date, timedelta

import requests
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

from creative_champions import (
    get_top_creatives,
    calculate_metrics,
    classify_format,
    get_previous_month_range,
    _avg,
)

load_dotenv()

app = Flask(__name__)

ACCOUNTS = {
    "act_568162184127732": "Conta 1",
    "act_670061628880862": "Conta 2",
    "act_979740244075964": "Conta 3",
}


def build_creatives(ad_account_id: str, since: str, until: str, limit: int = 40):
    raw_ads = get_top_creatives(ad_account_id, since, until, limit=limit)
    creatives = []
    for ad in raw_ads:
        ad_name = ad.get("ad_name") or ad.get("ad_id", "unknown")
        creatives.append({
            "ad_id": ad.get("ad_id"),
            "ad_name": ad_name,
            "format": classify_format(ad_name),
            "metrics": calculate_metrics(ad),
        })
    return creatives


def build_analysis(creatives: list[dict]):
    total_spend = sum(c["metrics"]["spend"] for c in creatives)
    total_revenue = sum(c["metrics"]["purchase_value"] for c in creatives)
    total_purchases = sum(c["metrics"]["purchases"] for c in creatives)
    overall_cac = round(total_spend / total_purchases, 2) if total_purchases > 0 else None
    overall_roi = round(((total_revenue - total_spend) / total_spend) * 100, 2) if total_spend > 0 and total_revenue > 0 else None

    # Por formato
    formats_map: dict[str, list] = {}
    for c in creatives:
        formats_map.setdefault(c["format"], []).append(c)

    formats_analysis = []
    for fmt, items in sorted(formats_map.items(), key=lambda x: -len(x[1])):
        m_list = [c["metrics"] for c in items]
        fmt_spend = sum(m["spend"] for m in m_list)
        fmt_revenue = sum(m["purchase_value"] for m in m_list)
        avg_roi = _avg([m["roi"] for m in m_list])
        formats_analysis.append({
            "name": fmt,
            "count": len(items),
            "purchases": sum(m["purchases"] for m in m_list),
            "spend": fmt_spend,
            "revenue": fmt_revenue,
            "avg_cac": _avg([m["cac"] for m in m_list]),
            "avg_roi": avg_roi,
            "avg_roas": _avg([m["roas"] for m in m_list]),
            "avg_hook": _avg([m["hook_rate"] for m in m_list]),
            "avg_ctr": _avg([m["ctr"] for m in m_list]),
            "roi_status": "excellent" if avg_roi and avg_roi >= 200 else ("good" if avg_roi and avg_roi >= 50 else "low"),
        })

    # Destaques
    def best(key, reverse=False):
        filtered = [c for c in creatives if c["metrics"].get(key) is not None]
        if not filtered:
            return None
        return sorted(filtered, key=lambda c: c["metrics"][key], reverse=not reverse)[0]

    best_cac = best("cac", reverse=True)
    best_roi = best("roi")
    best_hook = best("hook_rate")
    best_roas = best("roas")

    # Sugestões
    suggestions = []
    high_cac = [c for c in creatives if c["metrics"]["cac"] and overall_cac and c["metrics"]["cac"] > overall_cac * 1.3]
    low_hook = [c for c in creatives if c["metrics"]["hook_rate"] is not None and c["metrics"]["hook_rate"] < 20]
    low_ctr = [c for c in creatives if c["metrics"]["ctr"] < 1.0]
    no_hook = [c for c in creatives if c["metrics"]["hook_rate"] is None]

    if high_cac:
        suggestions.append({"type": "warning", "text": f"{len(high_cac)} criativos com CAC 30%+ acima da média. Revisar segmentação ou oferta."})
    if low_hook:
        suggestions.append({"type": "warning", "text": f"{len(low_hook)} criativos com Hook Rate < 20%. Melhorar os primeiros 3 segundos do vídeo."})
    if low_ctr:
        suggestions.append({"type": "warning", "text": f"{len(low_ctr)} criativos com CTR < 1%. Revisar CTA, thumbnail ou copy."})
    if no_hook:
        suggestions.append({"type": "info", "text": f"{len(no_hook)} criativos sem Hook Rate (imagens estáticas). Testar versão em vídeo."})

    for fmt_data in formats_analysis:
        if fmt_data["spend"] > 0 and fmt_data["revenue"] < fmt_data["spend"]:
            suggestions.append({"type": "danger", "text": f"Formato [{fmt_data['name']}] com ROI negativo. Considerar pausar ou reformular."})

    # Melhor formato
    best_fmt = max(formats_analysis, key=lambda x: x["avg_roi"] or -999, default=None)

    # Scale candidates
    scale_candidates = [c for c in creatives if c["metrics"]["roi"] and c["metrics"]["roi"] >= 150 and c["metrics"]["purchases"] >= 10]

    return {
        "summary": {
            "total": len(creatives),
            "with_purchases": len([c for c in creatives if c["metrics"]["purchases"] > 0]),
            "total_spend": total_spend,
            "total_revenue": total_revenue,
            "total_purchases": total_purchases,
            "overall_cac": overall_cac,
            "overall_roi": overall_roi,
        },
        "formats": formats_analysis,
        "highlights": {
            "best_cac": {"name": best_cac["ad_name"][:55], "value": best_cac["metrics"]["cac"], "format": best_cac["format"]} if best_cac else None,
            "best_roi": {"name": best_roi["ad_name"][:55], "value": best_roi["metrics"]["roi"], "format": best_roi["format"]} if best_roi else None,
            "best_hook": {"name": best_hook["ad_name"][:55], "value": best_hook["metrics"]["hook_rate"], "format": best_hook["format"]} if best_hook else None,
            "best_roas": {"name": best_roas["ad_name"][:55], "value": best_roas["metrics"]["roas"], "format": best_roas["format"]} if best_roas else None,
        },
        "suggestions": suggestions,
        "best_format": best_fmt["name"] if best_fmt else None,
        "scale_candidates": [{"name": c["ad_name"][:55], "roi": c["metrics"]["roi"], "format": c["format"]} for c in scale_candidates[:3]],
    }


@app.route("/")
def index():
    since, until = get_previous_month_range()
    return render_template("dashboard.html", accounts=ACCOUNTS, default_since=since, default_until=until)


@app.route("/api/creatives")
def api_creatives():
    account_id = request.args.get("account_id", list(ACCOUNTS.keys())[0])
    since = request.args.get("since")
    until = request.args.get("until")
    if not since or not until:
        since, until = get_previous_month_range()

    try:
        creatives = build_creatives(account_id, since, until)
        analysis = build_analysis(creatives)
        return jsonify({
            "ok": True,
            "creatives": creatives,
            "analysis": analysis,
            "since": since,
            "until": until,
            "account_id": account_id,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
