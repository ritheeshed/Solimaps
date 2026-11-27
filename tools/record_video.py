"""Records the Soli Maps map page as the homepage hero video.

Runs in GitHub Actions (open network, so real map tiles load). Serves the repo
locally, plays a short scripted tour of map.html, and saves the raw recording to
/tmp/rec. The workflow then trims and encodes it with ffmpeg.
"""
import functools, http.server, json, os, threading, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1440, 900

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
handler.log_message = lambda *a: None
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

# a company with openings near OMR to fly to, and a second stop
feeds = json.load(open(os.path.join(ROOT, "feeds.json")))
counts = {}
for j in feeds["jobs"]:
    if str(j.get("a", "")).startswith("co_"):
        counts[j["a"]] = counts.get(j["a"], 0) + 1
prefer = ["co_freshworks", "co_rocketlane", "co_fourkites", "co_detect", "co_kaleidofin", "co_syncfusion"]
stops = [a for a in prefer if counts.get(a)][:2] or sorted(counts, key=counts.get, reverse=True)[:2]
print("stops:", stops)

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                        record_video_dir="/tmp/rec", record_video_size={"width": W, "height": H}, color_scheme="light")
    # pretend to be signed in, so the map never redirects to the homepage
    ctx.add_init_script("""try{localStorage.setItem('soli-user',JSON.stringify({n:'Demo',e:'demo@solimaps.com',p:'',t:Date.now(),k:'demo'}));sessionStorage.setItem('soli-new-x','');}catch(e){}""")
    pg = ctx.new_page()
    t0 = time.time()
    pg.goto("http://127.0.0.1:8765/map.html", wait_until="networkidle", timeout=90000)
    pg.wait_for_timeout(6000)                      # tiles + buildings settle (trimmed off later)
    mark = time.time() - t0
    open("/tmp/rec/start.txt", "w").write(f"{mark:.2f}")
    pg.mouse.move(700, 450)
    pg.wait_for_timeout(2500)                      # overview with logo stacks
    pg.click(".chip[data-c=tech]")                 # filter by role
    pg.wait_for_timeout(2200)
    pg.evaluate(f"setArea('{stops[0]}')")          # fly to the office
    pg.wait_for_timeout(4200)
    pg.hover(".job .apply")                        # hover the first Apply
    pg.wait_for_timeout(1800)
    if len(stops) > 1:
        pg.evaluate(f"setArea('{stops[1]}')")
        pg.wait_for_timeout(4000)
    pg.click(".chip[data-c=tech]")                 # clear the filter
    pg.evaluate("setArea('all')")                  # back to the city
    pg.wait_for_timeout(3500)
    open("/tmp/rec/end.txt", "w").write(f"{time.time() - t0:.2f}")
    ctx.close()
    b.close()
srv.shutdown()
