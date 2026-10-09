from __future__ import annotations
import argparse
import csv
import sys
import time
import re
from pathlib import Path

from bs4 import BeautifulSoup

# ==========================================================================
# SETTINGS
# ==========================================================================
TRIAL_LIMIT = None

OUTPUT_CSV = "hst_school_data23.csv"
PAGE_TIMEOUT_SECONDS = 60
DEBUG_DIR = "scrape_debug"

DEFAULT_DBNS = (
    "01M458,01M515,01M650,02M313,02M394,02M544,02M550,02M560,02M565,02M570,"
    "02M575,02M586,03M404,04M310,04M505,05M285,06M423,07X379,07X381,07X557,"
    "08X377,08X537,09X350,10X319,10X397,12X446,12X480,13K553,13K616,15K423,"
    "15K529,15K698,16K669,17K568,17K646,18K578,18K635,18K673,21K728,22K630,"
    "23K643,23K647,24Q744,25Q540,25Q792,27Q261,28Q338,31R470,32K564,84K417,"
    "84K486,84M424,84M707,84Q388,84Q428,84R012,84X610"
)


def parse_dbns(raw: str) -> list[str]:
    """'01m458, 01M515\n02M313' -> ['01M458', '01M515', '02M313'] (deduped, order kept)."""
    tokens = raw.replace("\n", ",").replace(";", ",").split(",")
    dbns = [t.strip().upper() for t in tokens if t.strip()]
    return list(dict.fromkeys(dbns))


CANDIDATE_TYPES = ("HST",)
MANUAL_TYPE_OVERRIDES: dict[str, str] = {}


def _candidate_types_for(dbn: str) -> list[str]:
    pinned = MANUAL_TYPE_OVERRIDES.get(dbn)
    if pinned:
        return [pinned] + [t for t in CANDIDATE_TYPES if t != pinned]
    return list(CANDIDATE_TYPES)


def get_schools(dbn_arg: str | None = None) -> list[tuple[str, list[str]]]:
    """[(dbn, [types to try]), ...] from a comma-separated string.
    Falls back to DEFAULT_DBNS when no string is given."""
    dbns = parse_dbns(dbn_arg if dbn_arg else DEFAULT_DBNS)
    return [(dbn, _candidate_types_for(dbn)) for dbn in dbns]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--dbns",
        help="Comma-separated DBNs to scrape, e.g. 01M458,02M313 "
             "(defaults to the built-in list)",
    )
    return p.parse_args()

SNAPSHOT_YEAR = "2023"

BASE_URL = "https://tools.nycenet.edu/snapshot/{year}/{dbn}/{type}/"

DELAY_BETWEEN_SCHOOLS_SECONDS = 3
RESTART_DRIVER_EVERY = 100

# Skipping "About the NYC School Survey" / "Survey Response Rates" section
EXCLUDED_GROUP_CLASSES = {"survey-rr"}

# Report type printed under the page title; anything else is skipped.
REPORT_TYPE = "Transfer High School"

# --------------------------------------------------------------------------
# Output columns (codebook order). dbn / school_name are identifiers so rows
# can be told apart; drop them with --no-id.
# --------------------------------------------------------------------------
ID_COLUMNS = ["dbn", "school_name"]
CODEBOOK_COLUMNS = [
    "hst_sd_1ip", "hst_sd_1ssc", "hst_sd_1rf",
    "hst_sd_2w", "hst_sd_2p", "hst_sp_2g", "hst_sd_2e", "hst_sd_2am", "hst_sd_2as",
    "hst_sd_2a", "hst_sd_2l", "hst_sd_2n",
    "hst_sd_3as", "hst_sd_3bl", "hst_sd_3hst", "hst_sd_3na", "hst_sd_3pi", "hst_sd_3wh",
    "hst_sd_3ell", "hst_sd_3iep", "hst_sd_3eni", "hst_sd_3ouc", "hst_sd_3f", "hst_sd_3m",
    "hst_sd_3nb",
    "hst_sd_4qvar", "hst_sd_4spt", "hst_sd_4ec", "hst_sd_4art", "hst_sd_4ps",
    "hst_sd_5as", "hst_sd_5bl", "hst_sd_5hst", "hst_sd_5na", "hst_sd_5pi", "hst_sd_5wh",
    "hst_sd_5py", "hst_sd_5t3",
    "hst_sd_6q1a", "hst_sd_6q1b", "hst_sd_6q1h", "hst_sd_6q1n", "hst_sd_6q1p",
    "hst_sd_6q1w", "hst_sd_6q1e", "hst_sd_6q1i", "hst_sd_6q2", "hst_sd_6q3",
    "hst_ip_1crs", "hst_ip_1pc", "hst_ip_1ce",
    "hst_ip_2ap", "hst_ip_2nap",
    "hst_ip_2ra", "hst_ip_2rb", "hst_ip_2rh", "hst_ip_2rn", "hst_ip_2rp", "hst_ip_2rw",
    "hst_ip_3mv", "hst_ip_3sef", "hst_ip_3sep", "hst_ip_3sen",
    "hst_ip_3rsf", "hst_ip_3rsp", "hst_ip_3rsn",
    "hst_ip_4gr", "hst_ip_4gra", "hst_ip_4grb", "hst_ip_4grh", "hst_ip_4grn",
    "hst_ip_4grp", "hst_ip_4grw", "hst_ip_4grf", "hst_ip_4grm", "hst_ip_4gre",
    "hst_ip_4gri", "hst_ip_4mar", "hst_ip_4ouc", "hst_ip_4hstp",
    "hst_ip_5q", "hst_ip_5q1", "hst_ip_5q1a", "hst_ip_5q1b", "hst_ip_5q1h",
    "hst_ip_5q1n", "hst_ip_5q1p", "hst_ip_5q1w", "hst_ip_5q1e", "hst_ip_5q1i",
    "hst_ssc_1qp", "hst_ssc_1q1", "hst_ssc_1q1a", "hst_ssc_1q1b", "hst_ssc_1q1h",
    "hst_ssc_1q1n", "hst_ssc_1q1p", "hst_ssc_1q1w", "hst_ssc_1q1e", "hst_ssc_1q1i",
    "hst_ssc_2qp", "hst_ssc_2q1", "hst_ssc_2q2",
    "hst_ssc_3qp", "hst_ssc_3q1", "hst_ssc_3q1a", "hst_ssc_3q1b", "hst_ssc_3q1h",
    "hst_ssc_3q1n", "hst_ssc_3q1p", "hst_ssc_3q1w", "hst_ssc_3q1e", "hst_ssc_3q1i",
    "hst_ssc_4sa", "hst_ssc_4sa90", "hst_ssc_4ta",
    "hst_ssc_5qp",
    "hst_ssc_5q1", "hst_ssc_5q1a", "hst_ssc_5q1b", "hst_ssc_5q1h", "hst_ssc_5q1n",
    "hst_ssc_5q1p", "hst_ssc_5q1w", "hst_ssc_5q1e", "hst_ssc_5q1i",
    "hst_ssc_5q2", "hst_ssc_5q2a", "hst_ssc_5q2b", "hst_ssc_5q2h", "hst_ssc_5q2n",
    "hst_ssc_5q2p", "hst_ssc_5q2w", "hst_ssc_5q2e", "hst_ssc_5q2i",
    "hst_ssc_5q3", "hst_ssc_5q3a", "hst_ssc_5q3b", "hst_ssc_5q3h", "hst_ssc_5q3n",
    "hst_ssc_5q3p", "hst_ssc_5q3w", "hst_ssc_5q3e", "hst_ssc_5q3i",
    "hst_rf_1qp", "hst_rf_1q1", "hst_rf_1q1a", "hst_rf_1q1b", "hst_rf_1q1h",
    "hst_rf_1q1n", "hst_rf_1q1p", "hst_rf_1q1w", "hst_rf_1q1e", "hst_rf_1q1i",
    "hst_rf_2qp", "hst_rf_2q1", "hst_rf_2q1a", "hst_rf_2q1b", "hst_rf_2q1h",
    "hst_rf_2q1n", "hst_rf_2q1p", "hst_rf_2q1w", "hst_rf_2q1e", "hst_rf_2q1i",
    "hst_rf_3qp", "hst_rf_3q1", "hst_rf_3q1a", "hst_rf_3q1b", "hst_rf_3q1h",
    "hst_rf_3q1n", "hst_rf_3q1p", "hst_rf_3q1w", "hst_rf_3q1e", "hst_rf_3q1i",
]

# Suffix letter -> subgroup key used by the chart parser.
# (Convention used throughout the codebook: a=Asian, b=Black, h=Hispanic,
#  n=Native American, p=Pacific Islander, w=White, e=ELL, i=IEP.)
SUBGROUP_SUFFIX = {
    "a": "asian", "b": "black", "h": "hispanic", "n": "native_american",
    "p": "pacific_islander", "w": "white", "e": "ell", "i": "iep",
}
SUFFIX_SETS = {
    "all8": "abhnpwei",   # race + ELL + IEP
    "race6": "abhnpw",    # race only
}


# --------------------------------------------------------------------------
# Loading
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
    if el is None:
        return ""
    el = BeautifulSoup(str(el), "lxml")
    for cls in drop_classes:
        for s in el.select(f"span.{cls}"):
            s.decompose()
    return clean(el.get_text(" "))


def group(scope, cls):
    return scope.select_one(f"div.metric-group.{cls}") if scope else None


def colon_values(scope):
    out = {}
    if scope is None:
        return out
    for div in scope.select("div.metric-colon"):
        lab = div.select_one("span.label")
        key = norm(lab.get_text(" ") if lab else "")
        out[key] = own_text(div)
    return out


def rating_word(svg_parent):
    if svg_parent is None:
        return ""
    svg = svg_parent if svg_parent.name == "svg" else svg_parent.find("svg", attrs={"aria-label": True})
    if svg is None:
        return ""
    m = re.search(r"Bars?,\s*(.+)$", svg.get("aria-label", ""))
    return clean(m.group(1)) if m else clean(svg.get("aria-label", ""))


def bignum(scope, fragment):
    if scope is None:
        return ""
    for block in scope.select("div.metric-bignum"):
        desc = block.select_one(".description")
        if desc and norm(fragment) in norm(desc.get_text(" ")):
            val = block.select_one(".school-value")
            return clean(val.get_text(" ")) if val else ""
    return ""


def subgroup_key(label):
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
# Legacy-layout parser (2022-23 style pages: tabs info/sa/ri/ct/se/es/sf/tr).
# Only fills codebook columns whose item is the same on the old page.
# Everything else stays "" (blank). No new columns.
# --------------------------------------------------------------------------
LEGACY_TAB_KEYS = ("info", "sa", "se", "sf", "tr")   # only tabs we read from


def parse_hst_page_legacy(soup, row):
    def tab(k):
        return soup.select_one(f"#tab-content-{k}")

    info, sa, se, sf, tr = (tab(k) for k in LEGACY_TAB_KEYS)

    # ---- School Info: General Information
    gen = group(info, "gen")
    if gen is not None:
        for div in gen.select("div.metric-colon"):
            lab = norm(div.select_one("span.label").get_text(" ")) if div.select_one("span.label") else ""
            if lab == "school website":
                a = div.find("a")
                row["hst_sd_2w"] = clean(a.get_text()) if a else own_text(div)
        cv = colon_values(gen)
        row["hst_sd_2p"] = cv.get("principal", "")
        row["hst_sp_2g"] = cv.get("grades served", "")        # blank if page has none
        row["hst_sd_2e"] = cv.get("enrollment", "")
        row["hst_sd_2am"] = cv.get("admissions methods", "")  # blank if page has none
        # hst_sd_2as (state accountability status): no equivalent -> blank

    loc = group(info, "location")
    if loc is not None:
        links = [clean(d.get_text(" ")) for d in loc.select("div.address")]
        row["hst_sd_2a"] = links[0] if len(links) > 0 else ""
        row["hst_sd_2l"] = links[1] if len(links) > 1 else ""
        ph = loc.select_one("div.phone")
        row["hst_sd_2n"] = re.sub(r"^Phone:\s*", "", clean(ph.get_text())) if ph else ""

    # Headings are looked up across the whole Info tab, because on older pages
    # they sit in different groups from page to page.
    cv = colon_values(section_after_heading(info, "Student Demographics"))
    row["hst_sd_3as"] = cv.get("asian", "")
    row["hst_sd_3bl"] = cv.get("black", "")
    row["hst_sd_3hst"] = cv.get("hispanic or latinx", "")
    row["hst_sd_3na"] = cv.get("native american", "")
    row["hst_sd_3pi"] = cv.get("native hawaiian pacific islander", "")
    row["hst_sd_3wh"] = cv.get("white", "")
    row["hst_sd_3ell"] = cv.get("english language learners", "")
    row["hst_sd_3iep"] = cv.get("students with ieps", "")
    row["hst_sd_3eni"] = cv.get("economic need index", "")
    row["hst_sd_3ouc"] = cv.get("overage under credited", "")
    row["hst_sd_3f"] = cv.get("female", "")
    row["hst_sd_3m"] = cv.get("male", "")
    row["hst_sd_3nb"] = cv.get("neither female nor male", "")

    # ---- Programs
    row["hst_sd_4qvar"] = survey_question(info, "wide enough variety of programs").get("all", "")
    psal = section_after_heading(info, "PSAL Sports")
    if psal is not None:
        parts = []
        for div in psal.select("div.metric-colon"):
            lab = clean(div.select_one("span.label").get_text(" ")) if div.select_one("span.label") else ""
            parts.append(f"{lab} {own_text(div)}".strip())
        row["hst_sd_4spt"] = "; ".join(parts)
    for heading, col in (("Extracurricular Activities", "hst_sd_4ec"),
                         ("Arts Classes", "hst_sd_4art"),
                         ("Programs and State Designation", "hst_sd_4ps")):
        sec = section_after_heading(info, heading)
        if sec is not None:
            row[col] = "; ".join(clean(d.get_text(" ")) for d in sec.select("div.description"))

    # ---- Teacher demographics / staff experience
    cv = colon_values(section_after_heading(info, "Teacher Demographics"))
    row["hst_sd_5as"] = cv.get("asian", "")
    row["hst_sd_5bl"] = cv.get("black", "")
    row["hst_sd_5hst"] = cv.get("hispanic or latinx", "")
    row["hst_sd_5na"] = cv.get("native american", "")
    row["hst_sd_5pi"] = cv.get("native hawaiian pacific islander", "")
    row["hst_sd_5wh"] = cv.get("white", "")
    cv = colon_values(section_after_heading(info, "Staff Experience"))
    row["hst_sd_5py"] = cv.get("years of experience as principal at this school", "")
    # older pages spell it "three" instead of "3"
    row["hst_sd_5t3"] = (cv.get("teachers with 3 or more years of experience")
                         or cv.get("teachers with three or more years of experience", ""))

    # hst_sd_1* (overall ratings) and hst_sd_6* (facilities): no match -> blank

    # ---- Advanced courses (Info tab)
    vl = value_list(group(info, "adv_courses"),
                    "How many students were enrolled in at least one advanced class")
    row["hst_ip_2ap"] = vl.get("advanced placement", "")
    row["hst_ip_2nap"] = next((v for k, v in vl.items() if "non ap" in k), "")
    adv = group(info, "adv-demog")
    adv_chart = adv.select_one("div.metric-viz-comp-bars") if adv else None
    put_subgroups(row, "hst_ip_2r", chart_rows(adv_chart, "adv-courses"),
                  SUFFIX_SETS["race6"], all_col=False)

    # ---- Student Achievement tab: graduation + college/career
    ccr = group(sa, "ccr")
    # hst_ip_1crs (average CCR score): not on old page -> blank
    row["hst_ip_1pc"] = bignum(ccr, "successfully completed approved college or career preparatory")
    row["hst_ip_1ce"] = bignum(ccr, "enrolled in college or other post-secondary")

    grad = group(sa, "grad")
    row["hst_ip_4gr"] = bignum(grad, "of students graduated high school")
    sub = section_after_heading(grad, "Graduation Rate by Subgroup")
    g = chart_rows(sub, "main") if sub is not None else {}
    for suf, key in (("a", "asian"), ("b", "black"), ("h", "hispanic"),
                     ("n", "native_american"), ("p", "pacific_islander"),
                     ("w", "white"), ("f", "female"), ("m", "male"),
                     ("e", "ell"), ("i", "iep")):
        row["hst_ip_4gr" + suf] = g.get(key, "")
    row["hst_ip_4mar"] = bignum(grad, "entered this school very far off-track")
    row["hst_ip_4ouc"] = bignum(grad, "graduation rate for students who entered this school far off-track")
    row["hst_ip_4hstp"] = bignum(grad, "earned a high school equivalency")

    # ---- Supportive Environment tab
    row["hst_ip_3mv"] = rating_word(group(se, "lre"))
    swiep = group(se, "swiep")
    s_ = value_list(swiep, "recommended special education programs")
    row["hst_ip_3sef"] = s_.get("received in full", "")
    row["hst_ip_3sep"] = s_.get("received in part", "")
    row["hst_ip_3sen"] = s_.get("did not receive", "")
    r_ = value_list(swiep, "recommended related services")
    row["hst_ip_3rsf"] = r_.get("received in full", "")
    row["hst_ip_3rsp"] = r_.get("received in part", "")
    row["hst_ip_3rsn"] = r_.get("did not receive", "")

    put_subgroups(row, "hst_ssc_1q1", survey_question(se, "feel safe in the hallways"),
                  SUFFIX_SETS["all8"])
    put_subgroups(row, "hst_ssc_5q1", survey_question(se, "support them when they are upset"),
                  SUFFIX_SETS["all8"])

    att = group(se, "gen")      # the only "gen" group on this tab = Attendance
    if att is not None:
        for d in att.select("div.description"):
            mm = re.match(r"Student attendance:\s*(.+)$", own_text(d), re.I)
            if mm:
                row["hst_ssc_4sa"] = mm.group(1)
        row["hst_ssc_4ta"] = colon_values(att).get("teacher attendance", "")
    # hst_ssc_4sa90 and (on transfer pages) hst_ssc_4sa: different metric -> blank

    # ---- Trust tab
    # (differs from the new-layout fragment by one verb form: "treat" vs "treats")
    put_subgroups(row, "hst_ssc_5q2", survey_question(tr, "them with respect"),
                  SUFFIX_SETS["all8"])
    put_subgroups(row, "hst_rf_3q1", survey_question(tr, "build trusting relationships with families"),
                  SUFFIX_SETS["all8"])

    # ---- Strong Family-Community Ties tab
    # (differs from the new-layout fragment: "communicate ... how families can help"
    #  vs "communicates ... how they can help"; delete this call to leave blank)
    put_subgroups(row, "hst_rf_1q1",
                  survey_question(sf, "regularly communicate with them about how"),
                  SUFFIX_SETS["all8"])
    put_subgroups(row, "hst_rf_2q1",
                  survey_question(sf, "communicated with their child's teacher about their child's performance"),
                  SUFFIX_SETS["all8"])

    # Everything else (survey % headlines, hst_ip_5q*, hst_ssc_2*, 3*, 5qp, 5q3*,
    # hst_rf_*qp, ...) intentionally stays blank.
    return row


# --------------------------------------------------------------------------
# Main parser
# --------------------------------------------------------------------------
def parse_hst_page(html: str):
    soup = BeautifulSoup(html, "lxml")
    for cls in EXCLUDED_GROUP_CLASSES:
        for el in soup.select(f"div.metric-group.{cls}"):
            el.decompose()

    school_type = soup.select_one("p.school-type")
    school_type = clean(school_type.get_text()) if school_type else ""
    if school_type.lower() != REPORT_TYPE.lower():
        return None, f"report type is '{school_type or 'unknown'}', not '{REPORT_TYPE}'"

    row = {c: "" for c in ID_COLUMNS + CODEBOOK_COLUMNS}

    # Identifiers
    name_el = soup.select_one("div.school-name")
    full_name = clean(name_el.get_text()) if name_el else ""
    m = re.match(r"(.*)\((\w{6})\)\s*$", full_name)
    row["school_name"], row["dbn"] = (clean(m.group(1)), m.group(2)) if m else (full_name, "")

    # Older snapshot years use a different layout (tabs info/sa/ri/ct/se/es/sf/tr)
    if soup.select_one("#tab-content-sa") is not None:
        return parse_hst_page_legacy(soup, row), None

    info = soup.select_one("#tab-content-info")
    ip = soup.select_one("#tab-content-ip")
    ss = soup.select_one("#tab-content-ss")
    rf = soup.select_one("#tab-content-rf")

    # ---------------- School Description ----------------
    # 1. Overall School Ratings (School Description tab only)
    fr = info.select_one("div.framework-ratings") if info else None
    if fr:
        for href, col in (("#IP", "hst_sd_1ip"), ("#SS", "hst_sd_1ssc"), ("#RF", "hst_sd_1rf")):
            a = fr.select_one(f'a[href="{href}"]')
            row[col] = rating_word(a)

    # 2. Overview (Average SAT and About This School are skipped)
    ov = group(info, "gen")
    if ov is not None:
        for div in ov.select("div.metric-colon"):
            lab = norm(div.select_one("span.label").get_text(" ")) if div.select_one("span.label") else ""
            if lab == "school website":
                a = div.find("a")
                row["hst_sd_2w"] = clean(a.get_text()) if a else own_text(div)
        cv = colon_values(ov)
        row["hst_sd_2p"] = cv.get("principal", "")
        row["hst_sp_2g"] = cv.get("grades served", "")
        row["hst_sd_2e"] = cv.get("enrollment", "")
        row["hst_sd_2am"] = cv.get("admissions methods", "")
        row["hst_sd_2as"] = cv.get("state accountability status", "")
    loc = group(info, "location")
    if loc is not None:
        links = [clean(d.get_text(" ")) for d in loc.select("div.address")]
        row["hst_sd_2a"] = links[0] if len(links) > 0 else ""        # street address
        row["hst_sd_2l"] = links[1] if len(links) > 1 else ""        # city, state ZIP
        ph = loc.select_one("div.phone")
        row["hst_sd_2n"] = re.sub(r"^Phone:\s*", "", clean(ph.get_text())) if ph else ""

    # 3. Student Body -> Student Demographics (Surrounding Demographics skipped)
    demo = section_after_heading(group(info, "sch-demog"), "Student Demographics")
    cv = colon_values(demo)
    row["hst_sd_3as"] = cv.get("asian", "")
    row["hst_sd_3bl"] = cv.get("black", "")
    row["hst_sd_3hst"] = cv.get("hispanic or latinx", "")
    row["hst_sd_3na"] = cv.get("native american", "")
    row["hst_sd_3pi"] = cv.get("native hawaiian pacific islander", "")
    row["hst_sd_3wh"] = cv.get("white", "")
    row["hst_sd_3ell"] = cv.get("english language learners", "")
    row["hst_sd_3iep"] = cv.get("students with ieps", "")
    row["hst_sd_3eni"] = cv.get("economic need index", "")
    row["hst_sd_3ouc"] = cv.get("overage under credited", "")
    row["hst_sd_3f"] = cv.get("female", "")
    row["hst_sd_3m"] = cv.get("male", "")
    row["hst_sd_3nb"] = cv.get("neither female nor male", "")

    # 4. Programs
    prog = group(info, "program")
    row["hst_sd_4qvar"] = survey_question(prog, "wide enough variety of programs").get("all", "")
    sports = section_after_heading(prog, "PSAL Sports")
    if sports is not None:
        parts = []
        for div in sports.select("div.metric-colon"):
            lab = clean(div.select_one("span.label").get_text(" ")) if div.select_one("span.label") else ""
            parts.append(f"{lab} {own_text(div)}".strip())
        row["hst_sd_4spt"] = "; ".join(parts)
    for heading, col in (("Extracurricular Activities", "hst_sd_4ec"),
                         ("Arts Classes", "hst_sd_4art"),
                         ("NYCPS Programs", "hst_sd_4ps")):
        sec = section_after_heading(prog, heading)
        if sec is not None:
            row[col] = "; ".join(clean(d.get_text(" ")) for d in sec.select("div.description"))

    # 5. Staff/Faculty
    staff = group(info, "staff")
    cv = colon_values(section_after_heading(staff, "Teacher Demographics"))
    row["hst_sd_5as"] = cv.get("asian", "")
    row["hst_sd_5bl"] = cv.get("black", "")
    row["hst_sd_5hst"] = cv.get("hispanic or latinx", "")
    row["hst_sd_5na"] = cv.get("native american", "")
    row["hst_sd_5pi"] = cv.get("native hawaiian pacific islander", "")
    row["hst_sd_5wh"] = cv.get("white", "")
    cv = colon_values(section_after_heading(staff, "Staff Experience"))
    row["hst_sd_5py"] = cv.get("years of experience as principal at this school", "")
    row["hst_sd_5t3"] = cv.get("teachers with 3 or more years of experience", "")

    # 6. School Facilities and Services (Shared Space skipped)
    space = group(info, "space")
    put_subgroups(row, "hst_sd_6q1", survey_question(space, "school is kept clean"),
                  SUFFIX_SETS["all8"], all_col=False)
    row["hst_sd_6q2"] = survey_question(space, "kept in good physical condition").get("all", "")
    row["hst_sd_6q3"] = survey_question(space, "physical repairs to this school building").get("all", "")

    # ---------------- Instruction and Performance ----------------
    # (the "Overall Rating for Instruction and Performance" banner is skipped)
    ccr = group(ip, "ccr")
    # Transfer pages show the *growth* (e.g. +20%) as the big number and the
    # average score inside the sentence: "...The average college and career
    # readiness score for students is 24." -> 24
    row["hst_ip_1crs"] = ""
    for block in (ccr.select("div.metric-bignum") if ccr else []):
        desc = clean(block.select_one(".description").get_text(" ")) if block.select_one(".description") else ""
        mm = re.search(r"average college and career readiness score for students is\s*(\d+(?:\.\d+)?|N/A)", desc, re.I)
        if mm:
            row["hst_ip_1crs"] = mm.group(1)
            break
    else:
        row["hst_ip_1crs"] = bignum(ccr, "average college and career readiness score")
    row["hst_ip_1pc"] = bignum(ccr, "successfully completed approved college or career preparatory")
    row["hst_ip_1ce"] = bignum(ccr, "enrolled in college or other post-secondary")

    adv = group(ip, "adv-demog")
    vl = value_list(adv, "How many students were enrolled in at least one advanced class")
    row["hst_ip_2ap"] = vl.get("advanced placement", "")
    row["hst_ip_2nap"] = next((v for k, v in vl.items() if "non ap" in k), "")
    adv_chart = adv.select_one("div.metric-viz-comp-bars") if adv else None
    put_subgroups(row, "hst_ip_2r", chart_rows(adv_chart, "adv-courses"),
                  SUFFIX_SETS["race6"], all_col=False)

    lre = group(ip, "lre")
    row["hst_ip_3mv"] = rating_word(lre)

    swiep = group(ip, "swiep")
    se = value_list(swiep, "recommended special education programs")
    row["hst_ip_3sef"] = se.get("received in full", "")
    row["hst_ip_3sep"] = se.get("received in part", "")
    row["hst_ip_3sen"] = se.get("did not receive", "")
    rs = value_list(swiep, "recommended related services")
    row["hst_ip_3rsf"] = rs.get("received in full", "")
    row["hst_ip_3rsp"] = rs.get("received in part", "")
    row["hst_ip_3rsn"] = rs.get("did not receive", "")

    grad = group(ip, "grad")
    row["hst_ip_4gr"] = bignum(grad, "of students graduated high school")
    sub = section_after_heading(grad, "Graduation Rate by Subgroup")
    g = chart_rows(sub, "main") if sub is not None else {}
    for suf, key in (("a", "asian"), ("b", "black"), ("h", "hispanic"),
                     ("n", "native_american"), ("p", "pacific_islander"),
                     ("w", "white"), ("f", "female"), ("m", "male"),
                     ("e", "ell"), ("i", "iep")):
        row["hst_ip_4gr" + suf] = g.get(key, "")
    row["hst_ip_4mar"] = bignum(grad, "entered this school very far off-track")
    row["hst_ip_4ouc"] = bignum(grad, "graduation rate for students who entered this school far off-track")
    row["hst_ip_4hstp"] = bignum(grad, "earned a high school equivalency")

    le = group(ip, "learning-env")
    row["hst_ip_5q"] = bignum(le, "instruction/learning environment")
    put_subgroups(row, "hst_ip_5q1",
                  survey_question(le, "treat students of different races, cultures, or backgrounds equally"),
                  SUFFIX_SETS["all8"])

    # ---------------- Safety and School Climate ----------------
    # (the "Overall Rating for Safety and School Climate" banner is skipped)
    saf = group(ss, "safety")
    row["hst_ssc_1qp"] = bignum(saf, "survey questions about safety")
    put_subgroups(row, "hst_ssc_1q1", survey_question(saf, "feel safe in the hallways"),
                  SUFFIX_SETS["all8"])

    lead = group(ss, "school-leadership")
    row["hst_ssc_2qp"] = bignum(lead, "survey questions about school leadership")
    row["hst_ssc_2q1"] = survey_question(lead, "sets high standards for student learning").get("all", "")
    row["hst_ssc_2q2"] = survey_question(lead, "encourages feedback through regular meetings").get("all", "")

    advis = group(ss, "advising")
    row["hst_ssc_3qp"] = bignum(advis, "survey questions about advising and planning")
    put_subgroups(row, "hst_ssc_3q1", survey_question(advis, "help them plan for how to meet their future career goals"),
                  SUFFIX_SETS["all8"])

    att = group(ss, "attendance")
    if att is not None:
        for d in att.select("div.description"):
            t = own_text(d)
            mm = re.match(r"Student attendance:\s*(.+)$", t, re.I)
            if mm:
                row["hst_ssc_4sa"] = mm.group(1)
            mm = re.match(r"Students with >\s*90% attendance:\s*(.+)$", t, re.I)
            if mm:
                row["hst_ssc_4sa90"] = mm.group(1)
        row["hst_ssc_4ta"] = colon_values(att).get("teacher attendance", "")

    sup = group(ss, "stu-support")
    row["hst_ssc_5qp"] = bignum(sup, "survey questions about student support")
    put_subgroups(row, "hst_ssc_5q1", survey_question(sup, "support them when they are upset"), SUFFIX_SETS["all8"])
    put_subgroups(row, "hst_ssc_5q2", survey_question(sup, "treats them with respect"), SUFFIX_SETS["all8"])
    put_subgroups(row, "hst_ssc_5q3", survey_question(sup, "feel like they belong at this school"), SUFFIX_SETS["all8"])

    # ---------------- Relationships with Families ----------------
    # (the "Overall Rating for Relationships with Families" banner is skipped)
    com = group(rf, "communication")
    row["hst_rf_1qp"] = bignum(com, "survey questions about communication")
    put_subgroups(row, "hst_rf_1q1", survey_question(com, "regularly communicates with them about how they can help"),
                  SUFFIX_SETS["all8"])

    fam = group(rf, "family-involve")
    row["hst_rf_2qp"] = bignum(fam, "survey questions about family involvement")
    put_subgroups(row, "hst_rf_2q1", survey_question(fam, "communicated with their child's teacher about their child's performance"),
                  SUFFIX_SETS["all8"])

    trust = group(rf, "relation-w-family")
    row["hst_rf_3qp"] = bignum(trust, "survey questions about family-school trust")
    put_subgroups(row, "hst_rf_3q1", survey_question(trust, "build trusting relationships with families"),
                  SUFFIX_SETS["all8"])

    return row, None


# --------------------------------------------------------------------------
# Live fetch (Playwright). The snapshot site is a JavaScript app, so the page
# must be rendered.
# --------------------------------------------------------------------------
def _short(e):
    return (str(e).strip().splitlines() or [repr(e)])[0][:200]


TAB_KEYS = ("info", "ip", "ss", "rf")


def _grab_all_tabs(page, timeout_ms):
    # Current layout: info / ip / ss / rf.  Older layout (has a #tab-button-sa):
    # info / sa / se / sf / tr.
    keys = LEGACY_TAB_KEYS if page.query_selector("#tab-button-sa") else TAB_KEYS
    tabs = {}
    for key in keys:
        content = f"#tab-content-{key} .metric-group"
        if page.query_selector(content) is None:
            button = page.query_selector(f"#tab-button-{key}")
            if button is not None:
                button.click()
        page.wait_for_selector(content, state="attached", timeout=timeout_ms)
        page.wait_for_timeout(500)  # let the charts finish drawing
        tabs[key] = page.eval_on_selector(f"#tab-content-{key}", "e => e.outerHTML")

    # Rest of the page (header with school name + report type), minus any
    # tab panels, followed by the tabs captured above.
    soup = BeautifulSoup(page.evaluate("document.body.outerHTML"), "lxml")
    for el in soup.select('[id^="tab-content-"]'):
        el.decompose()
    return str(soup) + "".join(tabs[k] for k in keys)


def _save_debug(page, label):
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
    columns = ID_COLUMNS + CODEBOOK_COLUMNS if include_id else CODEBOOK_COLUMNS
    rows, seen = [], set()
    for src, html in sources:
        try:
            row, reason = parse_hst_page(html)
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
    print(f"Wrote {len(rows)} HST school row(s) to {output}", file=sys.stderr)
    return rows


def scrape_schools(limit=TRIAL_LIMIT, output=OUTPUT_CSV, include_id=True, dbns=None, year=None):
    year = year or SNAPSHOT_YEAR
    schools = get_schools(dbns)
    print(f"{len(schools)} school(s) to scrape (snapshot year {year})", file=sys.stderr)
    if limit:
        schools = schools[:limit]
        print(f"TRIAL RUN: scraping only the first {len(schools)}", file=sys.stderr)
    jobs = [(dbn, [BASE_URL.format(year=year, dbn=dbn, type=t) for t in types])
            for dbn, types in schools]
    sources = fetch_rendered_html(jobs, delay=DELAY_BETWEEN_SCHOOLS_SECONDS)
    return _write_csv(sources, output, include_id)


def scrape(inputs=(), urls=(), output=OUTPUT_CSV, include_id=True):
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
    ap = argparse.ArgumentParser(description="Scrape NYC School Quality Snapshot HST pages to CSV.")
    ap.add_argument("inputs", nargs="*", help="Saved outer-HTML files (.html/.rtf/.txt) or folders")
    ap.add_argument("--url", nargs="*", default=[], help="Specific snapshot URLs to render")
    ap.add_argument("--dbns", help="Comma-separated DBNs to scrape (default: built-in list)")
    ap.add_argument("--year", default=SNAPSHOT_YEAR,
                    help="Snapshot URL year, e.g. 2023 for the 2022-23 report (default: %(default)s)")
    ap.add_argument("--limit", type=int, default=TRIAL_LIMIT,
                    help="Trial run: only the first N schools")
    ap.add_argument("-o", "--output", default=OUTPUT_CSV)
    ap.add_argument("--no-id", action="store_true", help="Omit dbn/school_name columns")
    args = ap.parse_args()
    if args.inputs or args.url:
        scrape(args.inputs, args.url, args.output, include_id=not args.no_id)
    else:  # no files/URLs given -> scrape the DBN list
        scrape_schools(args.limit, args.output, include_id=not args.no_id,
                       dbns=args.dbns, year=args.year)


if __name__ == "__main__":
    main()