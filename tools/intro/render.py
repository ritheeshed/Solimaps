"""Renders tools/intro/intro.html to assets/intro.mp4 / .webm / .jpg, frame by frame.

Needs: playwright + chromium, ffmpeg, and assets/hero.mp4 (the real map recording made by
tools/record_video.py). Usage: python tools/intro/render.py [chrome-executable]
"""
import datetime, functools, glob, http.server, json, os, re, shutil, subprocess, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = "/tmp/intro"
FPS = 30
shutil.rmtree(TMP, ignore_errors=True)
for d in ("frames/a", "frames/b", "out"):
    os.makedirs(os.path.join(TMP, d))

# real map footage: the city overview, then the fly-in to the office
hero = os.path.join(ROOT, "assets", "hero.mp4")
for name, start, dur in (("a", 0.0, 3.8), ("b", 10.3, 4.2)):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(dur), "-i", hero,
                    "-vf", f"fps={FPS},scale=1600:-2", "-q:v", "3", os.path.join(TMP, "frames", name, "%04d.jpg")], check=True)

feeds = json.load(open(os.path.join(ROOT, "feeds.json")))
cos = json.load(open(os.path.join(ROOT, "companies.json")))["companies"]
logos = feeds.get("logos", {})
office = {c["name"]: c.get("office", "") for c in cos}
PLACES = ["IIT Madras Research Park", "Perungudi", "Taramani", "Guindy", "Thoraipakkam", "Sholinganallur", "Siruseri",
          "Ambattur", "Velachery", "Porur", "Manapakkam", "Nungambakkam", "Teynampet", "Anna Salai", "Alandur", "Ekkaduthangal", "Adyar"]
def place(name):
    o = office.get(name, "")
    for p in PLACES:
        if p.lower() in o.lower():
            return p + (", OMR" if p in ("Perungudi", "Thoraipakkam", "Sholinganallur", "Siruseri") else "")
    return "Chennai"
today = datetime.date.today()
def when(d):
    n = (today - datetime.date.fromisoformat(d)).days
    return "today" if n <= 0 else "yesterday" if n == 1 else f"{n} days ago"
careers = [j for j in feeds["jobs"] if j.get("src") == "Company careers" and logos.get(j["c"], "").endswith((".png", ".svg", ".webp"))]
careers.sort(key=lambda j: j["d"], reverse=True)
def pick(company):
    js = [j for j in careers if j["c"] == company]
    return js[0] if js else None
job = pick("Freshworks") or careers[0]
job2 = next((j for j in careers if j["c"] != job["c"] and place(j["c"]) != "Chennai"), careers[1])
order = ["Freshworks", "Rocketlane", "Uniphore", "FourKites", "Kaleidofin", "Detect Technologies", "Syncfusion", "Disprz"]
tiles = [logos[c] for c in order if c in logos and any(j["c"] == c for j in careers)][:6]
area = place(job["c"]).split(",")[-1].strip()
data = {
    "query": f"Product jobs near {area}",
    "filter": f"{area} · Product",
    "pages": len(cos),
    "reply": f"Here are real openings near {area}, straight from the companies.",
    "job": {"t": job["t"], "c": job["c"], "place": place(job["c"]), "logo": logos[job["c"]], "when": when(job["d"]), "host": f"the {job['c']} careers page"},
    "job2": {"t": job2["t"], "c": job2["c"], "place": place(job2["c"]), "logo": logos[job2["c"]]},
    "logos": tiles,
    "office": "Office pinned · " + (office.get(job["c"], "").split(",")[0] or place(job["c"])),
    "frames": {k: [f"/__frames/{k}/{os.path.basename(p)}" for p in sorted(glob.glob(os.path.join(TMP, "frames", k, "*.jpg")))] for k in ("a", "b")},
}
print(json.dumps({k: v for k, v in data.items() if k != "frames"}, ensure_ascii=False, indent=1))

class H(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith("/__frames/"):
            return os.path.join(TMP, "frames", path[len("/__frames/"):].split("?")[0])
        return super().translate_path(path)
    def log_message(self, *a):
        pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8790), functools.partial(H, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()

with sync_playwright() as p:
    kw = {"executable_path": sys.argv[1]} if len(sys.argv) > 1 else {}
    b = p.chromium.launch(args=["--force-color-profile=srgb"], **kw)
    pg = b.new_page(viewport={"width": 1600, "height": 800}, device_scale_factor=1)
    pg.add_init_script("window.DATA=" + json.dumps(data))
    pg.goto("http://127.0.0.1:8790/tools/intro/intro.html")
    pg.evaluate("document.fonts.ready")
    pg.evaluate("preload()")
    pg.wait_for_timeout(500)
    n = int(pg.evaluate("DURATION") * FPS)
    for i in range(n):
        pg.evaluate(f"render({i / FPS})")
        pg.screenshot(path=os.path.join(TMP, "out", f"{i:04d}.jpg"), type="jpeg", quality=92)
    b.close()
srv.shutdown()

src = os.path.join(TMP, "out", "%04d.jpg")
assets = os.path.join(ROOT, "assets")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", src, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", os.path.join(assets, "intro.mp4")], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", src, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "36",
                "-row-mt", "1", "-deadline", "good", "-cpu-used", "4", os.path.join(assets, "intro.webm")], check=True)
shutil.copy(os.path.join(TMP, "out", f"{int(12.6 * FPS):04d}.jpg"), os.path.join(assets, "intro.jpg"))
print("done", n, "frames")
