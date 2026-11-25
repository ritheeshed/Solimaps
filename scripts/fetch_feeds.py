"""Daily job fetcher for Soli Maps.

Pulls Chennai white-collar jobs from:
  * Google for Jobs, via OpenWeb Ninja JSearch (needs the JSEARCH_KEY secret)
  * company career pages that publish public job feeds
    (Greenhouse, Lever, SmartRecruiters, Workday)
and writes feeds.json, which the site merges with jobs.json (Indeed) and posts.json (employer posts).

Standard library only, so the GitHub Action needs no installs.
"""
import json, os, re, sys, time, math, datetime, urllib.request, urllib.parse

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
              "architect", "technical", "product manager", "program manager", "scrum"]),
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


def main():
    for fn in (fetch_jsearch, fetch_greenhouse, fetch_lever, fetch_smartrecruiters, fetch_workday):
        try:
            fn()
        except Exception as e:
            LOG.append(f"{fn.__name__}: crashed: {e}")
    seen, out = set(), []
    for j in sorted(JOBS, key=lambda x: x["d"], reverse=True):
        k = re.sub(r"[^a-z0-9]", "", (j["t"] + "|" + j["c"]).lower())
        if k in seen:
            continue
        seen.add(k)
        out.append(j)
    used = {j["a"] for j in out if j["a"]}
    feed = {"updated": TODAY.isoformat(), "areas": {k: v for k, v in NEW_AREAS.items() if k in used},
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
