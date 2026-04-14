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
    .wizard-top {{ display: flex; justify-content: space-between; align-items: center; gap: 14px; margin: 16px 0; }}
    .progress {{ flex: 1; height: 8px; background: var(--soft); border-radius: 8px; overflow: hidden; }}
    .progress span {{ display: block; height: 100%; width: 25%; background: var(--green); transition: width .2s ease; }}
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
    textarea, input[type="text"], input[type="file"] {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 11px;
      font: inherit;
      color: var(--ink);
      background: white;
    }}
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
      <p class="lead">Collect safety concerns, missing links, route ideas, and everyday barriers in one public map built for community workshops and online input.</p>
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
      <div class="metric"><strong>Add</strong><span>notes and photos from the field</span></div>
      <div class="metric"><strong>Review</strong><span>your own comments before sharing</span></div>
      <div class="metric"><strong>Use</strong><span>public input for advocacy priorities</span></div>
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
    <h1 id="wizardTitle">Start with one bike safety story.</h1>
    <div class="wizard-top">
      <div class="progress" aria-label="Survey progress"><span id="progressBar"></span></div>
      <div class="count" id="stepCount">1 / 4</div>
    </div>
    <section class="screen active" data-screen="intro">
      <p class="lead">Walk through a quick map survey, then review or remove what you added before sharing priorities.</p>
      <div class="step"><strong>Step 1</strong>Pick the kind of feedback you want to leave.</div>
      <div class="step"><strong>Step 2</strong>Click the map where it happens.</div>
      <div class="step"><strong>Step 3</strong>Add a note and optional photo.</div>
      <button class="button" type="button" data-action="start">Start survey</button>
    </section>
    <section class="screen" data-screen="category">
      <p class="lead">Choose the issue that best fits this location.</p>
      <div class="choice-list" id="categoryList">
        <button class="choice" type="button" data-category="Dangerous crossing">Dangerous crossing<span>Hard to cross, poor visibility, or fast turning traffic.</span></button>
        <button class="choice" type="button" data-category="Near miss">Near miss<span>A crash almost happened here.</span></button>
        <button class="choice" type="button" data-category="Missing bike connection">Missing bike connection<span>A gap in the network keeps riders from using this route.</span></button>
        <button class="choice" type="button" data-category="Maintenance problem">Maintenance problem<span>Pavement, debris, drainage, signs, or signal timing.</span></button>
      </div>
      <div class="row">
        <button class="button ghost" type="button" data-action="back">Back</button>
        <button class="button" type="button" data-action="choose-location" disabled>Next: place pin</button>
      </div>
    </section>
    <section class="screen" data-screen="location">
      <p class="lead">Click the exact spot on the map. Drag the blue marker if you need to adjust it.</p>
      <div class="step"><strong id="activeCategory">Safety concern</strong><span id="locationStatus">Waiting for a map click.</span></div>
      <div class="row">
        <button class="button ghost" type="button" data-action="back">Back</button>
        <button class="button" type="button" data-action="details" disabled>Next: add details</button>
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
      <div class="row">
        <button class="button ghost" type="button" data-action="back">Back</button>
        <button class="button" type="button" data-action="save">Save pin</button>
      </div>
    </section>
    <section class="screen" data-screen="review">
      <span class="status-pill" id="savedStatus">Saved to the project map</span>
      <p class="lead">Review your mapped comments. You can edit or remove entries submitted from this browser.</p>
      <div class="pin-list" id="pinList"></div>
      <div class="row">
        <button class="button" type="button" data-action="new">Add another pin</button>
      </div>
    </section>
  </aside>
  <section class="map-wrap">
    <div id="map"><div class="fallback-map"></div></div>
    <div class="map-note" id="note">Use the wizard to add a note, photo, and location.</div>
  </section>
</main>
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
let mode = 'browse';
let screen = 'intro';
let draft = {};
let editingId = null;
let draftMarker = null;
let fallbackPins = new Map();
let mapMarkers = new Map();

const titles = {
  intro: 'Start with one bike safety story.',
  category: 'What kind of feedback is this?',
  location: 'Place the pin on the map.',
  details: 'Add the story behind the pin.',
  review: 'Review mapped feedback.'
};
const steps = { intro: 1, category: 2, location: 3, details: 4, review: 4 };

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

function setScreen(next) {
  screen = next;
  document.querySelectorAll('.screen').forEach((node) => node.classList.toggle('active', node.dataset.screen === next));
  document.getElementById('wizardTitle').textContent = titles[next];
  document.getElementById('stepCount').textContent = `${steps[next]} / 4`;
  document.getElementById('progressBar').style.width = `${steps[next] * 25}%`;
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

function beginNew() {
  clearDraftMarker();
  draft = {};
  editingId = null;
  mode = 'browse';
  document.querySelectorAll('.choice').forEach((button) => button.classList.remove('selected'));
  document.querySelector('[data-action="choose-location"]').disabled = true;
  document.querySelector('[data-action="details"]').disabled = true;
  document.getElementById('pinTitle').value = '';
  document.getElementById('pinNote').value = '';
  document.getElementById('pinPhoto').value = '';
  document.getElementById('photoPreview').style.display = 'none';
  setNote('Choose a category, then click the map to place the pin.');
  setScreen('category');
}

function editPin(id) {
  const pin = ownedPins().find((item) => item.id === id);
  if (!pin) return;
  draft = { ...pin };
  editingId = id;
  mode = 'browse';
  document.getElementById('activeCategory').textContent = pin.category;
  document.getElementById('pinTitle').value = pin.title || '';
  document.getElementById('pinNote').value = pin.note || '';
  const preview = document.getElementById('photoPreview');
  preview.src = pin.photo || '';
  preview.style.display = pin.photo ? 'block' : 'none';
  document.querySelector('[data-action="details"]').disabled = false;
  setNote('Editing this pin. Update details, or go back to place it again.');
  setScreen('details');
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
  document.getElementById('locationStatus').textContent = 'Location selected. Continue to add details.';
  document.querySelector('[data-action="details"]').disabled = false;
  setNote('Location selected. Add the story, photo, and label next.');
}

async function saveDraft() {
  const title = document.getElementById('pinTitle').value.trim();
  const note = document.getElementById('pinNote').value.trim();
  const nextPin = {
    ...draft,
    title: title || draft.category,
    note,
    photo_data_url: draft.photo || '',
    client_id: clientId
  };
  if (!nextPin.lng && !nextPin.x) {
    setNote('Place the pin on the map before saving.');
    setScreen('location');
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
    setScreen('review');
    setNote('Concern saved to the project map. Review it, edit it, or add another pin.');
  } catch (error) {
    setNote(error.message);
  }
}

function handleMapClick(event) {
  if (mode !== 'place') return;
  if (event.lngLat) placeDraft(event.lngLat, null);
}

document.querySelectorAll('[data-action]').forEach((button) => {
  button.addEventListener('click', () => {
    const action = button.dataset.action;
    if (action === 'start' || action === 'new') beginNew();
    if (action === 'back') {
      if (screen === 'category') setScreen('intro');
      if (screen === 'location') setScreen('category');
      if (screen === 'details') setScreen('location');
    }
    if (action === 'choose-location') {
      mode = 'place';
      document.getElementById('activeCategory').textContent = draft.category;
      document.getElementById('locationStatus').textContent = 'Click the map to place this concern.';
      setNote('Click the map where this concern happens.');
      setScreen('location');
    }
    if (action === 'details') {
      mode = 'browse';
      setScreen('details');
    }
    if (action === 'save') saveDraft();
  });
});

document.getElementById('categoryList').addEventListener('click', (event) => {
  const button = event.target.closest('.choice');
  if (!button) return;
  document.querySelectorAll('.choice').forEach((node) => node.classList.remove('selected'));
  button.classList.add('selected');
  draft.category = button.dataset.category;
  document.querySelector('[data-action="choose-location"]').disabled = false;
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
    if (mode !== 'place') return;
    const rect = event.currentTarget.getBoundingClientRect();
    placeDraft(null, {
      x: ((event.clientX - rect.left) / rect.width) * 100,
      y: ((event.clientY - rect.top) / rect.height) * 100
    });
  });
}
setNote('Loading public comments...');
loadPins();
</script>"""
    return _layout("Bike Better San Diego Survey", body.replace("__MAPBOX_TOKEN__", token_js))


def app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    query = parse_qs(environ.get("QUERY_STRING", ""))

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
