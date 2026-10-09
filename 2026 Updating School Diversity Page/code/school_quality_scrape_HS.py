import argparse
import csv
import re
import sys
import time
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

# ==========================================================================
# SETTINGS
# ==========================================================================
TRIAL_LIMIT = None
#TRIAL_LIMIT = 10

OUTPUT_CSV = "hs_school_data.csv"
PAGE_TIMEOUT_SECONDS = 60
DEBUG_DIR = "scrape_debug"

# --------------------------------------------------------------------------
# Which schools to scrape: DBNs from the NYC demographic snapshot spreadsheet
# --------------------------------------------------------------------------
DEMOGRAPHICS_XLSX_PATH = (
    "/Users/GCampa/Desktop/Updating School Diversity Page/origdata/"
    "demographic-snapshot-2021-22-to-2025-26-public.xlsx"
)
DEMOGRAPHICS_YEAR = "2024-25"


def _find_column(df: pd.DataFrame, *candidates: str) -> str:
    normalized = {re.sub(r"\s+", " ", str(c)).strip().lower(): c for c in df.columns}
    for candidate in candidates:
        key = re.sub(r"\s+", " ", candidate).strip().lower()
        if key in normalized:
            return normalized[key]
    raise KeyError(
        f"None of {list(candidates)!r} found as a column. "
        f"Actual columns in the sheet: {list(df.columns)}"
    )


def _load_demographics_sheet(xlsx_path: str) -> pd.DataFrame:
    xl = pd.ExcelFile(xlsx_path)
    errors = []
    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        try:
            _find_column(df, "DBN")
            _find_column(df, "Year", "School Year", "DBN Year")
            _find_column(df, "Grade 9")
        except KeyError as e:
            errors.append(f"  sheet {sheet!r}: {e}")
            continue
        return df
    raise KeyError(
        f"No sheet in {xlsx_path!r} has DBN/Year/Grade 9-style columns. "
        f"Sheets checked ({xl.sheet_names}):\n" + "\n".join(errors)
    )


def load_high_school_dbns(xlsx_path: str = DEMOGRAPHICS_XLSX_PATH,
                          year: str = DEMOGRAPHICS_YEAR) -> list[str]:
    demos = _load_demographics_sheet(xlsx_path)

    year_col = _find_column(demos, "Year", "School Year", "DBN Year")
    dbn_col = _find_column(demos, "DBN")
    grade_cols = [
        _find_column(demos, f"Grade {n}") for n in (9, 10, 11, 12)
    ]

    is_year = demos[year_col].astype(str).str.strip() == year
    has_hs_grade = pd.concat(
        [demos[c] > 1 for c in grade_cols], axis=1
    ).any(axis=1)

    hs = demos.loc[is_year & has_hs_grade].copy()
    if hs.empty:
        sample_years = demos[year_col].astype(str).str.strip().drop_duplicates().tolist()
        raise ValueError(
            f"No rows matched year={year!r} in column {year_col!r}. "
            f"Values actually present in that column: {sample_years}"
        )

    dbns = (
        hs[dbn_col].astype(str).str.strip().str.upper()
        .drop_duplicates().tolist()
    )
    return dbns

CANDIDATE_TYPES = ('HS',)
MANUAL_TYPE_OVERRIDES: dict[str, str] = {
}


def _candidate_types_for(dbn: str) -> list[str]:
    pinned = MANUAL_TYPE_OVERRIDES.get(dbn)
    if pinned:
        return [pinned] + [t for t in CANDIDATE_TYPES if t != pinned]
    return list(CANDIDATE_TYPES)


def get_schools() -> list[tuple[str, list[str]]]:
    """[(dbn, [types to try]), ...] -- reads the spreadsheet when called
    (not at import time, so importing this file never fails on the path)."""
    return [(dbn, _candidate_types_for(dbn)) for dbn in load_high_school_dbns()]


SNAPSHOT_YEAR = "2025"

BASE_URL = "https://tools.nycenet.edu/snapshot/{year}/{dbn}/{type}/"

DELAY_BETWEEN_SCHOOLS_SECONDS = 3
RESTART_DRIVER_EVERY = 100

# Skipping "About the NYC School Survey" / "Survey Response Rates" section
EXCLUDED_GROUP_CLASSES = {"survey-rr"}

# --------------------------------------------------------------------------
# Output columns from codebook. dbn / school_name are identifiers so rows
# can be told apart; drop them with --no-id.
# --------------------------------------------------------------------------
ID_COLUMNS = ["dbn", "school_name"]
CODEBOOK_COLUMNS = [
    "hs_sd_1ip", "hs_sd_1ssc", "hs_sd_1rf",
    "hs_sd_2w", "hs_sd_2p", "hs_sp_2g", "hs_sd_2e", "hs_sd_2am", "hs_sd_2as",
    "hs_sd_2a", "hs_sd_2l", "hs_sd_2n",
    "hs_sd_3as", "hs_sd_3bl", "hs_sd_3hs", "hs_sd_3na", "hs_sd_3pi", "hs_sd_3wh",
    "hs_sd_3ell", "hs_sd_3iep", "hs_sd_3eni", "hs_sd_3f", "hs_sd_3m", "hs_sd_3nb",
    "hs_sd_4qvar", "hs_sd_4spt", "hs_sd_4ec", "hs_sd_4art", "hs_sd_4ps",
    "hs_sd_5as", "hs_sd_5bl", "hs_sd_5hs", "hs_sd_5na", "hs_sd_5pi", "hs_sd_5wh",
    "hs_sd_5py", "hs_sd_5t3",
    "hs_sd_6q1a", "hs_sd_6q1b", "hs_sd_6q1h", "hs_sd_6q1n", "hs_sd_6q1p",
    "hs_sd_6q1w", "hs_sd_6q1e", "hs_sd_6q1i", "hs_sd_6q2", "hs_sd_6q3",
    "hs_ip_1crs", "hs_ip_1pc", "hs_ip_1ce",
    "hs_ip_2ap", "hs_ip_2nap",
    "hs_ip_2ra", "hs_ip_2rb", "hs_ip_2rh", "hs_ip_2rn", "hs_ip_2rp", "hs_ip_2rw",
    "hs_ip_3mv", "hs_ip_3sef", "hs_ip_3sep", "hs_ip_3sen",
    "hs_ip_3rsf", "hs_ip_3rsp", "hs_ip_3rsn",
    "hs_ip_4gr", "hs_ip_4gra", "hs_ip_4grb", "hs_ip_4grh", "hs_ip_4grn",
    "hs_ip_4grp", "hs_ip_4grw", "hs_ip_4grf", "hs_ip_4grm", "hs_ip_4gre",
    "hs_ip_4gri",
    "hs_ip_5q", "hs_ip_5q1", "hs_ip_5q1a", "hs_ip_5q1b", "hs_ip_5q1h",
    "hs_ip_5q1n", "hs_ip_5q1p", "hs_ip_5q1w", "hs_ip_5q1e", "hs_ip_5q1i",
    "hs_ssc_1qp", "hs_ssc_1q1", "hs_ssc_1q1a", "hs_ssc_1q1b", "hs_ssc_1q1h",
    "hs_ssc_1q1n", "hs_ssc_1q1p", "hs_ssc_1q1w", "hs_ssc_1q1e", "hs_ssc_1q1i",
    "hs_ssc_2qp", "hs_ssc_2q1", "hs_ssc_2q2",
    "hs_ssc_3qp", "hs_ssc_3q1", "hs_ssc_3q1a", "hs_ssc_3q1b", "hs_ssc_3q1h",
    "hs_ssc_3q1n", "hs_ssc_3q1p", "hs_ssc_3q1w", "hs_ssc_3q1e", "hs_ssc_3q1i",
    "hs_ssc_4sa", "hs_ssc_4sa90", "hs_ssc_4ta",
    "hs_ssc_5qp",
    "hs_ssc_5q1", "hs_ssc_5q1a", "hs_ssc_5q1b", "hs_ssc_5q1h", "hs_ssc_5q1n",
    "hs_ssc_5q1p", "hs_ssc_5q1w", "hs_ssc_5q1e", "hs_ssc_5q1i",
    "hs_ssc_5q2", "hs_ssc_5q2a", "hs_ssc_5q2b", "hs_ssc_5q2h", "hs_ssc_5q2n",
    "hs_ssc_5q2p", "hs_ssc_5q2w", "hs_ssc_5q2e", "hs_ssc_5q2i",
    "hs_ssc_5q3", "hs_ssc_5q3a", "hs_ssc_5q3b", "hs_ssc_5q3h", "hs_ssc_5q3n",
    "hs_ssc_5q3p", "hs_ssc_5q3w", "hs_ssc_5q3e", "hs_ssc_5q3i",
    "hs_rf_1qp", "hs_rf_1q1", "hs_rf_1q1a", "hs_rf_1q1b", "hs_rf_1q1h",
    "hs_rf_1q1n", "hs_rf_1q1p", "hs_rf_1q1w", "hs_rf_1q1e", "hs_rf_1q1i",
    "hs_rf_2qp", "hs_rf_2q1", "hs_rf_2q1a", "hs_rf_2q1b", "hs_rf_2q1h",
    "hs_rf_2q1n", "hs_rf_2q1p", "hs_rf_2q1w", "hs_rf_2q1e", "hs_rf_2q1i",
    "hs_rf_3qp", "hs_rf_3q1", "hs_rf_3q1a", "hs_rf_3q1b", "hs_rf_3q1h",
    "hs_rf_3q1n", "hs_rf_3q1p", "hs_rf_3q1w", "hs_rf_3q1e", "hs_rf_3q1i",
]

# Suffix letter -> subgroup key used by the chart parser.
# (Convention used throughout the codebook: a=Asian, b=Black, h=Hispanic,n=Native American, p=Pacific Islander, w=White, e=ELL, i=IEP.)
SUBGROUP_SUFFIX = {
    "a": "asian", "b": "black", "h": "hispanic", "n": "native_american",
    "p": "pacific_islander", "w": "white", "e": "ell", "i": "iep",
}
SUFFIX_SETS = {
    "all8": "abhnpwei",   # race + ELL + IEP
    "race6": "abhnpw",    # race only
}

# --------------------------------------------------------------------------
# Loading the pages
# --------------------------------------------------------------------------
def rtf_to_html(rtf: str) -> str:
    """Pull the HTML out of a plain-text RTF wrapper (e.g. TextEdit paste)."""
    start = rtf.find("<")
    body = rtf[start:] if start != -1 else rtf
    body = body.rstrip().rstrip("}")
    body = re.sub(r"\\'([0-9a-fA-F]{2})",
                  lambda m: bytes([int(m.group(1), 16)]).decode("cp1252"), body)
    body = re.sub(r"\\u(-?\d+) ?\??", lambda m: chr(int(m.group(1)) % 65536), body)
    body = (body.replace("\\\n", "\n").replace("\\{", "{")
                .replace("\\}", "}").replace("\\\\", "\\"))
    return body


def load_html(path: Path) -> str:
    raw = path.read_bytes().decode("utf-8", errors="replace")
    if raw.lstrip().startswith("{\\rtf"):
        raw = path.read_bytes().decode("latin-1")
        return rtf_to_html(raw)
    return raw


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def clean(text):
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def own_text(el, drop_classes=("label", "grey")):
    """Text of an element excluding child spans such as the label / grey city value."""
    if el is None:
        return ""
    el = BeautifulSoup(str(el), "lxml")
    for cls in drop_classes:
        for s in el.select(f"span.{cls}"):
            s.decompose()
    return clean(el.get_text(" "))


def group(scope, cls):
    """div.metric-group.<cls> inside scope."""
    return scope.select_one(f"div.metric-group.{cls}") if scope else None


def colon_values(scope):
    """{label (normalized, no colon): value} for div.metric-colon rows."""
    out = {}
    if scope is None:
        return out
    for div in scope.select("div.metric-colon"):
        lab = div.select_one("span.label")
        key = norm(lab.get_text(" ") if lab else "")
        out[key] = own_text(div)
    return out


def rating_word(svg_parent):
    """'Rating: 3 of 4 Bars, Good' -> 'Good'."""
    if svg_parent is None:
        return ""
    svg = svg_parent if svg_parent.name == "svg" else svg_parent.find("svg", attrs={"aria-label": True})
    if svg is None:
        return ""
    m = re.search(r"Bars?,\s*(.+)$", svg.get("aria-label", ""))
    return clean(m.group(1)) if m else clean(svg.get("aria-label", ""))


def bignum(scope, fragment):
    """School value of a big-number metric whose description contains fragment."""
    if scope is None:
        return ""
    for block in scope.select("div.metric-bignum"):
        desc = block.select_one(".description")
        if desc and norm(fragment) in norm(desc.get_text(" ")):
            val = block.select_one(".school-value")
            return clean(val.get_text(" ")) if val else ""
    return ""


def subgroup_key(label):
    """Map a chart row label (e.g. 'Hispanic or Latinx (116)') to a key."""
    t = norm(re.sub(r"\(.*?\)", "", label))
    if t.startswith("all "):
        return "all"
    if t == "city":
        return "city"
    if "asian" in t:
        return "asian"
    if "black" in t:
        return "black"
    if "hispanic" in t or "latinx" in t:
        return "hispanic"
    if "hawaiian" in t or "pacific" in t:
        return "pacific_islander"
    if "native american" in t:
        return "native_american"
    if "white" in t:
        return "white"
    if "english" in t or "learners" in t and "ieps" not in t:
        return "ell"
    if "iep" in t:
        return "iep"
    if "female" in t:
        return "female"
    if "male" in t:
        return "male"
    return t


def chart_rows(container, bar_class="main"):
    """
    Parse a viz-comp-bars chart. Returns {subgroup_key: value_text} using the
    bar whose <rect> has class bar_class (e.g. 'main', 'adv-courses').
    """
    out = {}
    if container is None:
        return out
    for bg in container.select("g.bar-group"):
        lab_g = bg.select_one("g.bar-group-labels")
        if lab_g is None:
            continue
        label = clean(" ".join(t.get_text(" ") for t in lab_g.find_all("text")))
        key = subgroup_key(label)
        for item in bg.select("g.bar-group-item"):
            rect = item.find("rect")
            if rect is not None and bar_class in (rect.get("class") or []):
                txt = item.find("text")
                out.setdefault(key, clean(txt.get_text(" ")) if txt else "")
                break
    return out


def survey_question(scope, fragment):
    """
    Find the 'Selected Questions from the NYC School Survey' question whose text
    contains fragment; return {subgroup_key: school value}. City values are
    returned under 'city' but never written out.
    """
    if scope is None:
        return {}
    for desc in scope.select("div.description"):
        if norm(fragment) in norm(desc.get_text(" ")):
            chart = desc.find_next_sibling()
            while chart is not None and "metric-viz-comp-bars" not in (chart.get("class") or []):
                if chart.name in ("h3", "h4") or "description" in (chart.get("class") or []):
                    chart = None
                    break
                chart = chart.find_next_sibling()
            return chart_rows(chart, "main")
    return {}


def value_list(scope, fragment):
    """ul.metric-value-list following a description -> {label(norm): value}."""
    if scope is None:
        return {}
    for desc in scope.select("div.description"):
        if norm(fragment) in norm(desc.get_text(" ")):
            ul = desc.find_next_sibling("ul")
            out = {}
            if ul:
                for li in ul.select("li.value-row"):
                    v = li.select_one("span.value")
                    lab = li.select_one("span.label")
                    out[norm(own_text(lab, drop_classes=("grey",)))] = clean(v.get_text(" ")) if v else ""
            return out
    return {}


def section_after_heading(scope, heading_text):
    """Elements that follow an h4 sub-heading until the next h3/h4 (as a mini soup)."""
    if scope is None:
        return None
    for h in scope.find_all("h4"):
        if norm(h.get_text(" ")) == norm(heading_text):
            parts = []
            for sib in h.find_next_siblings():
                if sib.name in ("h3", "h4"):
                    break
                parts.append(str(sib))
            return BeautifulSoup("<div>" + "".join(parts) + "</div>", "lxml")
    return None


def put_subgroups(row, prefix, data, suffixes, all_col=True):
    if all_col:
        row[prefix] = data.get("all", "")
    for s in suffixes:
        row[prefix + s] = data.get(SUBGROUP_SUFFIX[s], "")


# --------------------------------------------------------------------------
# Main parser
# --------------------------------------------------------------------------
def parse_hs_page(html: str):
    """Return (row_dict, None) for an HS page, or (None, reason) if skipped."""
    soup = BeautifulSoup(html, "lxml")
    for cls in EXCLUDED_GROUP_CLASSES:
        for el in soup.select(f"div.metric-group.{cls}"):
            el.decompose()

    school_type = soup.select_one("p.school-type")
    school_type = clean(school_type.get_text()) if school_type else ""
    if school_type.lower() != "high school":
        return None, f"report type is '{school_type or 'unknown'}', not 'High School'"

    row = {c: "" for c in ID_COLUMNS + CODEBOOK_COLUMNS}

    # Identifiers
    name_el = soup.select_one("div.school-name")
    full_name = clean(name_el.get_text()) if name_el else ""
    m = re.match(r"(.*)\((\w{6})\)\s*$", full_name)
    row["school_name"], row["dbn"] = (clean(m.group(1)), m.group(2)) if m else (full_name, "")

    info = soup.select_one("#tab-content-info")
    ip = soup.select_one("#tab-content-ip")
    ss = soup.select_one("#tab-content-ss")
    rf = soup.select_one("#tab-content-rf")

    # ---------------- School Description ----------------
    # 1. Overall School Ratings (School Description tab only)
    fr = info.select_one("div.framework-ratings") if info else None
    if fr:
        for href, col in (("#IP", "hs_sd_1ip"), ("#SS", "hs_sd_1ssc"), ("#RF", "hs_sd_1rf")):
            a = fr.select_one(f'a[href="{href}"]')
            row[col] = rating_word(a)

    # 2. Overview (Average SAT and About This School are skipped)
    ov = group(info, "gen")
    if ov is not None:
        for div in ov.select("div.metric-colon"):
            lab = norm(div.select_one("span.label").get_text(" ")) if div.select_one("span.label") else ""
            if lab == "school website":
                a = div.find("a")
                row["hs_sd_2w"] = clean(a.get_text()) if a else own_text(div)
        cv = colon_values(ov)
        row["hs_sd_2p"] = cv.get("principal", "")
        row["hs_sp_2g"] = cv.get("grades served", "")
        row["hs_sd_2e"] = cv.get("enrollment", "")
        row["hs_sd_2am"] = cv.get("admissions methods", "")
        row["hs_sd_2as"] = cv.get("state accountability status", "")
    loc = group(info, "location")
    if loc is not None:
        links = [clean(d.get_text(" ")) for d in loc.select("div.address")]
        row["hs_sd_2a"] = links[0] if len(links) > 0 else ""        # street address
        row["hs_sd_2l"] = links[1] if len(links) > 1 else ""        # city, state ZIP
        ph = loc.select_one("div.phone")
        row["hs_sd_2n"] = re.sub(r"^Phone:\s*", "", clean(ph.get_text())) if ph else ""

    # 3. Student Body -> Student Demographics (Surrounding Demographics skipped)
    demo = section_after_heading(group(info, "sch-demog"), "Student Demographics")
    cv = colon_values(demo)
    row["hs_sd_3as"] = cv.get("asian", "")
    row["hs_sd_3bl"] = cv.get("black", "")
    row["hs_sd_3hs"] = cv.get("hispanic or latinx", "")
    row["hs_sd_3na"] = cv.get("native american", "")
    row["hs_sd_3pi"] = cv.get("native hawaiian pacific islander", "")
    row["hs_sd_3wh"] = cv.get("white", "")
    row["hs_sd_3ell"] = cv.get("english language learners", "")
    row["hs_sd_3iep"] = cv.get("students with ieps", "")
    row["hs_sd_3eni"] = cv.get("economic need index", "")
    row["hs_sd_3f"] = cv.get("female", "")
    row["hs_sd_3m"] = cv.get("male", "")
    row["hs_sd_3nb"] = cv.get("neither female nor male", "")

    # 4. Programs
    prog = group(info, "program")
    row["hs_sd_4qvar"] = survey_question(prog, "wide enough variety of programs").get("all", "")
    sports = section_after_heading(prog, "PSAL Sports")
    if sports is not None:
        parts = []
        for div in sports.select("div.metric-colon"):
            lab = clean(div.select_one("span.label").get_text(" ")) if div.select_one("span.label") else ""
            parts.append(f"{lab} {own_text(div)}".strip())
        row["hs_sd_4spt"] = "; ".join(parts)
    for heading, col in (("Extracurricular Activities", "hs_sd_4ec"),
                         ("Arts Classes", "hs_sd_4art"),
                         ("NYCPS Programs", "hs_sd_4ps")):
        sec = section_after_heading(prog, heading)
        if sec is not None:
            row[col] = "; ".join(clean(d.get_text(" ")) for d in sec.select("div.description"))

    # 5. Staff/Faculty
    staff = group(info, "staff")
    cv = colon_values(section_after_heading(staff, "Teacher Demographics"))
    row["hs_sd_5as"] = cv.get("asian", "")
    row["hs_sd_5bl"] = cv.get("black", "")
    row["hs_sd_5hs"] = cv.get("hispanic or latinx", "")
    row["hs_sd_5na"] = cv.get("native american", "")
    row["hs_sd_5pi"] = cv.get("native hawaiian pacific islander", "")
    row["hs_sd_5wh"] = cv.get("white", "")
    cv = colon_values(section_after_heading(staff, "Staff Experience"))
    row["hs_sd_5py"] = cv.get("years of experience as principal at this school", "")
    row["hs_sd_5t3"] = cv.get("teachers with 3 or more years of experience", "")

    # 6. School Facilities and Services (Shared Space skipped)
    space = group(info, "space")
    put_subgroups(row, "hs_sd_6q1", survey_question(space, "school is kept clean"),
                  SUFFIX_SETS["all8"], all_col=False)
    row["hs_sd_6q2"] = survey_question(space, "kept in good physical condition").get("all", "")
    row["hs_sd_6q3"] = survey_question(space, "physical repairs to this school building").get("all", "")

    # ---------------- Instruction and Performance ----------------
    # (the "Overall Rating for Instruction and Performance" banner is skipped)
    ccr = group(ip, "ccr")
    row["hs_ip_1crs"] = bignum(ccr, "average college and career readiness score")
    row["hs_ip_1pc"] = bignum(ccr, "successfully completed approved college or career preparatory")
    row["hs_ip_1ce"] = bignum(ccr, "enrolled in college or other post-secondary")

    adv = group(ip, "adv-demog")
    vl = value_list(adv, "How many students were enrolled in at least one advanced class")
    row["hs_ip_2ap"] = vl.get("advanced placement", "")
    row["hs_ip_2nap"] = next((v for k, v in vl.items() if "non ap" in k), "")
    adv_chart = adv.select_one("div.metric-viz-comp-bars") if adv else None
    put_subgroups(row, "hs_ip_2r", chart_rows(adv_chart, "adv-courses"),
                  SUFFIX_SETS["race6"], all_col=False)

    lre = group(ip, "lre")
    row["hs_ip_3mv"] = rating_word(lre)

    swiep = group(ip, "swiep")
    se = value_list(swiep, "recommended special education programs")
    row["hs_ip_3sef"] = se.get("received in full", "")
    row["hs_ip_3sep"] = se.get("received in part", "")
    row["hs_ip_3sen"] = se.get("did not receive", "")
    rs = value_list(swiep, "recommended related services")
    row["hs_ip_3rsf"] = rs.get("received in full", "")
    row["hs_ip_3rsp"] = rs.get("received in part", "")
    row["hs_ip_3rsn"] = rs.get("did not receive", "")

    grad = group(ip, "grad")
    row["hs_ip_4gr"] = bignum(grad, "graduated within four years")
    sub = section_after_heading(grad, "4-Year Graduation Rate by Subgroup")
    g = chart_rows(sub, "main") if sub is not None else {}
    for suf, key in (("a", "asian"), ("b", "black"), ("h", "hispanic"),
                     ("n", "native_american"), ("p", "pacific_islander"),
                     ("w", "white"), ("f", "female"), ("m", "male"),
                     ("e", "ell"), ("i", "iep")):
        row["hs_ip_4gr" + suf] = g.get(key, "")

    le = group(ip, "learning-env")
    row["hs_ip_5q"] = bignum(le, "instruction/learning environment")
    put_subgroups(row, "hs_ip_5q1",
                  survey_question(le, "treat students of different races, cultures, or backgrounds equally"),
                  SUFFIX_SETS["all8"])

    # ---------------- Safety and School Climate ----------------
    # (the "Overall Rating for Safety and School Climate" banner is skipped)
    saf = group(ss, "safety")
    row["hs_ssc_1qp"] = bignum(saf, "survey questions about safety")
    put_subgroups(row, "hs_ssc_1q1", survey_question(saf, "feel safe in the hallways"),
                  SUFFIX_SETS["all8"])

    lead = group(ss, "school-leadership")
    row["hs_ssc_2qp"] = bignum(lead, "survey questions about school leadership")
    row["hs_ssc_2q1"] = survey_question(lead, "sets high standards for student learning").get("all", "")
    row["hs_ssc_2q2"] = survey_question(lead, "encourages feedback through regular meetings").get("all", "")

    advis = group(ss, "advising")
    row["hs_ssc_3qp"] = bignum(advis, "survey questions about advising and planning")
    put_subgroups(row, "hs_ssc_3q1", survey_question(advis, "help them plan for how to meet their future career goals"),
                  SUFFIX_SETS["all8"])

    att = group(ss, "attendance")
    if att is not None:
        for d in att.select("div.description"):
            t = own_text(d)
            mm = re.match(r"Student attendance:\s*(.+)$", t, re.I)
            if mm:
                row["hs_ssc_4sa"] = mm.group(1)
            mm = re.match(r"Students with >\s*90% attendance:\s*(.+)$", t, re.I)
            if mm:
                row["hs_ssc_4sa90"] = mm.group(1)
        row["hs_ssc_4ta"] = colon_values(att).get("teacher attendance", "")

    sup = group(ss, "stu-support")
    row["hs_ssc_5qp"] = bignum(sup, "survey questions about student support")
    put_subgroups(row, "hs_ssc_5q1", survey_question(sup, "support them when they are upset"), SUFFIX_SETS["all8"])
    put_subgroups(row, "hs_ssc_5q2", survey_question(sup, "treats them with respect"), SUFFIX_SETS["all8"])
    put_subgroups(row, "hs_ssc_5q3", survey_question(sup, "feel like they belong at this school"), SUFFIX_SETS["all8"])

    # ---------------- Relationships with Families ----------------
    # (the "Overall Rating for Relationships with Families" banner is skipped)
    com = group(rf, "communication")
    row["hs_rf_1qp"] = bignum(com, "survey questions about communication")
    put_subgroups(row, "hs_rf_1q1", survey_question(com, "regularly communicates with them about how they can help"),
                  SUFFIX_SETS["all8"])

    fam = group(rf, "family-involve")
    row["hs_rf_2qp"] = bignum(fam, "survey questions about family involvement")
    put_subgroups(row, "hs_rf_2q1", survey_question(fam, "communicated with their child's teacher about their child's performance"),
                  SUFFIX_SETS["all8"])

    trust = group(rf, "relation-w-family")
    row["hs_rf_3qp"] = bignum(trust, "survey questions about family-school trust")
    put_subgroups(row, "hs_rf_3q1", survey_question(trust, "build trusting relationships with families"),
                  SUFFIX_SETS["all8"])

    return row, None


# -------------------------------------------------------------------------------------------
# Live fetch (Playwright) the snapshot site is a JavaScript app, so the page must be rendered
# -------------------------------------------------------------------------------------------
def _short(e):
    return (str(e).strip().splitlines() or [repr(e)])[0][:200]


TAB_KEYS = ("info", "ip", "ss", "rf")


def _grab_all_tabs(page, timeout_ms):
    """
    The live page only builds a tab's content once that tab has been opened,
    so click each tab (School Description, Instruction and Performance,
    Safety and School Climate, Relationships with Families), wait for its
    content, and keep a copy of it. Returns one HTML string with all four tabs.
    """
    tabs = {}
    for key in TAB_KEYS:
        content = f"#tab-content-{key} .metric-group"
        if page.query_selector(content) is None:
            button = page.query_selector(f"#tab-button-{key}")
            if button is not None:
                button.click()
        page.wait_for_selector(content, state="attached", timeout=timeout_ms)
        page.wait_for_timeout(500)  # let the charts finish drawing
        tabs[key] = page.eval_on_selector(f"#tab-content-{key}", "e => e.outerHTML")

    # Rest of the page (header with school name + report type), minus any
    # tab panels, followed by the four tabs captured above.
    soup = BeautifulSoup(page.evaluate("document.body.outerHTML"), "lxml")
    for el in soup.select('[id^="tab-content-"]'):
        el.decompose()
    return str(soup) + "".join(tabs[k] for k in TAB_KEYS)


def _save_debug(page, label):
    """On a failed page, save what the browser saw (HTML + screenshot)."""
    try:
        folder = Path(DEBUG_DIR)
        folder.mkdir(exist_ok=True)
        label = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_")[-80:]
        (folder / f"{label}.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(folder / f"{label}.png"), full_page=True)
        print(f"       saved what the browser saw to {folder / label}.html / .png", file=sys.stderr)
    except Exception:
        pass


def _fetch_worker(jobs, pages, timeout_ms, delay, restart_every):
    """jobs: [(label, [url, url, ...])] -- urls tried in order until one loads."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = page = None
        for n, (label, urls) in enumerate(jobs):
            # (re)start the browser at the beginning, every `restart_every`
            # schools, or if it died
            need_new = (browser is None or page is None or page.is_closed()
                        or (restart_every and n and n % restart_every == 0))
            if need_new:
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass
                try:
                    browser = p.chromium.launch(headless=False)
                    page = browser.new_page()
                except Exception as e:
                    print(f"[fail] {label}: browser could not start ({_short(e)})", file=sys.stderr)
                    browser = page = None
                    continue
            if n and delay:
                time.sleep(delay)

            loaded = False
            for url in urls:
                try:
                    page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                    pages.append((url, _grab_all_tabs(page, timeout_ms)))
                    loaded = True
                    break
                except Exception as e:
                    print(f"[fail] {label}: {url} did not load ({_short(e)})", file=sys.stderr)
                    _save_debug(page, label)
            if not loaded and len(urls) > 1:
                print(f"[fail] {label}: none of its snapshot pages loaded", file=sys.stderr)
            print(f"[{n + 1}/{len(jobs)}] done {label}", file=sys.stderr)
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass


def fetch_rendered_html(jobs, timeout_ms=PAGE_TIMEOUT_SECONDS * 1000,
                        delay=0, restart_every=RESTART_DRIVER_EVERY):
    """jobs: list of URLs, or list of (label, [urls to try in order])."""
    import threading
    jobs = [(j, [j]) if isinstance(j, str) else j for j in jobs]
    pages, errors = [], []

    def run():
        try:
            _fetch_worker(jobs, pages, timeout_ms, delay, restart_every)
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=run)
    t.start()
    t.join()
    if errors:
        print(f"[fail] browser stopped early: {_short(errors[0])} "
              f"(keeping the {len(pages)} page(s) already loaded)", file=sys.stderr)
    return pages


def collect_files(inputs):
    exts = {".html", ".htm", ".rtf", ".txt"}
    files = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in exts)
        elif p.exists():
            files.append(p)
        else:
            print(f"[warn] not found: {inp}", file=sys.stderr)
    return files


def _write_csv(sources, output, include_id):
    """Parse (source, html) pairs, keep HS pages only, write the CSV."""
    columns = ID_COLUMNS + CODEBOOK_COLUMNS if include_id else CODEBOOK_COLUMNS
    rows, seen = [], set()
    for src, html in sources:
        try:
            row, reason = parse_hs_page(html)
        except Exception as e:
            print(f"[fail] {src}: could not parse ({_short(e)})", file=sys.stderr)
            continue
        if row is None:
            print(f"[skip] {src}: {reason}", file=sys.stderr)
            continue
        if row["dbn"] and row["dbn"] in seen:
            print(f"[skip] {src}: duplicate {row['dbn']}", file=sys.stderr)
            continue
        seen.add(row["dbn"])
        blanks = [c for c in CODEBOOK_COLUMNS if row[c] == ""]
        if blanks:
            print(f"[note] {row['dbn']}: {len(blanks)} empty field(s): {', '.join(blanks)}", file=sys.stderr)
        rows.append(row)
        print(f"[ok]   {src}: {row['school_name']} ({row['dbn']})", file=sys.stderr)

    with open(output, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} HS school row(s) to {output}", file=sys.stderr)
    return rows


def scrape_schools(limit=TRIAL_LIMIT, output=OUTPUT_CSV, include_id=True):
    """
    Scrape the schools listed in the demographics spreadsheet
    (DEMOGRAPHICS_XLSX_PATH / DEMOGRAPHICS_YEAR). limit=10 -> first 10 only.
    """
    schools = get_schools()
    print(f"{len(schools)} school(s) with grade 9-12 students in {DEMOGRAPHICS_YEAR}", file=sys.stderr)
    if limit:
        schools = schools[:limit]
        print(f"TRIAL RUN: scraping only the first {len(schools)}", file=sys.stderr)
    jobs = [(dbn, [BASE_URL.format(year=SNAPSHOT_YEAR, dbn=dbn, type=t) for t in types])
            for dbn, types in schools]
    sources = fetch_rendered_html(jobs, delay=DELAY_BETWEEN_SCHOOLS_SECONDS)
    return _write_csv(sources, output, include_id)


def scrape(inputs=(), urls=(), output=OUTPUT_CSV, include_id=True):
    """
    Scrape saved outer-HTML files and/or specific URLs:

        from hs_scraper import scrape
        scrape(inputs=["saved_pages/"], output="hs_data.csv")
        scrape(urls=["<url1>", "<url2>"], output="hs_data.csv")

    Non-HS pages, failed URLs and unreadable files are reported and skipped;
    they never stop the run. Returns the list of row dicts that were written.
    """
    if isinstance(inputs, (str, Path)):
        inputs = [inputs]
    if isinstance(urls, str):
        urls = [urls]

    sources = []
    for f in collect_files(inputs):
        try:
            sources.append((str(f), load_html(f)))
        except Exception as e:
            print(f"[fail] {f}: could not read ({_short(e)})", file=sys.stderr)
    if urls:
        sources += fetch_rendered_html(list(urls), delay=DELAY_BETWEEN_SCHOOLS_SECONDS)
    return _write_csv(sources, output, include_id)


def main():
    ap = argparse.ArgumentParser(description="Scrape NYC School Quality Snapshot HS pages to CSV.")
    ap.add_argument("inputs", nargs="*", help="Saved outer-HTML files (.html/.rtf/.txt) or folders")
    ap.add_argument("--url", nargs="*", default=[], help="Specific snapshot URLs to render")
    ap.add_argument("--limit", type=int, default=TRIAL_LIMIT,
                    help="Trial run: only the first N schools from the spreadsheet")
    ap.add_argument("-o", "--output", default=OUTPUT_CSV)
    ap.add_argument("--no-id", action="store_true", help="Omit dbn/school_name columns")
    args = ap.parse_args()
    if args.inputs or args.url:
        scrape(args.inputs, args.url, args.output, include_id=not args.no_id)
    else:  # no files/URLs given -> use the demographics spreadsheet
        scrape_schools(args.limit, args.output, include_id=not args.no_id)


if __name__ == "__main__":
    main()