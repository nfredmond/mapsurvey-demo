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
DEMO_ADMIN_TOKEN = os.environ.get("DEMO_ADMIN_TOKEN", "")
PIN_COLUMNS = "id,created_at,category,title,note,lng,lat,photo_data_url,status"
PROJECT_SLUG = "bike-better-san-diego"
SAMPLE_CLIENT_ID = "sample-seed"
SAMPLE_PINS = [
    {
        "category": "Dangerous crossing",
        "title": "Fast turns at 30th and University",
        "note": "Drivers turn quickly across the bike lane and people biking have very little protected waiting space. A leading bike interval or hardened corner would help.",
        "lng": -117.1309,
        "lat": 32.7484,
    },
    {
        "category": "Missing bike connection",
        "title": "Gap between Balboa Park and downtown",
        "note": "The route feels comfortable inside the park, then becomes stressful near freeway ramps and downtown crossings. A continuous low-stress connection is needed.",
        "lng": -117.1598,
        "lat": 32.7259,
    },
    {
        "category": "Maintenance problem",
        "title": "Debris in Rose Canyon bike lane",
        "note": "Glass and sand collect in the shoulder after rain. Regular sweeping would make this important north-south route usable for commuters.",
        "lng": -117.2165,
        "lat": 32.8537,
    },
    {
        "category": "Dangerous crossing",
        "title": "I-5 ramp conflict near Old Town",
        "note": "High-speed ramp traffic creates a scary crossing for riders heading toward Mission Bay. The crossing needs clearer priority and slower turning speeds.",
        "lng": -117.1966,
        "lat": 32.7556,
    },
    {
        "category": "School route",
        "title": "Families need safer access to Chula Vista schools",
        "note": "Parents report avoiding bike trips because crossings near the school feel exposed during pickup and drop-off. Protected approaches would help families ride.",
        "lng": -117.0842,
        "lat": 32.6401,
    },
    {
        "category": "Missing bike connection",
        "title": "El Cajon Boulevard gap",
        "note": "This corridor has destinations people want to reach, but bike facilities disappear at key blocks. Add a connected bikeway or parallel neighborhood route.",
        "lng": -117.1032,
        "lat": 32.7552,
    },
    {
        "category": "Bike parking need",
        "title": "Secure parking near trolley station",
        "note": "People would combine biking and transit more often if there were secure bike lockers and visible racks near the station entrance.",
        "lng": -117.1467,
        "lat": 32.7169,
    },
    {
        "category": "Dangerous crossing",
        "title": "Coast Highway crossing in Encinitas",
        "note": "Beach traffic and turning vehicles make this crossing stressful for families. Better daylighting and protected intersection design would help.",
        "lng": -117.2921,
        "lat": 33.0474,
    },
    {
        "category": "Maintenance problem",
        "title": "Pavement seam on Bayshore Bikeway",
        "note": "A rough seam catches narrow tires near the curve. This is a high-use regional route and should be prioritized for repair.",
        "lng": -117.1136,
        "lat": 32.6187,
    },
    {
        "category": "Near miss",
        "title": "Close passes on Mira Mesa Boulevard",
        "note": "Riders report close passes from high-speed traffic. A painted lane is not enough here; the corridor needs physical separation.",
        "lng": -117.1455,
        "lat": 32.9121,
    },
    {
        "category": "School route",
        "title": "Safer route to Oceanside schools",
        "note": "Students riding from nearby neighborhoods need protected crossings and slower speeds near school entrances.",
        "lng": -117.3795,
        "lat": 33.1959,
    },
    {
        "category": "Missing bike connection",
        "title": "Santee river trail access gap",
        "note": "The trail is useful, but getting to it from nearby homes requires uncomfortable arterial riding. Add a signed and protected access route.",
        "lng": -116.9842,
        "lat": 32.8384,
    },
    {
        "category": "Dangerous crossing",
        "title": "La Mesa village crossing",
        "note": "People biking to shops have to negotiate angled parking and unpredictable turns. A calmer intersection treatment would support local trips.",
        "lng": -117.0207,
        "lat": 32.7679,
    },
    {
        "category": "Bike parking need",
        "title": "More racks near North Park businesses",
        "note": "Bike parking fills up on busy evenings. More corrals would support local businesses and reduce sidewalk clutter.",
        "lng": -117.1292,
        "lat": 32.7478,
    },
    {
        "category": "Maintenance problem",
        "title": "Flooding under SR-56 path",
        "note": "Standing water blocks the path after storms and forces riders into traffic. Drainage and detour signage are needed.",
        "lng": -117.1641,
        "lat": 32.9633,
    },
    {
        "category": "Near miss",
        "title": "Dooring risk near beach parking",
        "note": "The bike lane runs directly beside parked cars with heavy turnover. A parking-protected lane would reduce dooring risk.",
        "lng": -117.2549,
        "lat": 32.8025,
    },
]

SAMPLE_RESPONSES = [
    ("poll", "quick-priority-poll", {"choice": "Protected bike lanes"}),
    ("poll", "quick-priority-poll", {"choice": "Safer crossings"}),
    ("poll", "quick-priority-poll", {"choice": "Safer crossings"}),
    ("poll", "quick-priority-poll", {"choice": "Maintenance fixes"}),
    ("poll", "quick-priority-poll", {"choice": "School routes"}),
    ("survey", "rider-priorities", {
        "priority": "Connect schools, transit stops, and main street business districts with protected bikeways.",
        "affected_groups": "Students, families, workers without cars, and new riders.",
        "email": "",
    }),
    ("survey", "rider-priorities", {
        "priority": "Focus first on intersections where riders have reported close calls and fast turning traffic.",
        "affected_groups": "Older adults, e-bike commuters, and parents riding with children.",
        "email": "",
    }),
    ("discussion", "public-discussion", {
        "title": "Report back matters",
        "comment": "Please show which comments become grant applications or project requests so people know their input changed something.",
    }),
    ("discussion", "public-discussion", {
        "title": "Coordinate with schools",
        "comment": "Safe Routes to School partners should be part of the next review because many of these gaps affect students.",
    }),
]


def _response(start_response, status, body, content_type="text/html; charset=utf-8"):
    payload = body.encode("utf-8") if isinstance(body, str) else body
    start_response(status, [
        ("Content-Type", content_type),
        ("Content-Length", str(len(payload))),
        ("Cache-Control", "public, max-age=60"),
    ])
    return [payload]


def _json_response(start_response, status, data):
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    start_response(status, [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(payload))),
        ("Cache-Control", "no-store"),
    ])
    return [payload]


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


def _pin_feature(pin):
    public = _public_pin(pin)
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [public["lng"], public["lat"]],
        },
        "properties": {
            "id": public["id"],
            "created_at": public["created_at"],
            "category": public["category"],
            "title": public["title"],
            "note": public["note"],
        },
    }


def _geojson(rows):
    return {
        "type": "FeatureCollection",
        "name": "bike-better-san-diego-map-comments",
        "features": [_pin_feature(row) for row in rows if row.get("lng") is not None and row.get("lat") is not None],
    }


def _project_record():
    rows = _supabase_request(
        "GET",
        f"engagement_projects?slug=eq.{PROJECT_SLUG}&select=id,slug,title,organization,description,status,starts_at,ends_at",
    ) or []
    if rows:
        return rows[0]
    raise RuntimeError("Project is not configured.")


def _tool_records(project_id):
    rows = _supabase_request(
        "GET",
        f"engagement_tools?project_id=eq.{project_id}&is_active=eq.true&select=id,slug,tool_type,title,config&order=created_at.asc",
    ) or []
    return rows


def _tool_by_slug(tools, slug):
    return next((tool for tool in tools if tool.get("slug") == slug), None)


def _audit(project_id, event_type, entity_type, entity_id=None, metadata=None):
    try:
        _supabase_request("POST", "engagement_audit_events", {
            "project_id": project_id,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "metadata": metadata or {},
        })
    except RuntimeError:
        pass


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


def _api_project(start_response):
    try:
        project = _project_record()
        tools = _tool_records(project["id"])
        decisions = _supabase_request(
            "GET",
            f"engagement_decisions?project_id=eq.{project['id']}&select=id,title,description,source_summary,status,created_at&order=created_at.desc&limit=10",
        ) or []
        responses = _supabase_request(
            "GET",
            f"engagement_responses?project_id=eq.{project['id']}&status=eq.active&select=tool_type,payload,created_at&order=created_at.desc&limit=500",
        ) or []
        return _json_response(start_response, "200 OK", {
            "project": project,
            "tools": tools,
            "decisions": decisions,
            "counts": {
                "map": len(_supabase_request("GET", f"sdbike_engagement_pins?select=id&status=eq.active&limit=1000") or []),
                "survey": sum(1 for row in responses if row.get("tool_type") == "survey"),
                "poll": sum(1 for row in responses if row.get("tool_type") == "poll"),
                "discussion": sum(1 for row in responses if row.get("tool_type") == "discussion"),
            },
        })
    except RuntimeError:
        return _json_response(start_response, "502 Bad Gateway", {"error": "The project database is temporarily unavailable."})


def _api_responses(environ, start_response, path):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    try:
        project = _project_record()
        tools = _tool_records(project["id"])

        if path == "/api/poll" and method == "GET":
            rows = _supabase_request(
                "GET",
                f"engagement_responses?project_id=eq.{project['id']}&tool_type=eq.poll&status=eq.active&select=payload&limit=2000",
            ) or []
            counts = {}
            for row in rows:
                choice = (row.get("payload") or {}).get("choice") or "Unspecified"
                counts[choice] = counts.get(choice, 0) + 1
            return _json_response(start_response, "200 OK", {"results": counts, "total": sum(counts.values())})

        if path == "/api/discussion" and method == "GET":
            rows = _supabase_request(
                "GET",
                f"engagement_responses?project_id=eq.{project['id']}&tool_type=eq.discussion&status=eq.active&select=id,payload,created_at&order=created_at.desc&limit=20",
            ) or []
            posts = [
                {
                    "id": row.get("id"),
                    "created_at": row.get("created_at"),
                    "title": (row.get("payload") or {}).get("title") or "Community comment",
                    "comment": (row.get("payload") or {}).get("comment") or "",
                }
                for row in rows
            ]
            return _json_response(start_response, "200 OK", {"posts": posts})

        if path in ("/api/poll", "/api/survey", "/api/discussion") and method == "POST":
            payload = _read_json(environ)
            client_id = _clean_text(payload.get("client_id"), 80)
            if not client_id:
                return _json_response(start_response, "400 Bad Request", {"error": "A contributor id is required."})

            if path == "/api/poll":
                tool_type, slug = "poll", "quick-priority-poll"
                body = {"choice": _clean_text(payload.get("choice"), 120)}
                if not body["choice"]:
                    return _json_response(start_response, "400 Bad Request", {"error": "Choose an option before voting."})
            elif path == "/api/survey":
                tool_type, slug = "survey", "rider-priorities"
                body = {
                    "priority": _clean_text(payload.get("priority"), 400),
                    "affected_groups": _clean_text(payload.get("affected_groups"), 400),
                    "email": _clean_text(payload.get("email"), 160),
                }
                if not body["priority"]:
                    return _json_response(start_response, "400 Bad Request", {"error": "Add a project priority before submitting."})
            else:
                tool_type, slug = "discussion", "public-discussion"
                body = {
                    "title": _clean_text(payload.get("title"), 160),
                    "comment": _clean_text(payload.get("comment"), 1000),
                }
                if not body["comment"]:
                    return _json_response(start_response, "400 Bad Request", {"error": "Add a comment before posting."})

            tool = _tool_by_slug(tools, slug)
            rows = _supabase_request("POST", "engagement_responses", {
                "project_id": project["id"],
                "tool_id": tool.get("id") if tool else None,
                "tool_type": tool_type,
                "client_id": client_id,
                "payload": body,
            })
            response_id = (rows or [{}])[0].get("id")
            _audit(project["id"], f"{tool_type}_submitted", "engagement_response", response_id, {"tool": slug})
            return _json_response(start_response, "201 Created", {"ok": True, "id": response_id})

        return _json_response(start_response, "405 Method Not Allowed", {"error": "Method not allowed."})
    except (RuntimeError, json.JSONDecodeError):
        return _json_response(start_response, "502 Bad Gateway", {"error": "The engagement database is temporarily unavailable."})


def _api_report(start_response, fmt):
    try:
        rows = _supabase_request(
            "GET",
            f"sdbike_engagement_pins?select={PIN_COLUMNS}&status=eq.active&order=created_at.desc&limit=5000",
        ) or []
        if fmt == "json":
            insights = _fallback_insights(rows)
            return _json_response(start_response, "200 OK", {"pins": [_public_pin(row) for row in rows], "insights": insights})
        if fmt == "geojson":
            return _json_response(start_response, "200 OK", _geojson(rows))
        header = ["id", "created_at", "category", "title", "note", "lng", "lat"]
        lines = [",".join(header)]
        for row in rows:
            values = [str(row.get(column, "")).replace('"', '""') for column in header]
            lines.append(",".join(f'"{value}"' for value in values))
        payload = "\n".join(lines).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "text/csv; charset=utf-8"),
            ("Content-Length", str(len(payload))),
            ("Cache-Control", "no-store"),
            ("Content-Disposition", 'attachment; filename="bike-better-san-diego-map-comments.csv"'),
        ])
        return [payload]
    except RuntimeError:
        return _json_response(start_response, "502 Bad Gateway", {"error": "The report database is temporarily unavailable."})


def _authorized_demo_request(environ):
    if not DEMO_ADMIN_TOKEN:
        return False
    query = parse_qs(environ.get("QUERY_STRING", ""))
    supplied = environ.get("HTTP_X_DEMO_TOKEN") or query.get("token", [""])[0]
    return supplied == DEMO_ADMIN_TOKEN


def _reset_sample_data(project_id):
    _supabase_request("PATCH", "sdbike_engagement_pins?source=eq.sdbike-sample", {"status": "removed"})
    _supabase_request(
        "PATCH",
        f"engagement_responses?project_id=eq.{project_id}&client_id=eq.{SAMPLE_CLIENT_ID}",
        {"status": "removed"},
    )


def _api_demo_data(environ, start_response, action):
    if environ.get("REQUEST_METHOD", "GET").upper() != "POST":
        return _json_response(start_response, "405 Method Not Allowed", {"error": "Use POST for demo data operations."})
    if not _authorized_demo_request(environ):
        return _json_response(start_response, "403 Forbidden", {"error": "Demo data operations require an admin token."})
    try:
        project = _project_record()
        tools = _tool_records(project["id"])
        _reset_sample_data(project["id"])
        if action == "reset":
            _audit(project["id"], "sample_data_reset", "project", project["id"])
            return _json_response(start_response, "200 OK", {"ok": True, "pins": 0, "responses": 0})

        pin_rows = [
            {
                **pin,
                "client_id": SAMPLE_CLIENT_ID,
                "source": "sdbike-sample",
                "status": "active",
            }
            for pin in SAMPLE_PINS
        ]
        inserted_pins = _supabase_request("POST", "sdbike_engagement_pins", pin_rows) or []
        response_rows = []
        for tool_type, slug, payload in SAMPLE_RESPONSES:
            tool = _tool_by_slug(tools, slug)
            response_rows.append({
                "project_id": project["id"],
                "tool_id": tool.get("id") if tool else None,
                "tool_type": tool_type,
                "client_id": SAMPLE_CLIENT_ID,
                "payload": {**payload, "sample": True},
                "status": "active",
            })
        inserted_responses = _supabase_request("POST", "engagement_responses", response_rows) or []
        _audit(project["id"], "sample_data_loaded", "project", project["id"], {
            "pins": len(inserted_pins),
            "responses": len(inserted_responses),
        })
        return _json_response(start_response, "200 OK", {
            "ok": True,
            "pins": len(inserted_pins),
            "responses": len(inserted_responses),
        })
    except RuntimeError:
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
    .tool-panel {{ margin-top: 18px; border-top: 1px solid var(--line); padding-top: 16px; }}
    .tool-panel h2 {{ margin: 0 0 8px; font-size: 22px; line-height: 1.1; }}
    .tool-panel p {{ color: var(--muted); line-height: 1.4; }}
    .tool-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 10px 0 14px; }}
    .tool-stat {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: var(--paper); }}
    .tool-stat strong {{ display: block; font-size: 22px; }}
    .poll-options {{ display: grid; gap: 8px; margin: 10px 0; }}
    .poll-option {{ display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); border-radius: 8px; padding: 9px; font-weight: 800; background: white; }}
    .result-list {{ display: grid; gap: 8px; margin-top: 10px; }}
    .result-row {{ display: grid; gap: 5px; }}
    .result-meta {{ display: flex; justify-content: space-between; gap: 10px; color: var(--muted); font-weight: 800; font-size: 13px; }}
    .result-bar {{ height: 8px; border-radius: 8px; background: var(--soft); overflow: hidden; }}
    .result-bar span {{ display: block; height: 100%; background: var(--green); }}
    .decision-list, .discussion-list {{ display: grid; gap: 8px; margin-top: 10px; }}
    .decision-item, .discussion-item {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: white; }}
    .decision-item strong, .discussion-item strong {{ display: block; margin-bottom: 4px; }}
    .decision-item span, .discussion-item span {{ display: block; color: var(--muted); line-height: 1.35; }}
    .message {{ min-height: 20px; color: var(--green); font-weight: 800; }}
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
    .map-tools {{
      position: absolute;
      top: 18px;
      left: 18px;
      right: 18px;
      z-index: 3;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: end;
      max-width: 720px;
      background: rgba(255,255,255,.95);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
    }}
    .map-tools label {{ display: grid; gap: 5px; font-size: 12px; font-weight: 800; color: var(--muted); }}
    .map-tools select {{ min-width: 170px; min-height: 38px; padding: 6px 8px; }}
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
    .dashboard {{ padding: 30px clamp(18px, 4vw, 56px); }}
    .dashboard-head {{ display: grid; gap: 10px; max-width: 980px; margin-bottom: 22px; }}
    .dashboard h1 {{ font-size: clamp(34px, 5vw, 58px); line-height: 1; margin: 0; }}
    .dashboard-grid {{ display: grid; grid-template-columns: 1.2fr .8fr; gap: 18px; align-items: start; }}
    .dashboard-card {{ border: 1px solid var(--line); border-radius: 8px; background: white; padding: 18px; }}
    .dashboard-card h2 {{ margin: 0 0 10px; font-size: 24px; }}
    .wide-card {{ grid-column: 1 / -1; }}
    .staff-list {{ display: grid; gap: 10px; }}
    .staff-item {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: var(--paper); }}
    .staff-item strong {{ display: block; margin-bottom: 4px; }}
    .staff-item span {{ display: block; color: var(--muted); line-height: 1.4; }}
    .export-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
    .report-page {{ padding: 34px clamp(18px, 5vw, 72px); }}
    .report-section {{ border-top: 1px solid var(--line); padding: 22px 0; }}
    .report-section h2 {{ margin: 0 0 10px; font-size: 28px; }}
    .report-map {{ min-height: 320px; border: 1px solid var(--line); border-radius: 8px; background: #d9e9e4; position: relative; overflow: hidden; }}
    .report-dot {{ position: absolute; width: 10px; height: 10px; border-radius: 50%; background: #d93636; border: 2px solid white; transform: translate(-50%, -50%); }}
    @media print {{
      .nav, .export-row .button {{ display: none; }}
      body {{ background: white; }}
      .report-page {{ padding: 0; }}
      .dashboard-card, .metric, .staff-item {{ break-inside: avoid; }}
    }}
    @media (max-width: 780px) {{
      .hero, .workspace {{ grid-template-columns: 1fr; }}
      .hero {{ min-height: auto; }}
      .metrics {{ grid-template-columns: 1fr 1fr; }}
      .panel {{ border-right: 0; border-bottom: 1px solid var(--line); }}
      .map-wrap {{ min-height: 560px; }}
      .dashboard-grid {{ grid-template-columns: 1fr; }}
      .map-tools {{ position: relative; top: auto; left: auto; right: auto; margin: 10px; }}
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
    <section class="tool-panel">
      <span class="status-pill">Project hub</span>
      <h2 id="projectTitle">Bike Better San Diego</h2>
      <p id="projectDescription">Map issues, answer the priority poll, and share a short project comment.</p>
      <div class="tool-grid">
        <div class="tool-stat"><strong id="countMap">0</strong><span>map comments</span></div>
        <div class="tool-stat"><strong id="countSurvey">0</strong><span>survey responses</span></div>
        <div class="tool-stat"><strong id="countPoll">0</strong><span>poll votes</span></div>
        <div class="tool-stat"><strong id="countDiscussion">0</strong><span>discussion posts</span></div>
      </div>
    </section>
    <section class="tool-panel">
      <h2>Quick priority poll</h2>
      <p>What should the Coalition push hardest for first?</p>
      <div class="poll-options" id="pollOptions">
        <label class="poll-option"><input type="radio" name="pollChoice" value="Safer crossings">Safer crossings</label>
        <label class="poll-option"><input type="radio" name="pollChoice" value="Protected bike lanes">Protected bike lanes</label>
        <label class="poll-option"><input type="radio" name="pollChoice" value="Maintenance fixes">Maintenance fixes</label>
        <label class="poll-option"><input type="radio" name="pollChoice" value="Bike parking">Bike parking</label>
        <label class="poll-option"><input type="radio" name="pollChoice" value="School routes">School routes</label>
      </div>
      <div class="row"><button class="button" type="button" data-action="submit-poll">Vote</button></div>
      <p class="message" id="pollMessage"></p>
      <div class="result-list" id="pollResults"></div>
    </section>
    <section class="tool-panel">
      <h2>Short project survey</h2>
      <div class="field">
        <label for="priorityInput">What would make biking better here?</label>
        <textarea id="priorityInput" maxlength="400" placeholder="Example: Protected lanes on high-speed streets and safer crossings near transit stops."></textarea>
      </div>
      <div class="field">
        <label for="affectedInput">Who is most affected?</label>
        <textarea id="affectedInput" maxlength="400" placeholder="Example: Students, older adults, workers riding after dark, families, or new riders."></textarea>
      </div>
      <div class="field">
        <label for="emailInput">Email, optional</label>
        <input id="emailInput" type="text" maxlength="160" placeholder="For follow-up only">
      </div>
      <div class="row"><button class="button" type="button" data-action="submit-survey">Submit survey</button></div>
      <p class="message" id="surveyMessage"></p>
    </section>
    <section class="tool-panel">
      <h2>Conversation</h2>
      <div class="field">
        <label for="discussionTitle">Topic, optional</label>
        <input id="discussionTitle" type="text" maxlength="160" placeholder="Example: North Park school access">
      </div>
      <div class="field">
        <label for="discussionComment">What should decision-makers hear?</label>
        <textarea id="discussionComment" maxlength="1000" placeholder="Share a question, lived experience, or idea for follow-up."></textarea>
      </div>
      <div class="row"><button class="button" type="button" data-action="submit-discussion">Post comment</button></div>
      <p class="message" id="discussionMessage"></p>
      <div class="discussion-list" id="discussionList"></div>
    </section>
    <section class="tool-panel">
      <h2>Reporting</h2>
      <p>Download the current public record and track how input moves toward decisions.</p>
      <div class="row">
        <a class="button ghost" href="/api/report.csv">CSV export</a>
        <a class="button ghost" href="/api/report.json">JSON export</a>
      </div>
      <div class="decision-list" id="decisionList"></div>
    </section>
  </aside>
  <section class="map-wrap">
    <div id="map"><div class="fallback-map"></div></div>
    <div class="map-tools" aria-label="Map display controls">
      <label>Filter by issue
        <select id="categoryFilter">
          <option value="">All issues</option>
        </select>
      </label>
      <label>Map view
        <select id="mapMode">
          <option value="pins">Pins</option>
          <option value="clusters">Clusters</option>
          <option value="heatmap">Heatmap</option>
        </select>
      </label>
      <a class="small-button" href="/api/report.geojson">GeoJSON</a>
    </div>
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
let mapLayersReady = false;
let suppressNextMapClick = false;

const titles = {
  type: 'Add a bike safety comment.',
  details: 'Add the story behind the pin.',
  confirm: 'Review this comment.'
};
const steps = { type: 1, details: 2, confirm: 3 };

function allPins() {
  return pins;
}

function filteredPins() {
  const category = document.getElementById('categoryFilter')?.value || '';
  return category ? pins.filter((pin) => pin.category === category) : pins;
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
    renderCategoryFilter();
    renderMarkers();
    renderList();
    setNote(pins.length ? 'Public input loaded. Use the wizard to add your own comment.' : 'No public comments yet. Add the first mapped concern.');
  } catch (error) {
    setNote('The public map is temporarily unable to load saved comments. You can still review this page and try again shortly.');
  }
}

function renderCategoryFilter() {
  const select = document.getElementById('categoryFilter');
  if (!select) return;
  const selected = select.value;
  const categories = [...new Set(pins.map((pin) => pin.category).filter(Boolean))].sort();
  select.innerHTML = '<option value="">All issues</option>' + categories.map((category) => `
    <option value="${escapeHtml(category)}">${escapeHtml(category)}</option>
  `).join('');
  if (categories.includes(selected)) select.value = selected;
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

async function loadProject() {
  try {
    const data = await api('/api/project');
    const project = data.project || {};
    const counts = data.counts || {};
    document.getElementById('projectTitle').textContent = project.title || 'Bike Better San Diego';
    document.getElementById('projectDescription').textContent = project.description || 'Public input is open for this project.';
    document.getElementById('countMap').textContent = counts.map || 0;
    document.getElementById('countSurvey').textContent = counts.survey || 0;
    document.getElementById('countPoll').textContent = counts.poll || 0;
    document.getElementById('countDiscussion').textContent = counts.discussion || 0;
    document.getElementById('decisionList').innerHTML = (data.decisions || []).map((item) => `
      <article class="decision-item">
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.description || item.source_summary || 'Decision record')}</span>
      </article>
    `).join('') || '<article class="decision-item"><strong>No decisions posted yet</strong><span>Outcomes will appear here as the Coalition reports back.</span></article>';
  } catch (error) {
    document.getElementById('projectDescription').textContent = 'Project metadata is temporarily unavailable.';
  }
}

async function loadPoll() {
  try {
    const data = await api('/api/poll');
    const entries = Object.entries(data.results || {});
    const total = data.total || 0;
    document.getElementById('pollResults').innerHTML = entries.map(([label, count]) => {
      const pct = total ? Math.round((count / total) * 100) : 0;
      return `<div class="result-row">
        <div class="result-meta"><span>${escapeHtml(label)}</span><span>${count} votes</span></div>
        <div class="result-bar"><span style="width:${pct}%"></span></div>
      </div>`;
    }).join('') || '<div class="insight-item">No votes yet<span>Results will update after the first vote.</span></div>';
  } catch (error) {
    document.getElementById('pollResults').innerHTML = '<div class="insight-item">Poll results are temporarily unavailable.</div>';
  }
}

async function loadDiscussion() {
  try {
    const data = await api('/api/discussion');
    document.getElementById('discussionList').innerHTML = (data.posts || []).map((post) => `
      <article class="discussion-item">
        <strong>${escapeHtml(post.title)}</strong>
        <span>${escapeHtml(post.comment)}</span>
      </article>
    `).join('') || '<article class="discussion-item"><strong>No conversation posts yet</strong><span>Share the first question, concern, or idea.</span></article>';
  } catch (error) {
    document.getElementById('discussionList').innerHTML = '<article class="discussion-item"><strong>Conversation unavailable</strong><span>Try again shortly.</span></article>';
  }
}

async function submitPoll() {
  const choice = document.querySelector('input[name="pollChoice"]:checked')?.value || '';
  if (!choice) {
    document.getElementById('pollMessage').textContent = 'Choose an option before voting.';
    return;
  }
  try {
    await api('/api/poll', { method: 'POST', body: JSON.stringify({ client_id: clientId, choice }) });
    document.getElementById('pollMessage').textContent = 'Vote recorded.';
    document.querySelectorAll('input[name="pollChoice"]').forEach((input) => { input.checked = false; });
    loadPoll();
    loadProject();
  } catch (error) {
    document.getElementById('pollMessage').textContent = error.message;
  }
}

async function submitSurvey() {
  const priority = document.getElementById('priorityInput').value.trim();
  const affectedGroups = document.getElementById('affectedInput').value.trim();
  const email = document.getElementById('emailInput').value.trim();
  if (!priority) {
    document.getElementById('surveyMessage').textContent = 'Add a project priority before submitting.';
    return;
  }
  try {
    await api('/api/survey', {
      method: 'POST',
      body: JSON.stringify({ client_id: clientId, priority, affected_groups: affectedGroups, email })
    });
    document.getElementById('priorityInput').value = '';
    document.getElementById('affectedInput').value = '';
    document.getElementById('emailInput').value = '';
    document.getElementById('surveyMessage').textContent = 'Survey response recorded.';
    loadProject();
  } catch (error) {
    document.getElementById('surveyMessage').textContent = error.message;
  }
}

async function submitDiscussion() {
  const title = document.getElementById('discussionTitle').value.trim();
  const comment = document.getElementById('discussionComment').value.trim();
  if (!comment) {
    document.getElementById('discussionMessage').textContent = 'Add a comment before posting.';
    return;
  }
  try {
    await api('/api/discussion', {
      method: 'POST',
      body: JSON.stringify({ client_id: clientId, title, comment })
    });
    document.getElementById('discussionTitle').value = '';
    document.getElementById('discussionComment').value = '';
    document.getElementById('discussionMessage').textContent = 'Comment posted.';
    loadDiscussion();
    loadProject();
  } catch (error) {
    document.getElementById('discussionMessage').textContent = error.message;
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

function pinsGeoJson() {
  return {
    type: 'FeatureCollection',
    features: filteredPins()
      .filter((pin) => pin.lng !== null && pin.lat !== null)
      .map((pin) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [pin.lng, pin.lat] },
        properties: {
          id: pin.id,
          category: pin.category || 'Uncategorized',
          title: pin.title || pin.category || 'Bike safety concern',
          note: pin.note || ''
        }
      }))
  };
}

function layerVisibility(mode, layer) {
  if (mode === 'heatmap') return layer === 'pins-heatmap' ? 'visible' : 'none';
  if (mode === 'clusters') return layer === 'pins-heatmap' ? 'none' : 'visible';
  if (layer === 'unclustered-pins') return 'visible';
  return 'none';
}

function ensureMapLayers() {
  if (!map || mapLayersReady || !map.loaded()) return;
  map.addSource('engagement-pins', {
    type: 'geojson',
    data: pinsGeoJson(),
    cluster: true,
    clusterRadius: 52,
    clusterMaxZoom: 14
  });
  map.addLayer({
    id: 'pins-heatmap',
    type: 'heatmap',
    source: 'engagement-pins',
    maxzoom: 16,
    paint: {
      'heatmap-weight': 1,
      'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 8, 0.7, 14, 1.7],
      'heatmap-color': [
        'interpolate', ['linear'], ['heatmap-density'],
        0, 'rgba(36,107,178,0)',
        0.25, 'rgba(36,107,178,.5)',
        0.55, 'rgba(12,122,77,.7)',
        0.85, 'rgba(255,212,71,.85)',
        1, 'rgba(217,54,54,.95)'
      ],
      'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 8, 18, 14, 34],
      'heatmap-opacity': 0
    }
  });
  map.addLayer({
    id: 'pin-clusters',
    type: 'circle',
    source: 'engagement-pins',
    filter: ['has', 'point_count'],
    paint: {
      'circle-color': ['step', ['get', 'point_count'], '#246bb2', 10, '#0c7a4d', 30, '#d93636'],
      'circle-radius': ['step', ['get', 'point_count'], 18, 10, 24, 30, 32],
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 2
    }
  });
  map.addLayer({
    id: 'cluster-count',
    type: 'symbol',
    source: 'engagement-pins',
    filter: ['has', 'point_count'],
    layout: {
      'text-field': ['get', 'point_count_abbreviated'],
      'text-size': 12
    },
    paint: { 'text-color': '#ffffff' }
  });
  map.addLayer({
    id: 'unclustered-pins',
    type: 'circle',
    source: 'engagement-pins',
    filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-color': '#d93636',
      'circle-radius': 7,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 2
    }
  });
  map.on('click', 'pin-clusters', (event) => {
    suppressNextMapClick = true;
    const features = map.queryRenderedFeatures(event.point, { layers: ['pin-clusters'] });
    const clusterId = features[0]?.properties?.cluster_id;
    if (clusterId === undefined) return;
    map.getSource('engagement-pins').getClusterExpansionZoom(clusterId, (error, zoom) => {
      if (error) return;
      map.easeTo({ center: features[0].geometry.coordinates, zoom });
    });
  });
  map.on('click', 'unclustered-pins', (event) => {
    suppressNextMapClick = true;
    const feature = event.features && event.features[0];
    if (!feature) return;
    const id = feature.properties.id;
    const pin = pins.find((item) => item.id === id);
    if (!pin) return;
    new mapboxgl.Popup().setLngLat(feature.geometry.coordinates).setHTML(popupHtml(pin)).addTo(map);
    if (ownedIds.has(id)) setTimeout(() => editPin(id), 0);
  });
  ['pin-clusters', 'unclustered-pins'].forEach((layer) => {
    map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
  });
  mapLayersReady = true;
}

function updateMapLayers() {
  if (!map) return;
  ensureMapLayers();
  const source = map.getSource('engagement-pins');
  if (!source) return;
  source.setData(pinsGeoJson());
  const mode = document.getElementById('mapMode')?.value || 'pins';
  ['pins-heatmap', 'pin-clusters', 'cluster-count', 'unclustered-pins'].forEach((layer) => {
    if (map.getLayer(layer)) {
      map.setLayoutProperty(layer, 'visibility', layerVisibility(mode, layer));
      if (layer === 'pins-heatmap') map.setPaintProperty(layer, 'heatmap-opacity', mode === 'heatmap' ? 0.82 : 0);
    }
  });
}

function renderMarkers() {
  mapMarkers.forEach((marker) => marker.remove());
  mapMarkers.clear();
  fallbackPins.forEach((marker) => marker.remove());
  fallbackPins.clear();
  if (map) {
    updateMapLayers();
  } else {
    filteredPins().forEach((pin) => fallbackPins.set(pin.id, addFallbackPin(pin)));
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
    loadProject();
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
    loadProject();
    setNote('Concern saved to the project map. Review it, edit it, or add another pin.');
  } catch (error) {
    setNote(error.message);
  }
}

function handleMapClick(event) {
  if (document.getElementById('pinModal').classList.contains('open')) return;
  if (suppressNextMapClick) {
    suppressNextMapClick = false;
    return;
  }
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
    if (action === 'submit-poll') submitPoll();
    if (action === 'submit-survey') submitSurvey();
    if (action === 'submit-discussion') submitDiscussion();
  });
});

document.getElementById('issueType').addEventListener('change', (event) => {
  document.getElementById('otherTypeField').hidden = event.target.value !== 'Other';
});

document.getElementById('categoryFilter').addEventListener('change', renderMarkers);
document.getElementById('mapMode').addEventListener('change', renderMarkers);

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
  map.on('load', () => {
    ensureMapLayers();
    renderMarkers();
  });
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
loadProject();
loadPoll();
loadDiscussion();
</script>"""
    return _layout("Bike Better San Diego Survey", body.replace("__MAPBOX_TOKEN__", token_js))


def _staff():
    body = """
<nav class="nav">
  <div class="brand">Bike Better San Diego</div>
  <div class="actions">
    <a href="/survey">Public tools</a>
    <a href="/report">Report</a>
    <a href="/">Overview</a>
  </div>
</nav>
<main class="dashboard">
  <section class="dashboard-head">
    <div class="eyebrow">Staff dashboard</div>
    <h1>Turn community input into action.</h1>
    <p class="lead">Review live participation, export GIS-ready records, and draft planning language from mapped comments, poll results, survey responses, and conversations.</p>
  </section>
  <section class="metrics" aria-label="Engagement totals">
    <div class="metric"><strong id="staffMap">0</strong><span>map comments</span></div>
    <div class="metric"><strong id="staffSurvey">0</strong><span>survey responses</span></div>
    <div class="metric"><strong id="staffPoll">0</strong><span>poll votes</span></div>
    <div class="metric"><strong id="staffDiscussion">0</strong><span>conversation posts</span></div>
  </section>
  <section class="dashboard-grid" style="margin-top:18px">
    <article class="dashboard-card">
      <span class="status-pill" id="staffInsightSource">Live reporting</span>
      <h2>Insight brief</h2>
      <p class="insight-summary" id="staffSummary">Loading insight brief...</p>
      <div class="insight-grid">
        <div class="insight-stat"><strong id="staffNegative">0</strong><span>urgent</span></div>
        <div class="insight-stat"><strong id="staffMixed">0</strong><span>mixed</span></div>
        <div class="insight-stat"><strong id="staffPositive">0</strong><span>positive</span></div>
      </div>
      <div class="staff-list" id="staffActions"></div>
    </article>
    <article class="dashboard-card">
      <h2>Exports</h2>
      <p>Download the current public record for GIS, spreadsheets, and reproducible reporting.</p>
      <div class="export-row">
        <a class="button ghost" href="/report">Printable report</a>
        <a class="button ghost" href="/api/report.geojson">GeoJSON</a>
        <a class="button ghost" href="/api/report.csv">CSV</a>
        <a class="button ghost" href="/api/report.json">JSON</a>
      </div>
      <div class="field">
        <label for="demoToken">Demo admin token</label>
        <input id="demoToken" type="text" placeholder="Required to load or reset sample data">
      </div>
      <div class="export-row">
        <button class="small-button" type="button" data-demo-action="seed">Load sample data</button>
        <button class="small-button danger" type="button" data-demo-action="reset">Reset sample data</button>
      </div>
      <p class="message" id="demoMessage"></p>
    </article>
    <article class="dashboard-card">
      <h2>Top themes</h2>
      <div class="result-list" id="staffThemes"></div>
    </article>
    <article class="dashboard-card">
      <h2>Quick poll</h2>
      <div class="result-list" id="staffPollResults"></div>
    </article>
    <article class="dashboard-card wide-card">
      <h2>Planner mode draft</h2>
      <p id="plannerDraft">Loading a draft summary...</p>
    </article>
    <article class="dashboard-card">
      <h2>Recent map comments</h2>
      <div class="staff-list" id="staffPins"></div>
    </article>
    <article class="dashboard-card">
      <h2>Recent conversation</h2>
      <div class="staff-list" id="staffDiscussionList"></div>
    </article>
  </section>
</main>
<script>
async function api(path) {
  const response = await fetch(path);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}

async function postDemoData(action) {
  const token = document.getElementById('demoToken').value.trim();
  if (!token) {
    document.getElementById('demoMessage').textContent = 'Enter the demo admin token first.';
    return;
  }
  const response = await fetch(`/api/demo/${action}`, {
    method: 'POST',
    headers: { 'x-demo-token': token }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    document.getElementById('demoMessage').textContent = data.error || 'Demo data operation failed.';
    return;
  }
  document.getElementById('demoMessage').textContent = action === 'seed'
    ? `Loaded ${data.pins} sample pins and ${data.responses} sample responses.`
    : 'Sample data reset.';
  loadStaffDashboard();
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

function resultRows(results) {
  const entries = Object.entries(results || {});
  const total = entries.reduce((sum, entry) => sum + entry[1], 0);
  return entries.map(([label, count]) => {
    const pct = total ? Math.round((count / total) * 100) : 0;
    return `<div class="result-row">
      <div class="result-meta"><span>${escapeHtml(label)}</span><span>${count}</span></div>
      <div class="result-bar"><span style="width:${pct}%"></span></div>
    </div>`;
  }).join('') || '<div class="staff-item"><strong>No responses yet</strong><span>Results will appear as people participate.</span></div>';
}

function plannerLanguage(insights, counts) {
  if (!insights.total) {
    return 'No public comments have been submitted yet. Once input is received, this section will draft ATP/RTP-ready language that summarizes key needs, geography, and recommended follow-up actions.';
  }
  const themes = (insights.themes || []).map((item) => item.theme).slice(0, 3).join(', ') || 'bike safety';
  const action = (insights.recommended_actions || [])[0] || 'review mapped comments and group nearby issues into project-ready needs statements';
  return `Community input for Bike Better San Diego includes ${counts.map || insights.total} mapped comments, ${counts.survey || 0} survey responses, and ${counts.discussion || 0} conversation posts. Initial analysis points to ${themes}. Recommended next step: ${action}`;
}

async function loadStaffDashboard() {
  const [project, insights, report, poll, discussion] = await Promise.all([
    api('/api/project'),
    api('/api/insights'),
    api('/api/report.json'),
    api('/api/poll'),
    api('/api/discussion')
  ]);
  const counts = project.counts || {};
  document.getElementById('staffMap').textContent = counts.map || 0;
  document.getElementById('staffSurvey').textContent = counts.survey || 0;
  document.getElementById('staffPoll').textContent = counts.poll || 0;
  document.getElementById('staffDiscussion').textContent = counts.discussion || 0;
  document.getElementById('staffInsightSource').textContent = insights.generated_by === 'ai' ? 'AI-powered insights' : 'Live reporting';
  document.getElementById('staffSummary').textContent = insights.summary || 'No insight summary available yet.';
  document.getElementById('staffNegative').textContent = insights.sentiment?.negative || 0;
  document.getElementById('staffMixed').textContent = insights.sentiment?.mixed || 0;
  document.getElementById('staffPositive').textContent = insights.sentiment?.positive || 0;
  document.getElementById('staffActions').innerHTML = (insights.recommended_actions || []).map((item) => `
    <div class="staff-item"><strong>Recommended action</strong><span>${escapeHtml(item)}</span></div>
  `).join('') || '<div class="staff-item"><strong>No actions yet</strong><span>Actions will appear after public comments are submitted.</span></div>';
  document.getElementById('staffThemes').innerHTML = (insights.themes || []).map((item) => `
    <div class="result-row">
      <div class="result-meta"><span>${escapeHtml(item.theme)}</span><span>${item.mentions || 0} signals</span></div>
      <div class="result-bar"><span style="width:${Math.min(100, (item.mentions || 0) * 20)}%"></span></div>
    </div>
  `).join('') || '<div class="staff-item"><strong>No themes yet</strong><span>Theme extraction starts when mapped comments exist.</span></div>';
  document.getElementById('staffPollResults').innerHTML = resultRows(poll.results);
  document.getElementById('plannerDraft').textContent = plannerLanguage(insights, counts);
  document.getElementById('staffPins').innerHTML = (report.pins || []).slice(0, 8).map((pin) => `
    <div class="staff-item"><strong>${escapeHtml(pin.title || pin.category)}</strong><span>${escapeHtml(pin.category)} at ${Number(pin.lat).toFixed(4)}, ${Number(pin.lng).toFixed(4)}</span></div>
  `).join('') || '<div class="staff-item"><strong>No mapped comments yet</strong><span>Recent map input will appear here.</span></div>';
  document.getElementById('staffDiscussionList').innerHTML = (discussion.posts || []).slice(0, 8).map((post) => `
    <div class="staff-item"><strong>${escapeHtml(post.title)}</strong><span>${escapeHtml(post.comment)}</span></div>
  `).join('') || '<div class="staff-item"><strong>No conversation posts yet</strong><span>Discussion activity will appear here.</span></div>';
}

loadStaffDashboard().catch(() => {
  document.getElementById('staffSummary').textContent = 'Dashboard data is temporarily unavailable.';
});

document.querySelectorAll('[data-demo-action]').forEach((button) => {
  button.addEventListener('click', () => postDemoData(button.dataset.demoAction));
});
</script>"""
    return _layout("Bike Better San Diego Staff Dashboard", body)


def _report_page():
    body = """
<nav class="nav">
  <div class="brand">Bike Better San Diego</div>
  <div class="actions">
    <a href="/staff">Staff dashboard</a>
    <a href="/survey">Public tools</a>
  </div>
</nav>
<main class="report-page">
  <section class="dashboard-head">
    <div class="eyebrow">Printable engagement report</div>
    <h1>Bike Better San Diego: What We Heard</h1>
    <p class="lead" id="reportLead">Loading report summary...</p>
    <div class="export-row">
      <button class="button" type="button" onclick="window.print()">Print or save PDF</button>
      <a class="button ghost" href="/api/report.geojson">GeoJSON</a>
      <a class="button ghost" href="/api/report.csv">CSV</a>
    </div>
  </section>
  <section class="metrics" aria-label="Report totals">
    <div class="metric"><strong id="reportMap">0</strong><span>map comments</span></div>
    <div class="metric"><strong id="reportSurvey">0</strong><span>survey responses</span></div>
    <div class="metric"><strong id="reportPoll">0</strong><span>poll votes</span></div>
    <div class="metric"><strong id="reportDiscussion">0</strong><span>conversation posts</span></div>
  </section>
  <section class="report-section">
    <h2>Map Snapshot</h2>
    <p>Mapped comments show where riders experience unsafe crossings, missing links, maintenance barriers, school-route gaps, and bike parking needs.</p>
    <div class="report-map" id="reportMapPreview" aria-label="Static map preview of comments"></div>
  </section>
  <section class="report-section">
    <h2>Key Themes</h2>
    <div class="result-list" id="reportThemes"></div>
  </section>
  <section class="report-section">
    <h2>Recommended Actions</h2>
    <div class="staff-list" id="reportActions"></div>
  </section>
  <section class="report-section">
    <h2>Planner Mode Draft</h2>
    <p id="reportPlanner">Loading draft language...</p>
  </section>
  <section class="report-section">
    <h2>Appendix: Recent Comments</h2>
    <div class="staff-list" id="reportPins"></div>
  </section>
</main>
<script>
async function api(path) {
  const response = await fetch(path);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
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

function plannerLanguage(insights, counts) {
  if (!insights.total) {
    return 'No public comments have been submitted yet. This report will update as residents add mapped comments, poll responses, survey feedback, and conversation posts.';
  }
  const themes = (insights.themes || []).map((item) => item.theme).slice(0, 3).join(', ') || 'bike safety';
  const action = (insights.recommended_actions || [])[0] || 'group nearby comments into project-ready problem statements';
  return `Community input includes ${counts.map || insights.total} mapped comments, ${counts.survey || 0} survey responses, ${counts.poll || 0} poll votes, and ${counts.discussion || 0} conversation posts. The strongest recurring themes are ${themes}. Recommended next step: ${action}`;
}

function renderMapPreview(pins) {
  const node = document.getElementById('reportMapPreview');
  if (!pins.length) {
    node.innerHTML = '<div class="map-note">No mapped comments yet.</div>';
    return;
  }
  const minLng = -117.45, maxLng = -116.85, minLat = 32.55, maxLat = 33.25;
  node.innerHTML = pins.map((pin) => {
    const x = Math.max(3, Math.min(97, ((pin.lng - minLng) / (maxLng - minLng)) * 100));
    const y = Math.max(3, Math.min(97, (1 - ((pin.lat - minLat) / (maxLat - minLat))) * 100));
    return `<span class="report-dot" title="${escapeHtml(pin.title)}" style="left:${x}%;top:${y}%"></span>`;
  }).join('') + '<div class="map-note">Static preview for print. Use GeoJSON for GIS analysis.</div>';
}

async function loadReport() {
  const [project, insights, report] = await Promise.all([
    api('/api/project'),
    api('/api/insights'),
    api('/api/report.json')
  ]);
  const counts = project.counts || {};
  document.getElementById('reportMap').textContent = counts.map || 0;
  document.getElementById('reportSurvey').textContent = counts.survey || 0;
  document.getElementById('reportPoll').textContent = counts.poll || 0;
  document.getElementById('reportDiscussion').textContent = counts.discussion || 0;
  document.getElementById('reportLead').textContent = insights.summary || 'Engagement summary will appear as public input is collected.';
  document.getElementById('reportThemes').innerHTML = (insights.themes || []).map((item) => `
    <div class="result-row">
      <div class="result-meta"><span>${escapeHtml(item.theme)}</span><span>${item.mentions || 0} signals</span></div>
      <div class="result-bar"><span style="width:${Math.min(100, (item.mentions || 0) * 20)}%"></span></div>
    </div>
  `).join('') || '<div class="staff-item"><strong>No themes yet</strong><span>Theme extraction starts when public comments are available.</span></div>';
  document.getElementById('reportActions').innerHTML = (insights.recommended_actions || []).map((item) => `
    <div class="staff-item"><strong>Recommended action</strong><span>${escapeHtml(item)}</span></div>
  `).join('');
  document.getElementById('reportPlanner').textContent = plannerLanguage(insights, counts);
  document.getElementById('reportPins').innerHTML = (report.pins || []).slice(0, 20).map((pin) => `
    <div class="staff-item"><strong>${escapeHtml(pin.title || pin.category)}</strong><span>${escapeHtml(pin.category)}: ${escapeHtml(pin.note)}</span></div>
  `).join('') || '<div class="staff-item"><strong>No comments yet</strong><span>Recent comments will appear here.</span></div>';
  renderMapPreview(report.pins || []);
}

loadReport().catch(() => {
  document.getElementById('reportLead').textContent = 'Report data is temporarily unavailable.';
});
</script>"""
    return _layout("Bike Better San Diego Printable Report", body)


def app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    query = parse_qs(environ.get("QUERY_STRING", ""))

    if path == "/api/insights":
        return _api_insights(start_response)
    if path == "/api/project":
        return _api_project(start_response)
    if path in ("/api/poll", "/api/survey", "/api/discussion"):
        return _api_responses(environ, start_response, path)
    if path == "/api/report.json":
        return _api_report(start_response, "json")
    if path == "/api/report.geojson":
        return _api_report(start_response, "geojson")
    if path == "/api/report.csv":
        return _api_report(start_response, "csv")
    if path == "/api/demo/seed":
        return _api_demo_data(environ, start_response, "seed")
    if path == "/api/demo/reset":
        return _api_demo_data(environ, start_response, "reset")
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
    if path in ("/staff", "/staff/"):
        return _response(start_response, "200 OK", _staff())
    if path in ("/report", "/report/"):
        return _response(start_response, "200 OK", _report_page())
    if path == "/healthz":
        return _response(start_response, "200 OK", "ok", "text/plain; charset=utf-8")
    if path == "/" or "x-vercel-set-bypass-cookie" in query:
        return _response(start_response, "200 OK", _home())

    return _response(start_response, "404 Not Found", "Not found", "text/plain; charset=utf-8")
