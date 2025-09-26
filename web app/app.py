from flask import Flask, render_template, request, jsonify
import time, math, threading, random, os, atexit

app = Flask(__name__)

# -----------------------------
# Config
# -----------------------------
PORT = int(os.getenv("PORT", "5000"))
HOST = os.getenv("HOST", "0.0.0.0")

# Selected kind threshold used for filtering & routing
COLLECT_THRESHOLD = 80

# Optional: random simulation of bin changes
SIMULATE_BINS = os.getenv("SIMULATE_BINS", "0") in ("1", "true", "True", "yes")
SIM_TICK = int(os.getenv("SIM_TICK", "15"))
SIM_STEP_MIN, SIM_STEP_MAX = -3, 6

KINDS = ["plastic", "organic", "metal", "bread", "paper", "glass"]

# -----------------------------
# In-memory demo data (Sfax)
# Each bin has "comps": per-kind fullness (0..100)
# -----------------------------
bins = [
    {
        "id": 1, "name": "Bin A - Centre", "lat": 34.7402, "lon": 10.7600,
        "active": True, "priority": 0, "battery": 90,
        "comps": {"plastic": 80, "organic": 40, "metal": 12, "bread": 18, "paper": 40, "glass": 22}
    },
    {
        "id": 2, "name": "Bin B - Médina", "lat": 34.7390, "lon": 10.7608,
        "active": True, "priority": 1, "battery": 55,
        "comps": {"plastic": 90, "organic": 80, "metal": 8, "bread": 12, "paper": 25, "glass": 85}
    },
    {
        "id": 3, "name": "Bin C - Sakiet", "lat": 34.7550, "lon": 10.7280,
        "active": True, "priority": 0, "battery": 72,
        "comps": {"plastic": 96, "organic": 96, "metal": 6, "bread": 9, "paper": 90, "glass": 14}
    },
    {
        "id": 4, "name": "Bin D - Route GP1", "lat": 34.7295, "lon": 10.7505,
        "active": True, "priority": 3, "battery": 40,
        "comps": {"plastic": 80, "organic": 85, "metal": 5, "bread": 7, "paper": 32, "glass": 18}
    },
    {
        "id": 5, "name": "Bin E - Port", "lat": 34.7280, "lon": 10.7795,
        "active": True, "priority": 1, "battery": 65,
        "comps": {"plastic": 80, "organic": 80, "metal": 10, "bread": 13, "paper": 20, "glass": 45}
    },
    {
        "id": 6, "name": "Bin F - Université", "lat": 34.7328, "lon": 10.7078,
        "active": True, "priority": 0, "battery": 100,
        "comps": {"plastic": 80, "organic": 80, "metal": 4, "bread": 6, "paper": 87, "glass": 26}
    },
]

# Live truck locations: { "truck-1": {"lat":..., "lon":..., "t": epoch}, ... }
truck_locations = {}

# -----------------------------
# Geo helpers + simple TSP-ish planner
# -----------------------------
def haversine(a, b):
    R = 6371000.0
    la1, lo1 = math.radians(a[0]), math.radians(a[1])
    la2, lo2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = la2 - la1, lo2 - lo1
    s = math.sin(dlat/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(s))

def nearest_neighbor(start, pts):
    rem = pts[:]; out = []; cur = start
    while rem:
        nxt = min(rem, key=lambda p: haversine(cur, (p["lat"], p["lon"])))
        out.append(nxt); cur = (nxt["lat"], nxt["lon"]); rem.remove(nxt)
    return out

def two_opt(order, start):
    def length(seq):
        cur = start; d = 0.0
        for p in seq:
            d += haversine(cur, (p["lat"], p["lon"]))
            cur = (p["lat"], p["lon"])
        return d
    best = order[:]; best_len = length(best); improved = True
    while improved:
        improved = False
        for i in range(len(best)-1):
            for j in range(i+1, len(best)):
                cand = best[:i] + best[i:j+1][::-1] + best[j+1:]
                d = length(cand)
                if d + 1e-6 < best_len:
                    best, best_len, improved = cand, d, True
        if len(best) > 100:  # safety for very long lists
            break
    return best

# -----------------------------
# Pages
# -----------------------------
@app.route("/")
def index():
    return """
    <h2>Smart Waste — Multi-compartment demo</h2>
    <ul>
      <li><a href="/phone?truck=truck-1">/phone?truck=truck-1</a> (open on phone)</li>
      <li><a href="/map">/map</a> (open on PC)</li>
    </ul>
    """

@app.route("/phone")
def phone():
    return render_template("phone.html")

@app.route("/map")
def map_page():
    return render_template("map.html")

# -----------------------------
# APIs
# -----------------------------
@app.route("/update", methods=["POST"])
def update():
    """Body: { truck:'truck-1', lat: <float>, lon: <float> }"""
    data = request.get_json(force=True) or {}
    truck = data.get("truck", "truck-1")
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        return jsonify({"error": "lat/lon required"}), 400
    truck_locations[truck] = {"lat": float(lat), "lon": float(lon), "t": int(time.time())}
    return "", 200

@app.route("/latest")
def latest():
    """?truck=truck-1 -> that truck, else all trucks"""
    q = request.args.get("truck")
    if q:
        d = truck_locations.get(q)
        if not d:
            return jsonify({"truck": q, "lat": None, "lon": None, "t": None})
        out = dict(d); out["truck"] = q; return jsonify(out)
    return jsonify(truck_locations)

@app.route("/bins", methods=["GET"])
def get_bins():
    """
    Filters:
      ?active=1
      ?kind=plastic|organic|metal|bread|paper|glass   (controls display_fullness & filtering)
      ?min_fullness=80                               (applies to selected kind only)
    Returns:
      - comps: full per-kind dict (ints)
      - display_fullness: % used for the marker label/color (selected kind, or max across kinds if none)
    """
    res = bins
    if request.args.get("active") == "1":
        res = [b for b in res if b["active"]]

    kind = request.args.get("kind", "")
    if kind and kind not in KINDS:
        return jsonify({"error": f"unknown kind: {kind}"}), 400

    mf_val = None
    if "min_fullness" in request.args:
        try:
            mf_val = int(request.args["min_fullness"])
        except ValueError:
            return jsonify({"error": "min_fullness must be int"}), 400

    out = []
    for b in res:
        # normalize comps to ints
        comps = {k: int(b.get("comps", {}).get(k, 0)) for k in KINDS}

        if kind:
            val = comps[kind]  # selected kind drives marker label
            if mf_val is not None and val < mf_val:
                continue
            display_fullness = val
        else:
            display_fullness = max(comps.values()) if comps else 0

        out.append({
            "id": b["id"], "name": b["name"], "lat": b["lat"], "lon": b["lon"],
            "active": b["active"], "priority": b["priority"], "battery": int(b.get("battery", 0)),
            "comps": comps, "display_fullness": int(display_fullness)
        })
    return jsonify(out)

@app.route("/collect", methods=["POST"])
def collect():
    """
    Body: { bin_id: <int>, kind: <one of KINDS> }
    Sets only that compartment's fullness to 0.
    """
    data = request.get_json(force=True) or {}
    bin_id = data.get("bin_id")
    kind = data.get("kind")
    if kind not in KINDS:
        return jsonify({"error": "kind required/invalid"}), 400

    b = next((x for x in bins if x["id"] == bin_id), None)
    if not b:
        return jsonify({"error":"bin not found"}), 404

    b["comps"][kind] = 0
    return jsonify({"ok": True})

@app.route("/route", methods=["POST"])
def route():
    """
    Body: { truck:'truck-1', kind:'paper', active:1 }
    Builds a tour over bins where selected kind >= COLLECT_THRESHOLD.
    """
    data  = request.get_json(force=True) or {}
    truck = data.get("truck", "truck-1")
    kind  = data.get("kind", "")
    active_only = int(data.get("active", 1)) == 1

    if kind not in KINDS:
        return jsonify({"error": "kind is required and must be one of " + ",".join(KINDS)}), 400

    loc = truck_locations.get(truck)
    if not loc or loc.get("lat") is None:
        return jsonify({"error": "truck has no location"}), 400

    eligible = []
    for b in bins:
        if active_only and not b["active"]:
            continue
        val = int(b["comps"].get(kind, 0))
        if val >= COLLECT_THRESHOLD:
            eligible.append({
                "id": b["id"], "name": b["name"], "lat": b["lat"], "lon": b["lon"],
                "fullness": val, "kind": kind
            })

    if not eligible:
        return jsonify({"ordered": [], "meters": 0, "threshold": COLLECT_THRESHOLD})

    start = (loc["lat"], loc["lon"])

    order = nearest_neighbor(start, eligible)
    order = two_opt(order, start)

    cur = start; total = 0.0
    for p in order:
        total += haversine(cur, (p["lat"], p["lon"]))
        cur = (p["lat"], p["lon"])

    return jsonify({"ordered": order, "meters": int(total), "threshold": COLLECT_THRESHOLD})

@app.route("/bins/<int:bin_id>", methods=["PATCH"])
def patch_bin(bin_id):
    """
    Update a bin. Supports:
      - name, lat, lon, active, priority, battery
      - comps: { plastic: int, organic: int, ... } (only provided keys updated)
    """
    b = next((x for x in bins if x["id"] == bin_id), None)
    if not b:
        return jsonify({"error": "bin not found"}), 404
    data = request.get_json(force=True) or {}

    for f in ["name", "lat", "lon", "active", "priority", "battery"]:
        if f in data:
            b[f] = data[f]

    if "comps" in data and isinstance(data["comps"], dict):
        for k, v in data["comps"].items():
            if k in KINDS:
                try:
                    b["comps"][k] = int(v)
                except Exception:
                    pass

    return "", 204

@app.route("/health")
def health():
    return jsonify({"ok": True, "time": int(time.time())})

# -----------------------------
# Background simulation (optional)
# -----------------------------
_stop_sim = threading.Event()

def _clamp(x, lo, hi): return lo if x < lo else (hi if x > hi else x)

def simulate_bins_loop():
    while not _stop_sim.is_set():
        for b in bins:
            if not b.get("active", True): continue
            # random-walk each compartment and battery drain
            for k in KINDS:
                step = random.randint(SIM_STEP_MIN, SIM_STEP_MAX)
                b["comps"][k] = _clamp(b["comps"][k] + step, 0, 100)
            b["battery"] = _clamp(b.get("battery", 100) - random.randint(0, 2), 0, 100)
        _stop_sim.wait(SIM_TICK)

@atexit.register
def _on_exit():
    _stop_sim.set()

# -----------------------------
# Run
# -----------------------------
if __name__ == "__main__":
    print("Smart Waste server starting… Bins:", len(bins))
    if SIMULATE_BINS:
        print(f"🔁 Bin simulation enabled (every {SIM_TICK}s). Set SIMULATE_BINS=0 to disable.")
        threading.Thread(target=simulate_bins_loop, daemon=True).start()
    else:
        print("🔁 Bin simulation disabled. Enable with SIMULATE_BINS=1")
    app.run(host=HOST, port=PORT, debug=True, use_reloader=False)