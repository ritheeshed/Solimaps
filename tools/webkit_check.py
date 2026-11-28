"""Opens the live map in WebKit (Safari engine) as an iPhone and saves what went wrong."""
import json, os
from playwright.sync_api import sync_playwright
os.makedirs("debug", exist_ok=True)
log = {"console": [], "failed": [], "tiles": 0}
with sync_playwright() as p:
    b = p.webkit.launch()
    ctx = b.new_context(**p.devices["iPhone 13"], color_scheme="dark")
    pg = ctx.new_page()
    pg.on("console", lambda m: log["console"].append(f"{m.type}: {m.text}"[:300]))
    pg.on("pageerror", lambda e: log["console"].append(f"pageerror: {e}"[:300]))
    pg.on("requestfailed", lambda r: log["failed"].append(f"{r.url[:120]} {r.failure}"))
    pg.on("response", lambda r: log.__setitem__("tiles", log["tiles"] + (1 if "openfreemap" in r.url and r.url.endswith(".pbf") else 0)))
    pg.goto("https://solimaps.github.io/map.html?v=" + os.environ.get("GITHUB_SHA", "x")[:7], wait_until="load")
    pg.wait_for_timeout(9000)
    log["state"] = pg.evaluate("""()=>{const c=document.querySelector('#map canvas');let gl=null;try{gl=c&&(c.getContext('webgl2')||c.getContext('webgl'))}catch(e){}
      return {canvas:c?[c.width,c.height,c.clientWidth,c.clientHeight]:null, gl:!!gl, lost:gl?gl.isContextLost():null, mapH:document.querySelector('#map').clientHeight}}""")
    pg.screenshot(path="debug/webkit-iphone.png")
    b.close()
json.dump(log, open("debug/webkit-iphone.json", "w"), indent=1)
print(json.dumps(log, indent=1)[:4000])
