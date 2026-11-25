"""Daily job fetcher for Soli Maps.

Pulls Chennai white-collar jobs from:
  * Google for Jobs, via OpenWeb Ninja JSearch (needs the JSEARCH_KEY secret)
  * company career pages that publish public job feeds
    (Greenhouse, Lever, SmartRecruiters, Workday)
and writes feeds.json, which the site merges with jobs.json (Indeed) and posts.json (employer posts).

Standard library only, so the GitHub Action needs no installs.
"""
import json, os, re, sys, time, math, datetime, urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
TODAY = datetime.datetime.now(IST).date()
MAX_AGE = 90
UA = "SoliMaps/1.0 (+https://ritheeshed.github.io/Solimaps/)"
LOG = []

# ---------- places: known Chennai localities (centre points, en/ta names) ----------
EXTRA_AREAS = {
    "velachery": ("Velachery", "வேளச்சேரி", 12.9815, 80.2180),
    "thoraipakkam": ("Thoraipakkam", "துரைப்பாக்கம்", 12.9416, 80.2362),
    "siruseri": ("Siruseri", "சிறுசேரி", 12.8263, 80.2186),
    "navalur": ("Navalur", "நாவலூர்", 12.8459, 80.2265),
    "karapakkam": ("Karapakkam", "காரப்பாக்கம்", 12.9146, 80.2295),
    "kelambakkam": ("Kelambakkam", "கேளம்பாக்கம்", 12.7870, 80.2205),
    "ambattur": ("Ambattur", "அம்பத்தூர்", 13.1143, 80.1548),
    "porur": ("Porur", "போரூர்", 13.0382, 80.1565),
    "annanagar": ("Anna Nagar", "அண்ணா நகர்", 13.0850, 80.2101),
    "tnagar": ("T Nagar", "தி. நகர்", 13.0418, 80.2341),
    "adyar": ("Adyar", "அடையாறு", 13.0012, 80.2565),
    "alwarpet": ("Alwarpet", "ஆழ்வார்பேட்டை", 13.0336, 80.2550),
    "mylapore": ("Mylapore", "மயிலாப்பூர்", 13.0368, 80.2676),
    "perambur": ("Perambur", "பெரம்பூர்", 13.1210, 80.2329),
    "chromepet": ("Chromepet", "குரோம்பேட்டை", 12.9516, 80.1462),
    "pallavaram": ("Pallavaram", "பல்லாவரம்", 12.9675, 80.1491),
    "ekkatuthangal": ("Ekkatuthangal", "ஈக்காட்டுத்தாங்கல்", 13.0186, 80.2056),
    "saidapet": ("Saidapet", "சைதாப்பேட்டை", 13.0213, 80.2231),
    "vadapalani": ("Vadapalani", "வடபழனி", 13.0500, 80.2121),
    "royapettah": ("Royapettah", "ராயப்பேட்டை", 13.0540, 80.2640),
    "kilpauk": ("Kilpauk", "கீழ்ப்பாக்கம்", 13.0827, 80.2420),
    "ashoknagar": ("Ashok Nagar", "அசோக் நகர்", 13.0359, 80.2120),
    "madipakkam": ("Madipakkam", "மடிப்பாக்கம்", 12.9647, 80.1961),
    "medavakkam": ("Medavakkam", "மேடவாக்கம்", 12.9200, 80.1920),
    "avadi": ("Avadi", "ஆவடி", 13.1067, 80.1013),
    "poonamallee": ("Poonamallee", "பூந்தமல்லி", 13.0473, 80.0945),
    "thiruvanmiyur": ("Thiruvanmiyur", "திருவான்மியூர்", 12.9830, 80.2594),
    "besantnagar": ("Besant Nagar", "பெசன்ட் நகர்", 13.0003, 80.2667),
}
ALIASES = {"tharamani": "taramani", "t. nagar": "tnagar", "t.nagar": "tnagar", "thyagaraya nagar": "tnagar",
           "omr": None, "sipcot": "siruseri", "chengalpet": None, "mount road": None, "anna salai": None}


def load_json(name, default):
    try:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


BASE = load_json("jobs.json", {"areas": {}})
AREAS = dict(BASE.get("areas", {}))
NEW_AREAS = {}
for k, (en, ta, la, lo) in EXTRA_AREAS.items():
    if k not in AREAS:
        NEW_AREAS[k] = {"en": en, "ta": ta, "lat": la, "lon": lo}
ALL_AREAS = {**AREAS, **NEW_AREAS}
NAME_TO_KEY = {}
for k, v in ALL_AREAS.items():
    NAME_TO_KEY[v["en"].lower().replace(" district", "").replace(" (gpo)", "")] = k
for a, k in ALIASES.items():
    if k:
        NAME_TO_KEY[a] = k
CHENNAI_WORDS = ["chennai", "madras", "sriperumbudur", "oragadam", "siruseri", "tambaram", "chengalpattu",
                 "thiruvallur", "tiruvallur", "kanchipuram", "kancheepuram", "ambattur", "guindy", "sholinganallur",
                 "perungudi", "navalur", "kelambakkam", "porur", "velachery", "taramani", "tharamani", "avadi",
                 "poonamallee", "mahindra world city", "irungattukottai"]


def area_of(text):
    t = (text or "").lower()
    best = ""
    for name in sorted(NAME_TO_KEY, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name) + r"\b", t):
            best = NAME_TO_KEY[name]
            break
    return best


def in_chennai(text):
    t = (text or "").lower()
    return any(w in t for w in CHENNAI_WORDS) or bool(area_of(t))


# ---------- role filters ----------
BLUE = ["driver", "delivery boy", "delivery executive", "delivery partner", "rider", "helper", "machine operator",
        "security guard", "housekeeping", "house keeping", "cleaner", "loader", "packer", "picker", "welder", "fitter",
        "plumber", "electrician", "cook", "waiter", "steward", "peon", "office boy", "telecaller", "tele caller",
        "warehouse associate", "warehouse helper", "cnc operator", "lathe", "mason", "carpenter", "tailor", "beautician"]
RULES = [
    ("intern", ["intern", "internship", "student job", "apprentice"]),
    ("health", ["nurse", "nursing", "doctor", "physician", "pharmac", "clinical", "hospital", "medical officer",
                "dentist", "dental", "physiotherap", "radiolog", "lab technician", "healthcare assistant"]),
    ("edu", ["teacher", "professor", "lecturer", "faculty", "tutor", "educator", "school", "principal", "academic",
             "trainer"]),
    ("eng", ["mechanical", "civil engineer", "electrical engineer", "manufacturing", "production engineer",
             "quality engineer", "design engineer", "fea", "cad ", "hvac", "plant ", "process engineer",
             "project engineer", "maintenance engineer", "automotive", "piping", "structural", "inspection",
             "embedded", "hardware", "dfma", "project controls"]),
    ("des", ["designer", "ui/ux", "ux ", "ux/", "graphic", "visual", "motion", "illustrator", "art director",
             "creative"]),
    ("data", ["data analyst", "data scientist", "analytics", "business intelligence", "bi analyst", "data engineer",
              "machine learning", "ml engineer", "ai engineer", "reporting analyst", "data management"]),
    ("hr", ["recruit", "talent acquisition", "human resource", "hr ", "hr-", "payroll", "people partner",
            "hrbp", "talent sourcer"]),
    ("fin", ["account", "finance", "financial", "audit", "tax", "payable", "receivable", "treasury", "controller",
             "ledger", "chartered", "credit analyst", "fp&a", "billing"]),
    ("mkt", ["marketing", "sales", "business development", "account executive", "account manager", "brand", "seo",
             "content", "social media", "growth", "public relations", "pre-sales", "presales", "solution engineer",
             "solutions engineer", "deal desk", "partnerships"]),
    ("tech", ["software", "developer", "engineer", "devops", "sre", "qa", "test", "frontend", "front-end", "backend",
              "full stack", "fullstack", "cloud", "security", "it support", "sap", "salesforce", "programmer",
              "architect", "technical", "product owner", "product manager", "program manager", "scrum"]),
]


def categorise(title):
    t = " " + (title or "").lower() + " "
    if "account executive" in t or "account manager" in t:
        return "mkt"
    for cat, words in RULES:
        if any(w in t for w in words):
            return cat
    return "ops"


def blue_collar(title):
    t = (title or "").lower()
    return any(w in t for w in BLUE)


# ---------- http ----------
def get(url, data=None, headers=None, timeout=30):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def iso_date(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(IST).date().isoformat()
    except Exception:
        return TODAY.isoformat()


def rel_date(s):
    m = re.search(r"(\d+)\+?\s*day", (s or "").lower())
    if m:
        return (TODAY - datetime.timedelta(days=int(m.group(1)))).isoformat()
    return TODAY.isoformat()


def tidy(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


JOBS = []


def add(title, company, loc_text, date, jtype, url, src, area=None):
    title, company = tidy(title), tidy(company)
    if not title or not url or blue_collar(title):
        return
    if (TODAY - datetime.date.fromisoformat(date)).days > MAX_AGE:
        return
    JOBS.append({"t": title, "c": company or "Company not named", "a": area if area is not None else area_of(loc_text),
                 "d": date, "ty": jtype or "", "cat": categorise(title), "u": url, "src": src})


# ---------- source: Google for Jobs via JSearch ----------
JSEARCH_QUERIES = [
    "software developer jobs in Chennai", "marketing jobs in Chennai", "sales jobs in Chennai",
    "data analyst jobs in Chennai", "accountant jobs in Chennai", "HR recruiter jobs in Chennai",
    "customer support jobs in Chennai", "mechanical engineer jobs in Chennai", "designer jobs in Chennai",
    "teacher jobs in Chennai", "nurse jobs in Chennai", "fresher jobs in Chennai", "internship in Chennai",
    "manager jobs in Chennai", "business analyst jobs in Chennai", "engineer jobs in Sriperumbudur",
    "jobs in Sholinganallur Chennai", "jobs in Guindy Chennai", "jobs in Ambattur Chennai", "jobs in Tambaram",
]
CITY_CENTRE = (13.0827, 80.2707)


def nearest_area(la, lo, max_km=2.5):
    best, bd = "", 1e9
    for k, v in ALL_AREAS.items():
        d = math.hypot((v["lat"] - la) * 111, (v["lon"] - lo) * 108)
        if d < bd:
            best, bd = k, d
    return best if bd <= max_km else ""


def fetch_jsearch():
    key = os.environ.get("JSEARCH_KEY", "").strip()
    if not key:
        LOG.append("jsearch: skipped (no JSEARCH_KEY secret)")
        return
    limit = int(os.environ.get("JSEARCH_QUERIES", "6"))
    n0 = len(JOBS)
    day = TODAY.toordinal()
    qs = [JSEARCH_QUERIES[(day * limit + i) % len(JSEARCH_QUERIES)] for i in range(limit)] if limit < len(JSEARCH_QUERIES) else JSEARCH_QUERIES
    for q in qs:
        url = "https://api.openwebninja.com/jsearch/search?" + urllib.parse.urlencode(
            {"query": q, "page": 1, "num_pages": 1, "country": "in", "date_posted": "month"})
        try:
            res = get(url, headers={"x-api-key": key})
        except Exception as e:
            LOG.append(f"jsearch: '{q}' failed: {e}")
            continue
        for j in res.get("data") or []:
            loc = ", ".join(x for x in [j.get("job_location"), j.get("job_city"), j.get("job_state")] if x)
            if not in_chennai(loc):
                continue
            area = area_of(loc)
            la, lo = j.get("job_latitude"), j.get("job_longitude")
            if not area and isinstance(la, (int, float)) and isinstance(lo, (int, float)):
                if math.hypot((la - CITY_CENTRE[0]) * 111, (lo - CITY_CENTRE[1]) * 108) > 1.5:
                    area = nearest_area(la, lo)
            date = iso_date(j["job_posted_at_datetime_utc"]) if j.get("job_posted_at_datetime_utc") else rel_date(j.get("job_posted_at"))
            add(j.get("job_title"), j.get("employer_name"), loc, date, (j.get("job_employment_type") or "").title().replace("Fulltime", "Full-time"),
                j.get("job_apply_link"), j.get("job_publisher") or "Google for Jobs", area)
        time.sleep(1)
    LOG.append(f"jsearch: {len(JOBS) - n0} jobs from {len(qs)} searches")


# ---------- source: company career pages ----------
GREENHOUSE = ["fourkites", "mitsogoinc", "neysanetwork", "project44", "chargebee", "kissflow", "zuora", "gupshup"]
LEVER = ["valgenesis", "equativ", "facilio", "saasworthy"]
SMARTRECRUITERS = ["Freshworks", "Visa", "BoschGroup", "Ramco"]
WORKDAY = [  # host, tenant, site, company name
    ("workday.wd5.myworkdayjobs.com", "workday", "Workday", "Workday"),
    ("cat.wd5.myworkdayjobs.com", "cat", "CaterpillarCareers", "Caterpillar"),
    ("ford.wd1.myworkdayjobs.com", "ford", "FordCareers", "Ford"),
    ("pfizer.wd1.myworkdayjobs.com", "pfizer", "PfizerCareers", "Pfizer"),
    ("hcltech.wd3.myworkdayjobs.com", "hcltech", "HCLTechCareers", "HCLTech"),
]


def fetch_greenhouse():
    for tok in GREENHOUSE:
        n0 = len(JOBS)
        try:
            res = get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs")
            board = get(f"https://boards-api.greenhouse.io/v1/boards/{tok}")
            name = board.get("name") or tok
        except Exception as e:
            LOG.append(f"greenhouse {tok}: {e}")
            continue
        for j in res.get("jobs", []):
            loc = (j.get("location") or {}).get("name", "")
            if in_chennai(loc):
                add(j.get("title"), name, loc, iso_date(j.get("first_published") or j.get("updated_at")), "", j.get("absolute_url"), "Company careers")
        LOG.append(f"greenhouse {tok}: {len(JOBS) - n0} Chennai jobs")


def fetch_lever():
    for tok in LEVER:
        n0 = len(JOBS)
        try:
            res = get(f"https://api.lever.co/v0/postings/{tok}?mode=json")
        except Exception as e:
            LOG.append(f"lever {tok}: {e}")
            continue
        for j in res if isinstance(res, list) else []:
            cats = j.get("categories") or {}
            loc = " ".join([cats.get("location") or ""] + (cats.get("allLocations") or []))
            if in_chennai(loc):
                d = datetime.datetime.fromtimestamp((j.get("createdAt") or 0) / 1000, IST).date().isoformat() if j.get("createdAt") else TODAY.isoformat()
                add(j.get("text"), tok.title(), loc, d, cats.get("commitment") or "", j.get("hostedUrl"), "Company careers")
        LOG.append(f"lever {tok}: {len(JOBS) - n0} Chennai jobs")


def fetch_smartrecruiters():
    for co in SMARTRECRUITERS:
        n0 = len(JOBS)
        offset = 0
        try:
            while True:
                res = get(f"https://api.smartrecruiters.com/v1/companies/{co}/postings?city=Chennai&limit=100&offset={offset}")
                items = res.get("content", [])
                for j in items:
                    loc = j.get("location") or {}
                    lt = ", ".join(str(loc.get(k) or "") for k in ("city", "region", "country"))
                    if in_chennai(lt):
                        add(j.get("name"), (j.get("company") or {}).get("name") or co, lt, iso_date(j.get("releasedDate")),
                            ((j.get("typeOfEmployment") or {}).get("label") or ""), f"https://jobs.smartrecruiters.com/{co}/{j.get('id')}", "Company careers")
                offset += len(items)
                if not items or offset >= res.get("totalFound", 0) or offset >= 500:
                    break
        except Exception as e:
            LOG.append(f"smartrecruiters {co}: {e}")
            continue
        LOG.append(f"smartrecruiters {co}: {len(JOBS) - n0} Chennai jobs")


def fetch_workday():
    for host, tenant, site, name in WORKDAY:
        n0 = len(JOBS)
        try:
            off = 0
            while off < 200:
                res = get(f"https://{host}/wday/cxs/{tenant}/{site}/jobs", data={"appliedFacets": {}, "limit": 20, "offset": off, "searchText": "Chennai"})
                posts = res.get("jobPostings", [])
                for j in posts:
                    loc = j.get("locationsText") or ""
                    if in_chennai(loc) or in_chennai(j.get("title", "")):
                        add(j.get("title"), name, loc, rel_date(j.get("postedOn")), "", f"https://{host}/{site}{j.get('externalPath', '')}", "Company careers")
                off += 20
                if len(posts) < 20:
                    break
        except Exception as e:
            LOG.append(f"workday {name}: {e}")
            continue
        LOG.append(f"workday {name}: {len(JOBS) - n0} Chennai jobs")


# ---------- source: Chennai startup directory (companies.json) ----------
import html as htmlmod
from urllib.parse import urljoin, urlparse

DIRECTORY = load_json("companies.json", {"companies": []}).get("companies", [])
GEO_CACHE = load_json("geo_cache.json", {})
PREV = {j.get("u"): j.get("d") for j in (load_json("feeds.json", {}) or {}).get("jobs", []) if j.get("u")}
CO_AREAS = {}
APPROX = set()
HTML_UA = {"User-Agent": "Mozilla/5.0 (compatible; SoliMapsBot/1.0; +https://ritheeshed.github.io/Solimaps/)",
           "Accept": "text/html,application/xhtml+xml"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def fetch_html(url, timeout=25):
    req = urllib.request.Request(url, headers=HTML_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(3_000_000)
        return raw.decode(r.headers.get_content_charset() or "utf-8", "replace"), r.geturl()


def nominatim(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "in", "viewbox": "79.6,13.5,80.6,12.5", "bounded": 1})
    res = get(url, headers={"Referer": "https://ritheeshed.github.io/Solimaps/"})
    if res:
        return {"lat": float(res[0]["lat"]), "lon": float(res[0]["lon"]), "name": res[0].get("display_name", "")[:160], "t": TODAY.isoformat()}
    return {"miss": True, "t": TODAY.isoformat()}


def geocode_directory():
    looked = 0
    for c in DIRECTORY:
        if isinstance(c.get("lat"), (int, float)) and isinstance(c.get("lon"), (int, float)):
            CO_AREAS[c["id"]] = (c["lat"], c["lon"])
            continue
        qs = c.get("geo") or []
        qs = [qs] if isinstance(qs, str) else qs
        qs = [q.strip() for q in qs if q and q.strip()]
        if not qs:
            continue
        found = None
        approx = False
        for q in qs:
            approx = q.startswith("~")
            q = q.lstrip("~").strip()
            hit = GEO_CACHE.get(q)
            stale = hit and hit.get("miss") and (TODAY - datetime.date.fromisoformat(hit.get("t", "2000-01-01"))).days > 14
            if hit is None or stale:
                if looked:
                    time.sleep(1.2)
                looked += 1
                try:
                    hit = nominatim(q)
                except Exception as e:
                    LOG.append(f"geocode '{q}': {e}")
                    continue
                GEO_CACHE[q] = hit
            if hit and not hit.get("miss"):
                found = hit
                break
        if found:
            CO_AREAS[c["id"]] = (found["lat"], found["lon"])
            if approx:
                APPROX.add(c["id"])
        else:
            LOG.append(f"geocode: no match for {c['name']} ({' / '.join(qs)})")
    LOG.append(f"geocode: {len(CO_AREAS)} of {len(DIRECTORY)} companies pinned ({looked} new lookups)")


ATS_PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    ("greenhouse", r"greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.lever\.co/([A-Za-z0-9_-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("workday", r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
    ("keka", r"([a-z0-9-]+)\.keka\.com"),
    ("kula", r"careers\.kula\.ai/([A-Za-z0-9_-]+)"),
    ("freshteam", r"([a-z0-9-]+)\.freshteam\.com"),
    ("zohorecruit", r"([a-z0-9-]+\.zohorecruit\.(?:com|in))"),
    ("zohorecruit", r"(careers\.zohocorp\.com)"),
    ("unsupported", r"([a-z0-9-]+\.(?:darwinbox\.in|turbohire\.co))"),
]
SKIP_TOK = {"embed", "js", "v1", "api", "jobs", "careers", "j", "en-US", "www", "cdn", "assets", "static", "help", "support"}


def detect_ats(text):
    found = []
    for kind, pat in ATS_PATTERNS:
        for m in re.finditer(pat, text):
            g = m.groups()
            if g[0] in SKIP_TOK:
                continue
            item = (kind,) + g
            if item not in found:
                found.append(item)
    return found


def jobs_from_ats(kind, args, co_name):
    """Returns list of (title, loc_text, date, type, url)."""
    out = []
    if kind == "greenhouse":
        res = get(f"https://boards-api.greenhouse.io/v1/boards/{args[0]}/jobs")
        for j in res.get("jobs", []):
            out.append((j.get("title"), (j.get("location") or {}).get("name", ""), iso_date(j.get("first_published") or j.get("updated_at")), "", j.get("absolute_url")))
    elif kind == "lever":
        res = get(f"https://api.lever.co/v0/postings/{args[0]}?mode=json")
        for j in res if isinstance(res, list) else []:
            cats = j.get("categories") or {}
            d = datetime.datetime.fromtimestamp((j.get("createdAt") or 0) / 1000, IST).date().isoformat() if j.get("createdAt") else TODAY.isoformat()
            out.append((j.get("text"), " ".join([cats.get("location") or ""] + (cats.get("allLocations") or [])), d, cats.get("commitment") or "", j.get("hostedUrl")))
    elif kind == "ashby":
        res = get(f"https://api.ashbyhq.com/posting-api/job-board/{args[0]}")
        for j in res.get("jobs", []):
            locs = " ".join([j.get("location") or ""] + [(x or {}).get("location", "") for x in (j.get("secondaryLocations") or [])])
            out.append((j.get("title"), locs, iso_date(j.get("publishedAt")), (j.get("employmentType") or "").replace("FullTime", "Full-time"), j.get("jobUrl")))
    elif kind == "smartrecruiters":
        res = get(f"https://api.smartrecruiters.com/v1/companies/{args[0]}/postings?city=Chennai&limit=100")
        for j in res.get("content", []):
            loc = j.get("location") or {}
            out.append((j.get("name"), ", ".join(str(loc.get(k) or "") for k in ("city", "region", "country")), iso_date(j.get("releasedDate")), ((j.get("typeOfEmployment") or {}).get("label") or ""), f"https://jobs.smartrecruiters.com/{args[0]}/{j.get('id')}"))
    elif kind == "workable":
        res = get(f"https://apply.workable.com/api/v3/accounts/{args[0]}/jobs", data={"query": "", "location": [], "department": [], "worktype": [], "remote": []})
        for j in res.get("results", []):
            loc = j.get("location") or {}
            out.append((j.get("title"), ", ".join(str(loc.get(k) or "") for k in ("city", "region", "country")), iso_date(j.get("published")), "", f"https://apply.workable.com/{args[0]}/j/{j.get('shortcode')}/"))
    elif kind == "workday":
        tenant, wd, site = args
        host = f"{tenant}.{wd}.myworkdayjobs.com"
        off = 0
        while off < 200:
            res = get(f"https://{host}/wday/cxs/{tenant}/{site}/jobs", data={"appliedFacets": {}, "limit": 20, "offset": off, "searchText": ""})
            posts = res.get("jobPostings", [])
            for j in posts:
                out.append((j.get("title"), j.get("locationsText") or "", rel_date(j.get("postedOn")), "", f"https://{host}/{site}{j.get('externalPath', '')}"))
            off += 20
            if len(posts) < 20:
                break
    elif kind == "keka":
        base = f"https://{args[0]}.keka.com/careers/"
        page, _ = fetch_html(base)
        guid = re.search(r"embedjobs/(?:js/)?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", page) or re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", page)
        if not guid:
            raise ValueError("keka portal id not found")
        res = get(f"{base}api/embedjobs/default/active/{guid.group(1)}")
        for j in res if isinstance(res, list) else []:
            locs = " ".join(f"{l.get('name') or ''} {l.get('city') or ''}" for l in (j.get("jobLocations") or []))
            out.append((j.get("title"), locs, iso_date(j.get("publishedOn")), "", f"{base}jobdetails/{j.get('id')}"))
    elif kind == "freshteam":
        base = f"https://{args[0]}.freshteam.com"
        page, _ = fetch_html(base + "/jobs")
        links = list(dict.fromkeys(re.findall(r'href="(/jobs/[A-Za-z0-9_-]{6,}/[^"#?]+)"', page)))
        for path in links[:40]:
            try:
                pg, final = fetch_html(base + path)
            except Exception:
                continue
            for p in jsonld_postings(pg)[:1]:
                out.append((p.get("title"), posting_location(p), iso_date(p.get("datePosted")) if p.get("datePosted") else None, str(p.get("employmentType") or "").replace("_", " ").title(), final))
            time.sleep(0.2)
    elif kind == "kula":
        base = "https://careers.kula.ai"
        page, _ = fetch_html(f"{base}/{args[0]}")
        links = list(dict.fromkeys(re.findall(rf'href="(/{re.escape(args[0])}/\d+)', page)))
        if not links:
            raise ValueError("no kula jobs")
        for path in links[:45]:
            try:
                pg, final = fetch_html(base + path)
            except Exception:
                continue
            for p in jsonld_postings(pg)[:1]:
                out.append((p.get("title"), posting_location(p), iso_date(p.get("datePosted")) if p.get("datePosted") else None, str(p.get("employmentType") or "").replace("_", " ").title(), final))
            time.sleep(0.2)
    elif kind == "zohorecruit":
        host = args[0]
        page, final = fetch_html(f"https://{host}/jobs/Careers")
        m = re.search(r'<input[^>]*id=["\']jobs["\'][^>]*value=["\'](.*?)["\']\s*/?>', page, re.S) or re.search(r'value=["\'](\[\{.*?\}\])["\'][^>]*id=["\']jobs["\']', page, re.S)
        if not m:
            raise ValueError("zoho recruit list not found")
        for j in json.loads(htmlmod.unescape(m.group(1))):
            if j.get("Publish") is False:
                continue
            title = j.get("Posting_Title") or j.get("Job_Opening_Name")
            slug = re.sub(r"[^A-Za-z0-9]+", "-", title or "").strip("-")
            loc = ", ".join(str(j.get(k) or "") for k in ("City", "State", "Country1") if j.get(k))
            out.append((title, loc, iso_date(j.get("Date_Opened")) if j.get("Date_Opened") else None, j.get("Job_Type") or "", f"https://{host}/jobs/Careers/{j.get('id')}/{slug}"))
    return out


def jsonld_postings(page):
    found = []
    for blob in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try:
            data = json.loads(blob.strip())
        except Exception:
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                t = x.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    found.append(x)
                stack.extend(v for k, v in x.items() if k == "@graph" or isinstance(v, (list, dict)) and k not in ("hiringOrganization",))
    return found


def posting_location(p):
    locs = p.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    bits = []
    for l in locs:
        a = (l or {}).get("address") or {}
        if isinstance(a, dict):
            bits += [str(a.get(k) or "") for k in ("streetAddress", "addressLocality", "addressRegion")]
        elif isinstance(a, str):
            bits.append(a)
    return ", ".join(b for b in bits if b)


def text_of(page):
    page = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    return tidy(htmlmod.unescape(re.sub(r"<[^>]+>", " ", page)))


JOB_PATH = re.compile(r"/(?:careers?|jobs?|job-description|openings?|positions?|vacanc(?:y|ies))/[^/?#]{4,}", re.I)
NAV_WORDS = {"careers", "jobs", "openings", "view all", "apply", "life", "culture", "benefits", "faq", "about", "team", "students",
             "university", "search jobs", "all jobs", "current openings", "join us", "home"}
JOB_SIGNS = ["responsibilit", "requirement", "qualification", "experience", "job description", "what you", "about the role", "apply"]


def site_key(host):
    parts = (host or "").lower().split(".")
    return ".".join(parts[-3:]) if len(parts) > 2 and parts[-2] in ("co", "com", "org", "net", "ac") and len(parts[-1]) == 2 else ".".join(parts[-2:])


def crawl_careers(page, base, co_name):
    out, seen = [], set()
    for p in jsonld_postings(page):
        out.append((p.get("title"), posting_location(p), iso_date(p.get("datePosted")) if p.get("datePosted") else None, str(p.get("employmentType") or "").replace("_", " ").title(), p.get("url") or base))
    if out:
        return out, "embedded job listings"
    links = []
    for href, label in re.findall(r"<a\s[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", page, re.S | re.I):
        u = urljoin(base, htmlmod.unescape(href))
        lab = tidy(htmlmod.unescape(re.sub(r"<[^>]+>", " ", label)))
        pu = urlparse(u)
        if pu.scheme not in ("http", "https") or site_key(pu.netloc) != site_key(urlparse(base).netloc):
            continue
        if not JOB_PATH.search(pu.path) or u.rstrip("/") == base.rstrip("/") or u in seen:
            continue
        if not (4 <= len(lab) <= 90) or lab.lower() in NAV_WORDS:
            continue
        seen.add(u)
        links.append((u, lab))
    for u, lab in links[:30]:
        try:
            pg, final = fetch_html(u)
        except Exception:
            continue
        posts = jsonld_postings(pg)
        if posts:
            p = posts[0]
            out.append((p.get("title") or lab, posting_location(p) or text_of(pg)[:4000], iso_date(p.get("datePosted")) if p.get("datePosted") else None, str(p.get("employmentType") or "").replace("_", " ").title(), final))
            continue
        txt = text_of(pg)
        if "chennai" in txt.lower() and any(w in txt.lower() for w in JOB_SIGNS):
            m = re.search(r"<h1[^>]*>(.*?)</h1>", pg, re.S | re.I)
            title = tidy(htmlmod.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))) if m else lab
            out.append((title or lab, "Chennai", None, "", final))
        time.sleep(0.3)
    return out, ("job pages on the careers site" if out else "")


ATS_CACHE = load_json("ats_cache.json", {})
CAREER_WORDS = re.compile(r"career|jobs|join[-_ ]?us|work[-_ ]with[-_ ]us|hiring|openings|vacanc", re.I)


def slug_variants(c):
    out = []
    site = (c.get("site") or "").lower().removeprefix("www.")
    if site:
        out.append(site.split(".")[0])
    n = re.sub(r"\(.*?\)", "", c["name"]).lower()
    out.append(re.sub(r"[^a-z0-9]", "", n))
    out.append(re.sub(r"[^a-z0-9]+", "-", n).strip("-"))
    w = re.sub(r"[^a-z0-9 ]", "", n).split()
    if w and len(w[0]) >= 5:
        out.append(w[0])
    return [x for x in dict.fromkeys(out) if len(x) >= 3]


def indian(items):
    return any(not loc or in_chennai(loc) or "india" in (loc or "").lower() for _, loc, *_ in items)


def probe_ats(c):
    """Try the usual job-board addresses for this company's name. Returns (kind, args) or None."""
    from concurrent.futures import ThreadPoolExecutor
    tries = []
    for v in slug_variants(c):
        tries += [("greenhouse", (v,)), ("lever", (v,)), ("ashby", (v,)), ("workable", (v,)), ("keka", (v,)), ("freshteam", (v,)), ("kula", (v,)),
                  ("zohorecruit", (v + ".zohorecruit.in",)), ("zohorecruit", (v + ".zohorecruit.com",))]

    def one(t):
        try:
            items = jobs_from_ats(t[0], t[1], c["name"])
            return t if items and indian(items) else None
        except Exception:
            return None
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(one, tries):
            if r:
                return r
    return None


def careers_links(page, base):
    links = []
    for href, label in re.findall(r"<a\s[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", page, re.S | re.I):
        u = urljoin(base, htmlmod.unescape(href))
        lab = tidy(htmlmod.unescape(re.sub(r"<[^>]+>", " ", label)))
        pu = urlparse(u)
        if pu.scheme in ("http", "https") and (CAREER_WORDS.search(pu.path) or CAREER_WORDS.search(pu.netloc.split(".")[0]) or CAREER_WORDS.search(lab[:40])):
            links.append(u)
    return list(dict.fromkeys(links))[:4]


def read_page(url, name):
    """Returns (items, how) for a careers page, or raises."""
    page, final = fetch_html(url)
    how = ""
    for a in detect_ats(final + " " + page):
        if a[0] == "unsupported":
            how = how or f"uses {a[1]} (not readable yet)"
            continue
        try:
            items = jobs_from_ats(a[0], a[1:], name)
            return items, f"{a[0]} job board", (a[0], list(a[1:]))
        except Exception as e:
            LOG.append(f"company {name}: {a[0]} {a[1:]} failed: {e}")
    items, how2 = crawl_careers(page, final, name)
    return items, how2 or how, ("page", [final]) if items else None


def fetch_directory():
    for c in DIRECTORY:
        name = c["name"]
        n0 = len(JOBS)
        items, how, src = [], "", None
        cached = ATS_CACHE.get(c["id"]) or {}
        # 1. what worked last time
        if cached.get("kind") and cached["kind"] != "none":
            try:
                if cached["kind"] == "page":
                    items, how, src = read_page(cached["args"][0], name)
                else:
                    items = jobs_from_ats(cached["kind"], tuple(cached["args"]), name)
                    how, src = f"{cached['kind']} job board", (cached["kind"], cached["args"])
            except Exception as e:
                LOG.append(f"company {name}: saved source failed: {e}")
        # 2. the careers address we have on file
        if not src and c.get("careers"):
            try:
                items, how, src = read_page(c["careers"], name)
            except Exception as e:
                how = f"careers page failed: {e}"
        # 3. look for it: careers links on the home page, then the usual job boards (at most weekly for misses)
        stale = cached.get("kind") == "none" and cached.get("checked", "") > (TODAY - datetime.timedelta(days=7)).isoformat()
        if not src and not stale and c.get("site"):
            try:
                home, hfinal = fetch_html("https://" + c["site"] + "/")
                ats = [a for a in detect_ats(home) if a[0] != "unsupported"]
                cands = careers_links(home, hfinal)
                for a in ats:
                    try:
                        items = jobs_from_ats(a[0], a[1:], name)
                        how, src = f"{a[0]} job board (found on home page)", (a[0], list(a[1:]))
                        break
                    except Exception:
                        pass
                for u in cands if not src else []:
                    try:
                        it, h2, s2 = read_page(u, name)
                    except Exception:
                        continue
                    if s2:
                        items, how, src = it, h2 + " (found on home page)", s2
                        break
            except Exception:
                pass
            if not src:
                r = probe_ats(c)
                if r:
                    items = jobs_from_ats(r[0], r[1], name)
                    how, src = f"{r[0]} job board (found by name)", (r[0], list(r[1]))
            ATS_CACHE[c["id"]] = {"kind": src[0], "args": src[1], "checked": TODAY.isoformat()} if src else {"kind": "none", "checked": TODAY.isoformat()}
        elif src:
            ATS_CACHE[c["id"]] = {"kind": src[0], "args": src[1], "checked": TODAY.isoformat()}
        for title, loc, date, jtype, u in items:
            if not title or not u:
                continue
            if loc and not in_chennai(loc):
                continue
            d = date or PREV.get(u) or TODAY.isoformat()
            add(title, name, loc or "Chennai", d, jtype, u, "Company careers", area="")
        got = len(JOBS) - n0
        LOG.append(f"company {name}: " + (how if how.startswith("careers page failed") and not got else f"{got} Chennai jobs" + (f" via {how}" if how else " (no readable listings found)")))


def pin_directory_jobs():
    names = {}
    for c in DIRECTORY:
        for n in [c["name"]] + c.get("alias", []):
            names[norm(n)] = c
    for j in JOBS:
        c = names.get(norm(j["c"]))
        if not c:
            continue
        j["c"] = c["name"]
        if c["id"] in CO_AREAS and (not j["a"] or j["src"] == "Company careers"):
            j["a"] = "co_" + c["id"]



# ---------- company logos (saved into logos/ so the site serves them itself) ----------
LOGOS = {}


def icon_links(page, base):
    cands = []
    for tag in re.findall(r"<link\b[^>]*>", page, re.I):
        rel = (re.search(r"rel=[\"']([^\"']+)", tag, re.I) or [None, ""])[1].lower()
        href = (re.search(r"href=[\"']([^\"']+)", tag, re.I) or [None, ""])[1]
        if not href:
            continue
        if rel == "manifest":
            try:
                man = get(urljoin(base, htmlmod.unescape(href)), timeout=15)
                for ic in man.get("icons", []):
                    if ic.get("src"):
                        cands.append(urljoin(urljoin(base, href), ic["src"]))
            except Exception:
                pass
        elif "icon" in rel and "mask-icon" not in rel:
            cands.append(urljoin(base, htmlmod.unescape(href)))
    for m in re.findall(r"<meta[^>]+(?:msapplication-TileImage|og:logo)[^>]+content=[\"']([^\"']+)", page, re.I):
        cands.append(urljoin(base, htmlmod.unescape(m)))
    return list(dict.fromkeys(cands))


def fetch_bytes(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": HTML_UA["User-Agent"], "Accept": "image/*,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(1_500_001), (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()


EXT = {"image/png": "png", "image/svg+xml": "svg", "image/jpeg": "jpg", "image/webp": "webp", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico", "image/gif": "gif"}


def image_side(data, ext):
    """Smaller side of an image in pixels (SVG counts as large); 0 if unreadable."""
    import struct
    try:
        if ext == "svg":
            return 512 if b"<svg" in data[:3000].lower() else 0
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", data[16:24]); return min(w, h)
        if data[:4] == b"\x00\x00\x01\x00":
            best = 0
            for i in range(struct.unpack("<H", data[4:6])[0]):
                w, h = data[6 + 16 * i], data[7 + 16 * i]
                best = max(best, min(w or 256, h or 256))
            return best
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8X":
                return min(1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little"))
            if data[12:16] == b"VP8L":
                b = int.from_bytes(data[21:25], "little"); return min((b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1)
            if data[12:16] == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30]); return min(w & 0x3FFF, h & 0x3FFF)
        if data[:2] == b"\xff\xd8":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1; continue
                mk = data[i + 1]
                if mk in (0xC0, 0xC1, 0xC2):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9]); return min(w, h)
                i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        if data[:3] == b"GIF":
            w, h = struct.unpack("<HH", data[6:10]); return min(w, h)
    except Exception:
        pass
    return 0


# employers that post Chennai jobs but are not in companies.json: name -> website, for their logo
EMPLOYER_SITES = {"Caterpillar": "caterpillar.com", "Bosch Group": "bosch.com", "Pfizer": "pfizer.com", "Zuora": "zuora.com",
                  "Mitsogo Inc": "mitsogo.com", "Valgenesis": "valgenesis.com", "Visa": "visa.com", "Ford": "ford.com",
                  "HCLTech": "hcltech.com", "project44": "project44.com", "Equativ": "equativ.com", "Workday": "workday.com"}


def best_logo(site):
    """Downloads the clearest square icon the site offers. Returns (bytes, ext, side) or None."""
    urls, exists = [], False
    try:
        page, final = fetch_html("https://" + site + "/")
        urls += icon_links(page, final)
        exists = True
    except urllib.error.HTTPError:
        exists = True
    except Exception:
        pass
    urls += ["https://" + site + "/apple-touch-icon.png"]
    if exists:
        urls.append(f"https://www.google.com/s2/favicons?domain={site}&sz=256")
    best = None
    for u in urls[:10]:
        try:
            data, ctype = fetch_bytes(u)
        except Exception:
            continue
        ext = EXT.get(ctype) or (u.rsplit(".", 1)[-1].lower() if u.rsplit(".", 1)[-1].lower() in ("png", "svg", "jpg", "webp", "ico") else "")
        if not ext or len(data) < 120 or len(data) > 1_500_000:
            continue
        side = image_side(data, ext)
        if not side or side > 4096:
            continue
        # prefer real site icons; Google's copy is a fallback only when it is clearly bigger
        score = min(side, 512) - (40 if "google.com/s2" in u else 0)
        if not best or score > best[3]:
            best = (data, ext, side, score)
        if side >= 180 and "google.com/s2" not in u:
            break
    return best[:3] if best else None


def fetch_logos():
    os.makedirs(os.path.join(ROOT, "logos"), exist_ok=True)
    have = {f.rsplit(".", 1)[0]: f for f in os.listdir(os.path.join(ROOT, "logos"))}
    got = 0
    todo = [(c["id"], c["name"], c.get("site")) for c in DIRECTORY] + [("emp-" + re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-"), n, st) for n, st in EMPLOYER_SITES.items()]
    for key, name, site in todo:
        if not site:
            continue
        cur = have.get(key)
        side = 0
        if cur:
            try:
                with open(os.path.join(ROOT, "logos", cur), "rb") as f:
                    side = image_side(f.read(), cur.rsplit(".", 1)[-1])
            except Exception:
                side = 0
            LOGOS[name] = "logos/" + cur
            if 64 <= side <= 4096:
                continue
        found = best_logo(site)
        if found and found[2] > side:
            data, ext, _ = found
            if cur:
                os.remove(os.path.join(ROOT, "logos", cur))
            fname = f"{key}.{ext}"
            with open(os.path.join(ROOT, "logos", fname), "wb") as f:
                f.write(data)
            LOGOS[name] = "logos/" + fname
            got += 1
        time.sleep(0.2)
    LOG.append(f"logos: {len(LOGOS)} logos ({got} new or sharper)")


def main():
    for fn in (geocode_directory, fetch_logos, fetch_jsearch, fetch_greenhouse, fetch_lever, fetch_smartrecruiters, fetch_workday, fetch_directory):
        try:
            fn()
        except Exception as e:
            LOG.append(f"{fn.__name__}: crashed: {e}")
    pin_directory_jobs()
    seen, out = set(), []
    for j in sorted(JOBS, key=lambda x: x["d"], reverse=True):
        k = re.sub(r"[^a-z0-9]", "", (j["t"] + "|" + j["c"]).lower())
        if k in seen:
            continue
        seen.add(k)
        out.append(j)
    used = {j["a"] for j in out if j["a"]}
    areas = {k: v for k, v in NEW_AREAS.items() if k in used}
    for c in DIRECTORY:
        k = "co_" + c["id"]
        if c["id"] in CO_AREAS:
            la, lo = CO_AREAS[c["id"]]
            areas[k] = {"en": c["name"], "ta": c["name"], "lat": round(la, 6), "lon": round(lo, 6), "exact": True, "co": True, "office": c.get("office", ""), "logo": LOGOS.get(c["name"], ""), "approx": c["id"] in APPROX, "careers": c.get("careers", "")}
    with open(os.path.join(ROOT, "geo_cache.json"), "w", encoding="utf-8") as f:
        json.dump(GEO_CACHE, f, ensure_ascii=False, indent=0)
    with open(os.path.join(ROOT, "ats_cache.json"), "w", encoding="utf-8") as f:
        json.dump(ATS_CACHE, f, ensure_ascii=False, indent=1)
    feed = {"updated": TODAY.isoformat(), "areas": areas, "logos": LOGOS,
            "log": LOG, "jobs": out}
    if not out:
        prev = load_json("feeds.json", None)
        if prev and prev.get("jobs"):
            print("No jobs fetched today; keeping the previous feeds.json")
            print("\n".join(LOG))
            return
    with open(os.path.join(ROOT, "feeds.json"), "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(out)} jobs written")
    print("\n".join(LOG))


if __name__ == "__main__":
    main()
