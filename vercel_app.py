"""Vercel production engagement mapping app.

The full Mapsurvey app uses GeoDjango and requires native GDAL libraries that
Vercel's Python runtime does not provide. This WSGI app provides the production
public engagement input tool on Vercel and stores submissions in Supabase.
"""

import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


BASE_DIR = Path(__file__).resolve().parent
MAPBOX_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
AI_GATEWAY_API_KEY = os.environ.get("AI_GATEWAY_API_KEY", "")
AI_GATEWAY_MODEL = os.environ.get("AI_GATEWAY_MODEL", "openai/gpt-5.2")
PIN_COLUMNS = "id,created_at,category,title,note,lng,lat,photo_data_url,status"


def _response(start_response, status, body, content_type="text/html; charset=utf-8"):
    payload = body.encode("utf-8") if isinstance(body, str) else body
    start_response(status, [
        ("Content-Type", content_type),
        ("Content-Length", str(len(payload))),
        ("Cache-Control", "public, max-age=60"),
    ])
    return [payload]


def _json_response(start_response, status, data):
    return _response(
        start_response,
        status,
        json.dumps(data, separators=(",", ":")),
        "application/json; charset=utf-8",
    )


def _read_json(environ):
    try:
        size = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        size = 0
    raw = environ["wsgi.input"].read(size) if size else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _clean_text(value, max_len):
    return str(value or "").strip()[:max_len]


def _clean_pin_payload(payload, require_location=True):
    cleaned = {
        "category": _clean_text(payload.get("category"), 80),
        "title": _clean_text(payload.get("title"), 120),
        "note": _clean_text(payload.get("note"), 1000),
        "photo_data_url": _clean_text(payload.get("photo_data_url") or payload.get("photo"), 750000),
        "client_id": _clean_text(payload.get("client_id"), 80),
        "source": "sdbike-vercel",
        "status": "active",
    }
    if require_location:
        try:
            cleaned["lng"] = float(payload.get("lng"))
            cleaned["lat"] = float(payload.get("lat"))
        except (TypeError, ValueError):
            raise ValueError("A valid map location is required.")
        if not (-118.2 <= cleaned["lng"] <= -116.0 and 32.3 <= cleaned["lat"] <= 33.6):
            raise ValueError("The pin must be in the San Diego County region.")
    elif "lng" in payload and "lat" in payload:
        try:
            cleaned["lng"] = float(payload.get("lng"))
            cleaned["lat"] = float(payload.get("lat"))
        except (TypeError, ValueError):
            pass

    if not cleaned["client_id"]:
        raise ValueError("A contributor id is required.")
    if not cleaned["category"]:
        raise ValueError("A category is required.")
    if not cleaned["title"]:
        cleaned["title"] = cleaned["category"]
    return {key: value for key, value in cleaned.items() if value not in ("", None)}


def _supabase_request(method, path, body=None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase is not configured.")

    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    request = Request(f"{SUPABASE_URL}/rest/v1/{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Supabase request failed: {exc.code} {detail[:240]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Supabase request failed: {exc.reason}") from exc


def _public_pin(pin):
    return {
        "id": pin.get("id"),
        "created_at": pin.get("created_at"),
        "category": pin.get("category"),
        "title": pin.get("title"),
        "note": pin.get("note"),
        "lng": pin.get("lng"),
        "lat": pin.get("lat"),
        "photo": pin.get("photo_data_url") or "",
    }


def _sentiment_for_text(text):
    lower = text.lower()
    negative_terms = [
        "unsafe", "danger", "dangerous", "near miss", "crash", "speed", "fast",
        "blocked", "scary", "stress", "conflict", "poor", "missing", "dark",
        "debris", "narrow", "hard", "avoid",
    ]
    positive_terms = ["safe", "protected", "comfortable", "easy", "better", "calm"]
    score = sum(term in lower for term in positive_terms) - sum(term in lower for term in negative_terms)
    if score <= -2:
        return "negative"
    if score >= 1:
        return "positive"
    return "mixed"


def _keyword_themes(rows):
    themes = {
        "crossing safety": ["cross", "intersection", "turn", "signal", "visibility"],
        "speed and traffic stress": ["speed", "fast", "traffic", "drivers", "cars"],
        "network gaps": ["missing", "gap", "connection", "lane", "route"],
        "maintenance": ["debris", "pavement", "sand", "drainage", "sign", "surface"],
        "lighting and comfort": ["dark", "lighting", "night", "underpass", "comfort"],
        "school and family access": ["school", "family", "kids", "children"],
    }
    text = " ".join(f"{row.get('category', '')} {row.get('title', '')} {row.get('note', '')}".lower() for row in rows)
    scored = []
    for theme, terms in themes.items():
        count = sum(text.count(term) for term in terms)
        if count:
            scored.append({"theme": theme, "mentions": count})
    return sorted(scored, key=lambda item: item["mentions"], reverse=True)[:5]


def _fallback_insights(rows):
    total = len(rows)
    category_counts = {}
    sentiment_counts = {"negative": 0, "mixed": 0, "positive": 0}
    for row in rows:
        category = row.get("category") or "Uncategorized"
        category_counts[category] = category_counts.get(category, 0) + 1
        sentiment_counts[_sentiment_for_text(f"{category} {row.get('title', '')} {row.get('note', '')}")] += 1

    top_categories = [
        {"label": label, "count": count}
        for label, count in sorted(category_counts.items(), key=lambda item: item[1], reverse=True)[:6]
    ]
    themes = _keyword_themes(rows)
    lead = "No public comments have been submitted yet."
    if total:
        top = top_categories[0]["label"]
        lead = f"{total} active comments are on the map. The strongest signal is {top.lower()}, with recurring concerns around {themes[0]['theme'] if themes else 'bike access'}."
    actions = []
    if any(item["label"] == "Dangerous crossing" for item in top_categories):
        actions.append("Prioritize crossing audits at clustered intersections and compare comments with crash and near-miss records.")
    if any(item["label"] == "Missing bike connection" for item in top_categories):
        actions.append("Package missing-link comments into corridor gap lists for capital planning discussions.")
    if any(item["label"] == "Maintenance problem" for item in top_categories):
        actions.append("Route maintenance-related comments to the appropriate city or county response channel.")
    if not actions and total:
        actions.append("Review high-detail comments first and group nearby pins into project-ready problem statements.")
    if not actions:
        actions.append("Collect the first round of comments, then refresh insights to surface themes and priorities.")

    return {
        "generated_by": "rules",
        "summary": lead,
        "total": total,
        "sentiment": sentiment_counts,
        "top_categories": top_categories,
        "themes": themes,
        "recommended_actions": actions[:4],
    }


def _ai_insights(rows, fallback):
    if not AI_GATEWAY_API_KEY or not rows:
        return fallback
    compact_rows = [
        {
            "category": row.get("category"),
            "title": row.get("title"),
            "note": row.get("note"),
            "lng": row.get("lng"),
            "lat": row.get("lat"),
        }
        for row in rows[:300]
    ]
    body = {
        "model": AI_GATEWAY_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You analyze public bike engagement comments for a county bicycle coalition. "
                    "Return only compact JSON with keys summary, sentiment, themes, recommended_actions. "
                    "Sentiment values must include negative, mixed, positive counts. Themes must be an array "
                    "of objects with theme and mentions. Recommended actions must be concrete and suitable "
                    "for advocacy or project planning."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"comments": compact_rows, "fallback_counts": fallback}, separators=(",", ":")),
            },
        ],
        "response_format": {"type": "json_object"},
    }
    request = Request(
        "https://ai-gateway.vercel.sh/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {AI_GATEWAY_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            ai = json.loads(content)
            return {
                **fallback,
                "generated_by": "ai",
                "summary": ai.get("summary") or fallback["summary"],
                "sentiment": ai.get("sentiment") or fallback["sentiment"],
                "themes": ai.get("themes") or fallback["themes"],
                "recommended_actions": ai.get("recommended_actions") or fallback["recommended_actions"],
            }
    except Exception:
        return fallback


def _api_insights(start_response):
    try:
        rows = _supabase_request(
            "GET",
            f"sdbike_engagement_pins?select={PIN_COLUMNS}&status=eq.active&order=created_at.desc&limit=1000",
        ) or []
        fallback = _fallback_insights(rows)
        return _json_response(start_response, "200 OK", _ai_insights(rows, fallback))
    except RuntimeError:
        return _json_response(start_response, "502 Bad Gateway", {"error": "The engagement database is temporarily unavailable."})


def _api_pins(environ, start_response, path):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    query = parse_qs(environ.get("QUERY_STRING", ""))

    try:
        if path == "/api/pins" and method == "GET":
            limit = min(max(int(query.get("limit", ["500"])[0]), 1), 1000)
            rows = _supabase_request(
                "GET",
                f"sdbike_engagement_pins?select={PIN_COLUMNS}&status=eq.active&order=created_at.desc&limit={limit}",
            )
            return _json_response(start_response, "200 OK", {"pins": [_public_pin(row) for row in rows or []]})

        if path == "/api/pins" and method == "POST":
            payload = _clean_pin_payload(_read_json(environ), require_location=True)
            rows = _supabase_request("POST", "sdbike_engagement_pins", payload)
            pin = _public_pin((rows or [{}])[0])
            return _json_response(start_response, "201 Created", {"pin": pin})

        if path.startswith("/api/pins/") and method in {"PATCH", "DELETE"}:
            pin_id = path.rsplit("/", 1)[-1]
            payload = _read_json(environ)
            client_id = _clean_text(payload.get("client_id"), 80)
            if not pin_id or not client_id:
                return _json_response(start_response, "400 Bad Request", {"error": "Pin id and contributor id are required."})

            filters = f"id=eq.{quote(pin_id)}&client_id=eq.{quote(client_id)}"
            if method == "DELETE":
                rows = _supabase_request("PATCH", f"sdbike_engagement_pins?{filters}", {"status": "removed"})
                if not rows:
                    return _json_response(start_response, "404 Not Found", {"error": "Pin not found for this contributor."})
                return _json_response(start_response, "200 OK", {"removed": True})

            update = _clean_pin_payload(payload, require_location=False)
            update.pop("client_id", None)
            update.pop("source", None)
            rows = _supabase_request("PATCH", f"sdbike_engagement_pins?{filters}", update)
            if not rows:
                return _json_response(start_response, "404 Not Found", {"error": "Pin not found for this contributor."})
            return _json_response(start_response, "200 OK", {"pin": _public_pin(rows[0])})

        return _json_response(start_response, "405 Method Not Allowed", {"error": "Method not allowed."})
    except ValueError as exc:
        return _json_response(start_response, "400 Bad Request", {"error": str(exc)})
    except (RuntimeError, json.JSONDecodeError):
        return _json_response(start_response, "502 Bad Gateway", {"error": "The engagement database is temporarily unavailable."})


def _file_response(start_response, path):
    if not path.exists() or not path.is_file():
        return _response(start_response, "404 Not Found", "Not found", "text/plain; charset=utf-8")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = path.read_bytes()
    start_response("200 OK", [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "public, max-age=86400"),
    ])
    return [body]


def _layout(title, body):
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="preconnect" href="https://api.mapbox.com">
  <link href="https://api.mapbox.com/mapbox-gl-js/v3.10.0/mapbox-gl.css" rel="stylesheet">
  <style>
    :root {{
      --ink: #17201c;
      --muted: #5b6761;
      --line: #d9e2dc;
      --green: #0c7a4d;
      --blue: #246bb2;
      --yellow: #ffd447;
      --paper: #fbfcfa;
      --soft: #eef5f0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--paper);
    }}
    a {{ color: inherit; }}
    .nav {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 18px clamp(18px, 4vw, 56px);
      border-bottom: 1px solid var(--line);
      background: rgba(251, 252, 250, .94);
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    .brand {{ font-weight: 800; letter-spacing: .02em; }}
    .nav a {{ text-decoration: none; font-weight: 700; color: var(--green); }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(300px, 44vw);
      min-height: 640px;
      border-bottom: 1px solid var(--line);
    }}
    .hero-copy {{
      padding: clamp(42px, 7vw, 96px) clamp(22px, 6vw, 84px);
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 24px;
    }}
    .eyebrow {{ color: var(--blue); font-weight: 800; text-transform: uppercase; font-size: 13px; letter-spacing: .08em; }}
    h1 {{ font-size: clamp(38px, 7vw, 78px); line-height: .94; margin: 0; letter-spacing: 0; max-width: 820px; }}
    .lead {{ font-size: clamp(18px, 2.2vw, 23px); line-height: 1.45; color: var(--muted); max-width: 680px; margin: 0; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 12px; }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 48px;
      padding: 0 20px;
      border-radius: 8px;
      border: 2px solid var(--ink);
      background: var(--yellow);
      color: var(--ink);
      text-decoration: none;
      font-weight: 800;
    }}
    .button.secondary {{ background: transparent; border-color: var(--line); color: var(--green); }}
    .hero-image {{
      min-height: 420px;
      background:
        linear-gradient(180deg, rgba(12,122,77,.08), rgba(23,32,28,.18)),
        url("/staticfiles/survey/assets/img/demo/sd-bike-bus.webp") center / cover;
    }}
    .band {{ padding: 34px clamp(18px, 4vw, 56px); background: var(--soft); border-bottom: 1px solid var(--line); }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; max-width: 1180px; margin: 0 auto; }}
    .metric {{ border-left: 4px solid var(--green); padding: 10px 14px; background: white; min-height: 92px; }}
    .metric strong {{ display: block; font-size: 30px; }}
    .metric span {{ color: var(--muted); font-weight: 700; }}
    .workspace {{ min-height: calc(100vh - 70px); display: grid; grid-template-columns: 380px minmax(0, 1fr); }}
    .panel {{ padding: 24px; border-right: 1px solid var(--line); background: white; overflow: auto; }}
    .panel h1 {{ font-size: 32px; line-height: 1.05; margin-bottom: 12px; }}
    .wizard-top {{ display: flex; justify-content: space-between; align-items: center; gap: 14px; margin: 12px 0 18px; }}
    .progress {{ flex: 1; height: 8px; background: var(--soft); border-radius: 8px; overflow: hidden; }}
    .progress span {{ display: block; height: 100%; width: 33.333%; background: var(--green); transition: width .2s ease; }}
    .count {{ color: var(--muted); font-weight: 800; font-size: 13px; white-space: nowrap; }}
    .screen {{ display: none; }}
    .screen.active {{ display: block; }}
    .step {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin: 12px 0; background: var(--paper); }}
    .step strong {{ display: block; margin-bottom: 5px; }}
    .choice-list {{ display: grid; gap: 10px; margin: 14px 0; }}
    .choice {{
      width: 100%;
      text-align: left;
      border: 1px solid var(--line);
      background: white;
      border-radius: 8px;
      padding: 13px 14px;
      cursor: pointer;
      font-weight: 800;
      color: var(--ink);
    }}
    .choice span {{ display: block; margin-top: 4px; color: var(--muted); font-weight: 600; line-height: 1.35; }}
    .choice.selected {{ border-color: var(--green); box-shadow: inset 0 0 0 2px var(--green); }}
    .field {{ display: grid; gap: 7px; margin: 13px 0; }}
    .field label {{ font-weight: 800; }}
    textarea, input[type="text"], input[type="file"], select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 11px;
      font: inherit;
      color: var(--ink);
      background: white;
    }}
    select {{ min-height: 44px; }}
    textarea {{ min-height: 112px; resize: vertical; }}
    .row {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .row .button {{ flex: 1; min-width: 128px; }}
    .button.danger {{ background: #d93636; color: white; border-color: #d93636; }}
    .button.ghost {{ background: white; border-color: var(--line); color: var(--ink); }}
    .photo-preview {{ display: none; width: 100%; max-height: 150px; object-fit: cover; border-radius: 8px; border: 1px solid var(--line); }}
    .pin-list {{ display: grid; gap: 10px; margin-top: 14px; }}
    .pin-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--paper); }}
    .pin-card strong {{ display: block; margin-bottom: 4px; }}
    .pin-card p {{ color: var(--muted); margin: 0 0 8px; line-height: 1.35; }}
    .pin-card img {{ width: 100%; max-height: 120px; object-fit: cover; border-radius: 8px; margin: 4px 0 10px; }}
    .pin-actions {{ display: flex; gap: 8px; }}
    .small-button {{ border: 1px solid var(--line); background: white; border-radius: 8px; padding: 7px 10px; cursor: pointer; font-weight: 800; }}
    .small-button.danger {{ color: #b42323; }}
    .status-pill {{ display: inline-flex; padding: 5px 8px; border-radius: 8px; background: var(--soft); color: var(--green); font-weight: 800; font-size: 12px; margin-bottom: 10px; }}
    .insights {{ margin-top: 18px; border-top: 1px solid var(--line); padding-top: 16px; }}
    .insights h2 {{ margin: 0 0 8px; font-size: 22px; line-height: 1.1; }}
    .insight-summary {{ color: var(--muted); line-height: 1.4; margin: 0 0 12px; }}
    .insight-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 10px 0; }}
    .insight-stat {{ background: var(--soft); border-radius: 8px; padding: 9px; }}
    .insight-stat strong {{ display: block; font-size: 20px; }}
    .insight-list {{ display: grid; gap: 8px; margin: 10px 0; }}
    .insight-item {{ border: 1px solid var(--line); border-radius: 8px; padding: 9px; background: white; font-weight: 700; }}
    .insight-item span {{ display: block; color: var(--muted); font-weight: 600; margin-top: 3px; }}
    .map-wrap {{ position: relative; min-height: 720px; }}
    #map {{ position: absolute; inset: 0; background: #d9e9e4; }}
    .fallback-map {{
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, transparent 48%, rgba(36,107,178,.32) 49%, rgba(36,107,178,.32) 52%, transparent 53%),
        linear-gradient(24deg, transparent 45%, rgba(12,122,77,.28) 46%, rgba(12,122,77,.28) 49%, transparent 50%),
        linear-gradient(150deg, transparent 50%, rgba(255,212,71,.45) 51%, rgba(255,212,71,.45) 53%, transparent 54%),
        #dcefe8;
    }}
    .map-note {{
      position: absolute;
      left: 18px;
      bottom: 18px;
      right: 18px;
      max-width: 560px;
      background: rgba(255,255,255,.94);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
      font-weight: 700;
      z-index: 2;
    }}
    .pin {{
      position: absolute;
      width: 22px;
      height: 22px;
      border-radius: 50% 50% 50% 0;
      background: #d93636;
      border: 2px solid white;
      transform: rotate(-45deg);
      box-shadow: 0 4px 12px rgba(0,0,0,.25);
    }}
    .pin::after {{ content: ""; position: absolute; inset: 5px; border-radius: 50%; background: white; }}
    .mapboxgl-popup-content {{ border-radius: 8px; padding: 12px; max-width: 260px; }}
    .popup-title {{ font-weight: 800; margin-bottom: 4px; }}
    .popup-note {{ color: var(--muted); margin-bottom: 8px; }}
    .popup-photo {{ width: 220px; max-height: 120px; object-fit: cover; border-radius: 8px; display: block; }}
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(23, 32, 28, .42);
      z-index: 30;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 18px;
    }}
    .modal-backdrop.open {{ display: flex; }}
    .modal {{
      width: min(560px, 100%);
      max-height: calc(100vh - 36px);
      overflow: auto;
      background: white;
      border-radius: 8px;
      border: 1px solid var(--line);
      box-shadow: 0 18px 60px rgba(0,0,0,.22);
      padding: 22px;
    }}
    .modal-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
    .modal h2 {{ margin: 0; font-size: 28px; line-height: 1.05; letter-spacing: 0; }}
    .icon-button {{
      width: 36px;
      height: 36px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: white;
      cursor: pointer;
      font-weight: 900;
    }}
    .modal .screen {{ margin-top: 14px; }}
    .modal-footer {{ margin-top: 16px; }}
    @media (max-width: 780px) {{
      .hero, .workspace {{ grid-template-columns: 1fr; }}
      .hero {{ min-height: auto; }}
      .metrics {{ grid-template-columns: 1fr 1fr; }}
      .panel {{ border-right: 0; border-bottom: 1px solid var(--line); }}
      .map-wrap {{ min-height: 560px; }}
    }}
  </style>
</head>
<body>{body}</body>
</html>"""


def _home():
    return _layout("Bike Better San Diego", f"""
<nav class="nav">
  <div class="brand">Bike Better San Diego</div>
  <a href="/survey">Open engagement map</a>
</nav>
<main>
  <section class="hero">
    <div class="hero-copy">
      <div class="eyebrow">San Diego County Bicycle Coalition</div>
      <h1>Turn rider stories into safer streets.</h1>
      <p class="lead">Bring participation tools, visual project pages, and built-in reporting together so community feedback becomes clear insight for better bike decisions.</p>
      <div class="actions">
        <a class="button" href="/survey">Launch the map</a>
        <a class="button secondary" href="https://sdbikecoalition.org/">Visit SDBC</a>
      </div>
    </div>
    <div class="hero-image" role="img" aria-label="Bike and bus street scene"></div>
  </section>
  <section class="band">
    <div class="metrics">
      <div class="metric"><strong>Map</strong><span>locations that need safer bike access</span></div>
      <div class="metric"><strong>Talk</strong><span>support two-way community conversations</span></div>
      <div class="metric"><strong>Report</strong><span>turn public input into usable insights</span></div>
      <div class="metric"><strong>Act</strong><span>shape stronger project outcomes</span></div>
    </div>
  </section>
</main>""")


def _survey():
    token_js = MAPBOX_TOKEN.replace("\\", "\\\\").replace("'", "\\'")
    body = """
<nav class="nav">
  <div class="brand">Bike Better San Diego</div>
  <a href="/">Overview</a>
</nav>
<main class="workspace">
  <aside class="panel">
    <div class="eyebrow">Map safety concerns</div>
    <h1>Click the map to add a comment.</h1>
    <p class="lead">Click the exact place where biking feels unsafe, unclear, or disconnected. Each comment helps shape better project decisions.</p>
    <div class="step"><strong>1. Click the map</strong>A popup will open at that location.</div>
    <div class="step"><strong>2. Add details</strong>Choose an issue type, add a note, and attach a photo if useful.</div>
    <div class="step"><strong>3. Review your input</strong>You can edit or remove entries submitted from this browser.</div>
    <section class="review-panel">
      <span class="status-pill" id="savedStatus">Saved to the project map</span>
      <p class="lead">Review your mapped comments. You can edit or remove entries submitted from this browser.</p>
      <div class="pin-list" id="pinList"></div>
    </section>
    <section class="insights">
      <span class="status-pill" id="insightSource">Live reporting</span>
      <h2>Community insights</h2>
      <p class="insight-summary" id="insightSummary">Loading patterns from public comments...</p>
      <div class="insight-grid">
        <div class="insight-stat"><strong id="insightTotal">0</strong><span>comments</span></div>
        <div class="insight-stat"><strong id="insightNegative">0</strong><span>urgent</span></div>
        <div class="insight-stat"><strong id="insightThemes">0</strong><span>themes</span></div>
      </div>
      <div class="insight-list" id="themeList"></div>
      <div class="insight-list" id="actionList"></div>
    </section>
  </aside>
  <section class="map-wrap">
    <div id="map"><div class="fallback-map"></div></div>
    <div class="map-note" id="note">Click the map to open the input form.</div>
  </section>
</main>
<div class="modal-backdrop" id="pinModal" aria-hidden="true">
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
    <div class="modal-head">
      <div>
        <div class="eyebrow">Map input</div>
        <h2 id="modalTitle">Add a bike safety comment.</h2>
      </div>
      <button class="icon-button" type="button" data-action="close-modal" aria-label="Close">x</button>
    </div>
    <div class="wizard-top">
      <div class="progress" aria-label="Input progress"><span id="progressBar"></span></div>
      <div class="count" id="stepCount">1 / 3</div>
    </div>
    <section class="screen active" data-screen="type">
      <p class="lead">What kind of issue is at this location?</p>
      <div class="field">
        <label for="issueType">Issue type</label>
        <select id="issueType">
          <option value="">Choose one</option>
          <option value="Dangerous crossing">Dangerous crossing</option>
          <option value="Near miss">Near miss</option>
          <option value="Missing bike connection">Missing bike connection</option>
          <option value="Maintenance problem">Maintenance problem</option>
          <option value="Bike parking need">Bike parking need</option>
          <option value="Other">Other</option>
        </select>
      </div>
      <div class="field" id="otherTypeField" hidden>
        <label for="otherType">Describe the issue type</label>
        <input id="otherType" type="text" maxlength="80" placeholder="Example: Signal timing">
      </div>
      <div class="modal-footer row">
        <button class="button ghost" type="button" data-action="close-modal">Cancel</button>
        <button class="button" type="button" data-action="next-details">Next</button>
      </div>
    </section>
    <section class="screen" data-screen="details">
      <p class="lead">Add enough detail for staff, advocates, or elected offices to understand the need.</p>
      <div class="field">
        <label for="pinTitle">Short label</label>
        <input id="pinTitle" type="text" maxlength="80" placeholder="Example: Fast turns at 30th and University">
      </div>
      <div class="field">
        <label for="pinNote">What should change here?</label>
        <textarea id="pinNote" maxlength="500" placeholder="Describe the concern, who is affected, and what would help."></textarea>
      </div>
      <div class="field">
        <label for="pinPhoto">Photo, optional</label>
        <input id="pinPhoto" type="file" accept="image/*">
        <img class="photo-preview" id="photoPreview" alt="Selected photo preview">
      </div>
      <div class="modal-footer row">
        <button class="button ghost" type="button" data-action="back-type">Back</button>
        <button class="button" type="button" data-action="next-review">Review</button>
      </div>
    </section>
    <section class="screen" data-screen="confirm">
      <p class="lead">Review this comment before it appears on the public map.</p>
      <div class="step"><strong id="confirmTitle">Safety comment</strong><span id="confirmBody">Ready to save.</span></div>
      <img class="photo-preview" id="confirmPhoto" alt="Selected photo preview">
      <div class="modal-footer row">
        <button class="button ghost" type="button" data-action="back-details">Back</button>
        <button class="button" type="button" data-action="save">Save to map</button>
      </div>
    </section>
  </div>
</div>
<script src="https://api.mapbox.com/mapbox-gl-js/v3.10.0/mapbox-gl.js"></script>
<script>
const token = '__MAPBOX_TOKEN__';
const clientKey = 'sdbikeContributorId';
const ownedKey = 'sdbikeOwnedPinIds';

let pins = [];
let ownedIds = new Set(JSON.parse(localStorage.getItem(ownedKey) || '[]'));
let clientId = localStorage.getItem(clientKey);
if (!clientId) {
  clientId = (crypto.randomUUID ? crypto.randomUUID() : `client-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  localStorage.setItem(clientKey, clientId);
}

let map = null;
let screen = 'type';
let draft = {};
let editingId = null;
let draftMarker = null;
let fallbackPins = new Map();
let mapMarkers = new Map();

const titles = {
  type: 'Add a bike safety comment.',
  details: 'Add the story behind the pin.',
  confirm: 'Review this comment.'
};
const steps = { type: 1, details: 2, confirm: 3 };

function allPins() {
  return pins;
}

function ownedPins() {
  return pins.filter((pin) => ownedIds.has(pin.id));
}

function persistOwnedIds() {
  localStorage.setItem(ownedKey, JSON.stringify([...ownedIds]));
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}

async function loadPins() {
  try {
    const data = await api('/api/pins');
    pins = data.pins || [];
    renderMarkers();
    renderList();
    setNote(pins.length ? 'Public input loaded. Use the wizard to add your own comment.' : 'No public comments yet. Add the first mapped concern.');
  } catch (error) {
    setNote('The public map is temporarily unable to load saved comments. You can still review this page and try again shortly.');
  }
}

async function loadInsights() {
  try {
    const insights = await api('/api/insights');
    document.getElementById('insightSource').textContent = insights.generated_by === 'ai' ? 'AI-powered insights' : 'Live reporting';
    document.getElementById('insightSummary').textContent = insights.summary || 'No insights available yet.';
    document.getElementById('insightTotal').textContent = insights.total || 0;
    document.getElementById('insightNegative').textContent = insights.sentiment?.negative || 0;
    document.getElementById('insightThemes').textContent = (insights.themes || []).length;
    document.getElementById('themeList').innerHTML = (insights.themes || []).slice(0, 4).map((item) => `
      <div class="insight-item">${escapeHtml(item.theme)}<span>${item.mentions || 0} signals</span></div>
    `).join('') || '<div class="insight-item">No themes yet<span>Comments will appear here as they are submitted.</span></div>';
    document.getElementById('actionList').innerHTML = (insights.recommended_actions || []).slice(0, 3).map((item) => `
      <div class="insight-item">${escapeHtml(item)}</div>
    `).join('');
  } catch (error) {
    document.getElementById('insightSummary').textContent = 'Insights are temporarily unavailable.';
  }
}

function setScreen(next) {
  screen = next;
  document.querySelectorAll('#pinModal .screen').forEach((node) => node.classList.toggle('active', node.dataset.screen === next));
  document.getElementById('modalTitle').textContent = titles[next];
  document.getElementById('stepCount').textContent = `${steps[next]} / 3`;
  document.getElementById('progressBar').style.width = `${steps[next] * 33.333}%`;
  renderList();
}

function setNote(text) {
  document.getElementById('note').textContent = text;
}

function clearDraftMarker() {
  if (draftMarker && draftMarker.remove) draftMarker.remove();
  if (draftMarker && draftMarker.parentNode) draftMarker.parentNode.removeChild(draftMarker);
  draftMarker = null;
}

function openModal(next = 'type') {
  document.getElementById('pinModal').classList.add('open');
  document.getElementById('pinModal').setAttribute('aria-hidden', 'false');
  setScreen(next);
}

function closeModal(options = {}) {
  document.getElementById('pinModal').classList.remove('open');
  document.getElementById('pinModal').setAttribute('aria-hidden', 'true');
  if (!options.keepDraftMarker) clearDraftMarker();
  editingId = null;
}

function selectedCategory() {
  const value = document.getElementById('issueType').value;
  if (value === 'Other') return document.getElementById('otherType').value.trim();
  return value;
}

function resetForm() {
  document.getElementById('issueType').value = '';
  document.getElementById('otherType').value = '';
  document.getElementById('otherTypeField').hidden = true;
  document.getElementById('pinTitle').value = '';
  document.getElementById('pinNote').value = '';
  document.getElementById('pinPhoto').value = '';
  document.getElementById('photoPreview').style.display = 'none';
  document.getElementById('confirmPhoto').style.display = 'none';
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));
}

function popupHtml(pin) {
  const photo = pin.photo ? `<img class="popup-photo" src="${pin.photo}" alt="">` : '';
  return `<div class="popup-title">${escapeHtml(pin.title || pin.category)}</div>
    <div class="popup-note">${escapeHtml(pin.note || 'No note added yet.')}</div>${photo}`;
}

function addFallbackPin(pin, isDraft = false) {
  const wrap = document.querySelector('.map-wrap');
  const marker = document.createElement('button');
  marker.type = 'button';
  marker.className = 'pin';
  marker.title = pin.title || pin.category || 'Bike safety concern';
  marker.style.left = `${pin.x || 50}%`;
  marker.style.top = `${pin.y || 50}%`;
  marker.addEventListener('click', (event) => {
    event.stopPropagation();
    if (!isDraft && ownedIds.has(pin.id)) editPin(pin.id);
  });
  wrap.appendChild(marker);
  return marker;
}

function renderMarkers() {
  mapMarkers.forEach((marker) => marker.remove());
  mapMarkers.clear();
  fallbackPins.forEach((marker) => marker.remove());
  fallbackPins.clear();
  if (map) {
    allPins().forEach((pin) => {
      const marker = new mapboxgl.Marker({ color: '#d93636' })
        .setLngLat([pin.lng, pin.lat])
        .setPopup(new mapboxgl.Popup().setHTML(popupHtml(pin)))
        .addTo(map);
      marker.getElement().addEventListener('click', () => {
        if (ownedIds.has(pin.id)) setTimeout(() => editPin(pin.id), 0);
      });
      mapMarkers.set(pin.id, marker);
    });
  } else {
    allPins().forEach((pin) => fallbackPins.set(pin.id, addFallbackPin(pin)));
  }
}

function renderList() {
  const list = document.getElementById('pinList');
  if (!list) return;
  const mine = ownedPins();
  if (!mine.length) {
    list.innerHTML = '<div class="step"><strong>No submissions from this browser yet</strong>Add a concern to build your review list. Public comments from other people stay visible on the map.</div>';
    return;
  }
  list.innerHTML = mine.map((pin) => `
    <article class="pin-card">
      <strong>${escapeHtml(pin.title || pin.category)}</strong>
      <p>${escapeHtml(pin.category)}${pin.note ? ' - ' + escapeHtml(pin.note) : ''}</p>
      ${pin.photo ? `<img src="${pin.photo}" alt="">` : ''}
      <div class="pin-actions">
        <button class="small-button" type="button" data-edit="${pin.id}">Edit</button>
        <button class="small-button danger" type="button" data-delete="${pin.id}">Remove</button>
      </div>
    </article>
  `).join('');
}

function beginNew(lngLat, fallbackPoint) {
  clearDraftMarker();
  draft = {};
  editingId = null;
  resetForm();
  placeDraft(lngLat, fallbackPoint);
  setNote('Add details in the popup, then save the comment to the project map.');
  openModal('type');
}

function editPin(id) {
  const pin = ownedPins().find((item) => item.id === id);
  if (!pin) return;
  draft = { ...pin };
  editingId = id;
  resetForm();
  const standard = [...document.getElementById('issueType').options].some((option) => option.value === pin.category);
  document.getElementById('issueType').value = standard ? pin.category : 'Other';
  document.getElementById('otherTypeField').hidden = standard;
  document.getElementById('otherType').value = standard ? '' : pin.category;
  document.getElementById('pinTitle').value = pin.title || '';
  document.getElementById('pinNote').value = pin.note || '';
  const preview = document.getElementById('photoPreview');
  preview.src = pin.photo || '';
  preview.style.display = pin.photo ? 'block' : 'none';
  setNote('Editing this pin. Update details, or go back to place it again.');
  openModal('type');
}

async function removePin(id) {
  try {
    await api(`/api/pins/${id}`, {
      method: 'DELETE',
      body: JSON.stringify({ client_id: clientId })
    });
    ownedIds.delete(id);
    persistOwnedIds();
    pins = pins.filter((pin) => pin.id !== id);
    renderMarkers();
    renderList();
    loadInsights();
    setNote('Pin removed from the project map.');
  } catch (error) {
    setNote(error.message);
  }
}

function placeDraft(lngLat, fallbackPoint) {
  draft.lng = lngLat ? lngLat.lng : -117.1611;
  draft.lat = lngLat ? lngLat.lat : 32.7157;
  draft.x = fallbackPoint ? fallbackPoint.x : null;
  draft.y = fallbackPoint ? fallbackPoint.y : null;
  clearDraftMarker();
  if (map && lngLat) {
    draftMarker = new mapboxgl.Marker({ color: '#246bb2', draggable: true })
      .setLngLat(lngLat)
      .addTo(map);
    draftMarker.on('dragend', () => {
      const position = draftMarker.getLngLat();
      draft.lng = position.lng;
      draft.lat = position.lat;
    });
  } else {
    draftMarker = addFallbackPin({ ...draft, title: 'Draft concern' }, true);
  }
  setNote('Location selected. Complete the popup to save this comment.');
}

function prepareConfirm() {
  const category = selectedCategory();
  if (!category) {
    setNote('Choose an issue type before continuing.');
    setScreen('type');
    return false;
  }
  const title = document.getElementById('pinTitle').value.trim() || category;
  const note = document.getElementById('pinNote').value.trim();
  draft.category = category;
  document.getElementById('confirmTitle').textContent = title;
  document.getElementById('confirmBody').textContent = `${category}${note ? ' - ' + note : ''}`;
  const confirmPhoto = document.getElementById('confirmPhoto');
  confirmPhoto.src = draft.photo || '';
  confirmPhoto.style.display = draft.photo ? 'block' : 'none';
  setScreen('confirm');
  return true;
}

async function saveDraft() {
  const title = document.getElementById('pinTitle').value.trim();
  const note = document.getElementById('pinNote').value.trim();
  const category = selectedCategory();
  const nextPin = {
    ...draft,
    category,
    title: title || category,
    note,
    photo_data_url: draft.photo || '',
    client_id: clientId
  };
  if (!nextPin.lng && !nextPin.x) {
    setNote('Place the pin on the map before saving.');
    closeModal();
    return;
  }
  if (!category) {
    setNote('Choose an issue type before saving.');
    setScreen('type');
    return;
  }
  try {
    const result = editingId
      ? await api(`/api/pins/${editingId}`, { method: 'PATCH', body: JSON.stringify(nextPin) })
      : await api('/api/pins', { method: 'POST', body: JSON.stringify(nextPin) });
    const savedPin = result.pin;
    ownedIds.add(savedPin.id);
    persistOwnedIds();
    pins = editingId ? pins.map((pin) => pin.id === editingId ? savedPin : pin) : [savedPin].concat(pins);
    clearDraftMarker();
    renderMarkers();
    closeModal({ keepDraftMarker: true });
    renderList();
    loadInsights();
    setNote('Concern saved to the project map. Review it, edit it, or add another pin.');
  } catch (error) {
    setNote(error.message);
  }
}

function handleMapClick(event) {
  if (document.getElementById('pinModal').classList.contains('open')) return;
  if (event.lngLat) beginNew(event.lngLat, null);
}

document.querySelectorAll('[data-action]').forEach((button) => {
  button.addEventListener('click', () => {
    const action = button.dataset.action;
    if (action === 'close-modal') closeModal();
    if (action === 'next-details') {
      if (!selectedCategory()) {
        setNote('Choose an issue type before continuing.');
        return;
      }
      setScreen('details');
    }
    if (action === 'back-type') setScreen('type');
    if (action === 'next-review') prepareConfirm();
    if (action === 'back-details') setScreen('details');
    if (action === 'save') saveDraft();
  });
});

document.getElementById('issueType').addEventListener('change', (event) => {
  document.getElementById('otherTypeField').hidden = event.target.value !== 'Other';
});

document.getElementById('pinList').addEventListener('click', (event) => {
  const editButton = event.target.closest('[data-edit]');
  const deleteButton = event.target.closest('[data-delete]');
  if (editButton) editPin(editButton.dataset.edit);
  if (deleteButton) removePin(deleteButton.dataset.delete);
});

function resizePhoto(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const image = new Image();
      image.onload = () => {
        const maxSide = 1200;
        const scale = Math.min(1, maxSide / Math.max(image.width, image.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        const context = canvas.getContext('2d');
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/jpeg', 0.78));
      };
      image.onerror = reject;
      image.src = reader.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

document.getElementById('pinPhoto').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    draft.photo = await resizePhoto(file);
    const preview = document.getElementById('photoPreview');
    preview.src = draft.photo;
    preview.style.display = 'block';
  } catch (error) {
    setNote('That photo could not be loaded. Try another image.');
  }
});

if (token && window.mapboxgl) {
  mapboxgl.accessToken = token;
  map = new mapboxgl.Map({
    container: 'map',
    style: 'mapbox://styles/mapbox/streets-v12',
    center: [-117.1611, 32.7157],
    zoom: 11.2
  });
  map.addControl(new mapboxgl.NavigationControl({ showCompass: false }));
  map.on('load', renderMarkers);
  map.on('click', handleMapClick);
} else {
  document.querySelector('.map-wrap').addEventListener('click', (event) => {
    if (document.getElementById('pinModal').classList.contains('open')) return;
    const rect = event.currentTarget.getBoundingClientRect();
    beginNew(null, {
      x: ((event.clientX - rect.left) / rect.width) * 100,
      y: ((event.clientY - rect.top) / rect.height) * 100
    });
  });
}
setNote('Loading public comments...');
loadPins();
loadInsights();
</script>"""
    return _layout("Bike Better San Diego Survey", body.replace("__MAPBOX_TOKEN__", token_js))


def app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    query = parse_qs(environ.get("QUERY_STRING", ""))

    if path == "/api/insights":
        return _api_insights(start_response)
    if path == "/api/pins" or path.startswith("/api/pins/"):
        return _api_pins(environ, start_response, path)
    if path == "/favicon.ico":
        return _file_response(start_response, BASE_DIR / "survey" / "assets" / "favicon.ico")
    if path in ("/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
        return _file_response(start_response, BASE_DIR / "survey" / "assets" / "favicon-180x180.png")
    if path.startswith("/staticfiles/survey/assets/img/demo/sd-bike-bus.webp"):
        return _file_response(start_response, BASE_DIR / "survey" / "assets" / "img" / "demo" / "sd-bike-bus.webp")
    if path in ("/survey", "/survey/"):
        return _response(start_response, "200 OK", _survey())
    if path == "/healthz":
        return _response(start_response, "200 OK", "ok", "text/plain; charset=utf-8")
    if path == "/" or "x-vercel-set-bypass-cookie" in query:
        return _response(start_response, "200 OK", _home())

    return _response(start_response, "404 Not Found", "Not found", "text/plain; charset=utf-8")
