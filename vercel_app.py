"""Small Vercel-safe demo app.

The full Mapsurvey app uses GeoDjango and requires native GDAL libraries that
Vercel's Python runtime does not provide. This WSGI app keeps the Vercel demo
live while Docker hosts continue to run the full Django/GeoDjango service.
"""

import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs


BASE_DIR = Path(__file__).resolve().parent
MAPBOX_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "")


def _response(start_response, status, body, content_type="text/html; charset=utf-8"):
    payload = body.encode("utf-8") if isinstance(body, str) else body
    start_response(status, [
        ("Content-Type", content_type),
        ("Content-Length", str(len(payload))),
        ("Cache-Control", "public, max-age=60"),
    ])
    return [payload]


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
    .step {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin: 12px 0; background: var(--paper); }}
    .step strong {{ display: block; margin-bottom: 5px; }}
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
      <div class="eyebrow">San Diego County Bicycle Coalition demo</div>
      <h1>Turn rider stories into safer streets.</h1>
      <p class="lead">Collect safety concerns, missing links, route ideas, and everyday barriers in one public map built for fast community workshops.</p>
      <div class="actions">
        <a class="button" href="/survey">Launch the map</a>
        <a class="button secondary" href="https://sdbikecoalition.org/">Visit SDBC</a>
      </div>
    </div>
    <div class="hero-image" role="img" aria-label="Bike and bus street scene"></div>
  </section>
  <section class="band">
    <div class="metrics">
      <div class="metric"><strong>48</strong><span>safety pins collected</span></div>
      <div class="metric"><strong>12</strong><span>corridor ideas ranked</span></div>
      <div class="metric"><strong>6</strong><span>district-ready reports</span></div>
      <div class="metric"><strong>1</strong><span>shareable public link</span></div>
    </div>
  </section>
</main>""")


def _survey():
    token_js = MAPBOX_TOKEN.replace("\\", "\\\\").replace("'", "\\'")
    return _layout("Bike Better San Diego Survey", f"""
<nav class="nav">
  <div class="brand">Bike Better San Diego</div>
  <a href="/">Overview</a>
</nav>
<main class="workspace">
  <aside class="panel">
    <div class="eyebrow">Map safety concerns</div>
    <h1>Drop pins where biking feels unsafe.</h1>
    <p class="lead">Click the map to mark dangerous crossings, near misses, missing bike lanes, or places that keep people from riding.</p>
    <div class="step"><strong>1. Mark a safety concern</strong>Click anywhere on the map to add a red pin.</div>
    <div class="step"><strong>2. Add context</strong>Use this demo during a meeting to talk through the story behind each pin.</div>
    <div class="step"><strong>3. Export priorities</strong>Clustered concerns become a practical advocacy agenda.</div>
    <a class="button" href="/">Back to homepage</a>
  </aside>
  <section class="map-wrap">
    <div id="map"><div class="fallback-map"></div></div>
    <div class="map-note" id="note">Pins are saved in this browser for the demo. Click the map to add another concern.</div>
  </section>
</main>
<script src="https://api.mapbox.com/mapbox-gl-js/v3.10.0/mapbox-gl.js"></script>
<script>
const token = '{token_js}';
const seeded = [
  [-117.1611, 32.7157, 'Downtown crossing stress'],
  [-117.1452, 32.7299, 'Missing protected lane'],
  [-117.2490, 32.7920, 'Beach route pinch point'],
  [-117.1048, 32.7587, 'Fast traffic near school']
];
const saved = JSON.parse(localStorage.getItem('sdbikePins') || '[]');
const pins = seeded.concat(saved);
function savePin(lngLat) {{
  saved.push([lngLat.lng, lngLat.lat, 'Community concern']);
  localStorage.setItem('sdbikePins', JSON.stringify(saved));
}}
function addFallbackPin(x, y) {{
  const pin = document.createElement('div');
  pin.className = 'pin';
  pin.style.left = x + 'px';
  pin.style.top = y + 'px';
  document.querySelector('.map-wrap').appendChild(pin);
}}
if (token && window.mapboxgl) {{
  mapboxgl.accessToken = token;
  const map = new mapboxgl.Map({{
    container: 'map',
    style: 'mapbox://styles/mapbox/streets-v12',
    center: [-117.1611, 32.7157],
    zoom: 11.2
  }});
  map.addControl(new mapboxgl.NavigationControl({{ showCompass: false }}));
  map.on('load', () => {{
    pins.forEach(([lng, lat, label]) => new mapboxgl.Marker({{ color: '#d93636' }})
      .setLngLat([lng, lat])
      .setPopup(new mapboxgl.Popup().setText(label))
      .addTo(map));
  }});
  map.on('click', (event) => {{
    new mapboxgl.Marker({{ color: '#d93636' }}).setLngLat(event.lngLat).addTo(map);
    savePin(event.lngLat);
    document.getElementById('note').textContent = 'Concern added. Add another pin or use this map to discuss priorities.';
  }});
}} else {{
  document.querySelector('.map-wrap').addEventListener('click', (event) => {{
    const rect = event.currentTarget.getBoundingClientRect();
    addFallbackPin(event.clientX - rect.left, event.clientY - rect.top);
    document.getElementById('note').textContent = 'Concern added. Add another pin or use this map to discuss priorities.';
  }});
  [[62,48],[45,36],[72,62],[55,70]].forEach(([x,y]) => {{
    const wrap = document.querySelector('.map-wrap');
    addFallbackPin(wrap.clientWidth * x / 100, wrap.clientHeight * y / 100);
  }});
}}
</script>""")


def app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    query = parse_qs(environ.get("QUERY_STRING", ""))

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
