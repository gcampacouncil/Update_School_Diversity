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

OUTPUT_CSV = "d75_school_data.csv"
PAGE_TIMEOUT_SECONDS = 15
DEBUG_DIR = "scrape_debug"

# --------------------------------------------------------------------------
# Which schools to scrape: D75 DBNs from the NYC demographic snapshot spreadsheet
# --------------------------------------------------------------------------
DEMOGRAPHICS_XLSX_PATH = (
    "/Users/GCampa/Desktop/Updating School Diversity Page/origdata/"
    "demographic-snapshot-2021-22-to-2025-26-public.xlsx"
)
DEMOGRAPHICS_YEAR = "2024-25"

# District 75 schools all have DBNs that start with "75" (e.g. 75K004).
# False = every D75 school in the spreadsheet for DEMOGRAPHICS_YEAR.
# True  = only D75 schools with students in grades 9-12 (same grade rule as the
#         HS scraper).
D75_ONLY_HIGH_SCHOOL_GRADES = False


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


def load_d75_dbns(xlsx_path: str = DEMOGRAPHICS_XLSX_PATH,
                  year: str = DEMOGRAPHICS_YEAR,
                  only_hs_grades: bool = D75_ONLY_HIGH_SCHOOL_GRADES) -> list[str]:
    demos = _load_demographics_sheet(xlsx_path)

    year_col = _find_column(demos, "Year", "School Year", "DBN Year")
    dbn_col = _find_column(demos, "DBN")

    dbn = demos[dbn_col].astype(str).str.strip().str.upper()
    is_year = demos[year_col].astype(str).str.strip() == year
    is_d75 = dbn.str.startswith("75")
    keep = is_year & is_d75

    if only_hs_grades:
        grade_cols = [_find_column(demos, f"Grade {n}") for n in (9, 10, 11, 12)]
        has_hs_grade = pd.concat([demos[c] > 1 for c in grade_cols], axis=1).any(axis=1)
        keep = keep & has_hs_grade

    if not is_year.any():
        sample_years = demos[year_col].astype(str).str.strip().drop_duplicates().tolist()
        raise ValueError(
            f"No rows matched year={year!r} in column {year_col!r}. "
            f"Values actually present in that column: {sample_years}"
        )
    if not keep.any():
        raise ValueError(f"No District 75 (DBN starting with '75') rows found for {year!r}.")

    return dbn[keep].drop_duplicates().tolist()


CANDIDATE_TYPES = ('D75',)
MANUAL_TYPE_OVERRIDES: dict[str, str] = {
}


def _candidate_types_for(dbn: str) -> list[str]:
    pinned = MANUAL_TYPE_OVERRIDES.get(dbn)
    if pinned:
        return [pinned] + [t for t in CANDIDATE_TYPES if t != pinned]
    return list(CANDIDATE_TYPES)


def get_schools() -> list[tuple[str, list[str]]]:
    """[(dbn, [types to try]), ...] -- reads the spreadsheet when called."""
    return [(dbn, _candidate_types_for(dbn)) for dbn in load_d75_dbns()]


SNAPSHOT_YEAR = "2025"

BASE_URL = "https://tools.nycenet.edu/snapshot/{year}/{dbn}/{type}/"

DELAY_BETWEEN_SCHOOLS_SECONDS = 3
RESTART_DRIVER_EVERY = 100

# Skipping "About the NYC School Survey" / "Survey Response Rates" section
EXCLUDED_GROUP_CLASSES = {"survey-rr"}

# Report type printed under the page title; anything else is skipped.
REPORT_TYPE = "District 75"

# --------------------------------------------------------------------------
# Output columns from the D75 codebook. dbn / school_name are identifiers so
# rows can be told apart; drop them with --no-id.
# --------------------------------------------------------------------------
ID_COLUMNS = ["dbn", "school_name"]
CODEBOOK_COLUMNS = [
    "d75_sd_1ip", "d75_sd_1ssc", "d75_sd_1rf",
    "d75_sd_2w", "d75_sd_2p", "d75_sp_2g", "d75_sd_2e", "d75_sd_2l", "d75_sd_2n",
    "d75_sd_3as", "d75_sd_3bl", "d75_sd_3hs", "d75_sd_3na", "d75_sd_3pi",
    "d75_sd_3wh", "d75_sd_3ell", "d75_sd_3eni", "d75_sd_3f", "d75_sd_3m",
    "d75_sd_3nb",
    "d75_sd_4qvar", "d75_sd_4art", "d75_sd_4spt", "d75_sd_4ec", "d75_sd_4ps",
    "d75_sd_5as", "d75_sd_5bl", "d75_sd_5hs", "d75_sd_5na", "d75_sd_5pi",
    "d75_sd_5wh", "d75_sd_5py", "d75_sd_5t3",
    "d75_ip_1qp", "d75_ip_1qch",
    "d75_ip_2mv", "d75_ip_2int",
    "d75_ip_2sef", "d75_ip_2sep", "d75_ip_2sen",
    "d75_ip_2rsf", "d75_ip_2rsp", "d75_ip_2rsn",
    "d75_ip_2q1", "d75_ip_2q1a", "d75_ip_2q1b", "d75_ip_2q1h", "d75_ip_2q1n",
    "d75_ip_2q1p", "d75_ip_2q1w", "d75_ip_2q1e",
    "d75_ip_2q2", "d75_ip_2q2a", "d75_ip_2q2b", "d75_ip_2q2h", "d75_ip_2q2n",
    "d75_ip_2q2p", "d75_ip_2q2w", "d75_ip_2q2e",
    "d75_ip_2q3", "d75_ip_2q3a", "d75_ip_2q3b", "d75_ip_2q3h", "d75_ip_2q3n",
    "d75_ip_2q3p", "d75_ip_2q3w", "d75_ip_2q3e",
    "d75_ip_3lag", "d75_ip_3lap", "d75_ip_3seg", "d75_ip_3sep",
    "d75_ip_3smg", "d75_ip_3smp",
    "d75_ssc_1ac", "d75_ssc_1ta",
    "d75_ssc_2qp", "d75_ssc_2q1",
    "d75_ssc_3qp", "d75_ssc_3q1", "d75_ssc_3q2",
    "d75_ssc_4qp", "d75_ssc_4q1",
    "d75_rf_1qp", "d75_rf_1q1", "d75_rf_1q1a", "d75_rf_1q1b", "d75_rf_1q1h",
    "d75_rf_1q1n", "d75_rf_1q1p", "d75_rf_1q1w", "d75_rf_1q1e",
    "d75_rf_2qp", "d75_rf_2q1", "d75_rf_2q1a", "d75_rf_2q1b", "d75_rf_2q1h",
    "d75_rf_2q1n", "d75_rf_2q1p", "d75_rf_2q1w", "d75_rf_2q1e",
    "d75_rf_3qp", "d75_rf_3q1", "d75_rf_3q1a", "d75_rf_3q1b", "d75_rf_3q1h",
    "d75_rf_3q1n", "d75_rf_3q1p", "d75_rf_3q1w", "d75_rf_3q1e",
]

# Suffix letter -> subgroup key used by the chart parser.
# (a=Asian, b=Black, h=Hispanic, n=Native American, p=Pacific Islander,
#  w=White, e=ELL, i=IEP.)
SUBGROUP_SUFFIX = {
    "a": "asian", "b": "black", "h": "hispanic", "n": "native_american",
    "p": "pacific_islander", "w": "white", "e": "ell", "i": "iep",
}
SUFFIX_SETS = {
    "all8": "abhnpwei",   # race + ELL + IEP
    "race6": "abhnpw",    # race only
    "fam7": "abhnpwe",    # race + ELL (D75 codebook has no IEP columns)
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
# D75-specific helpers
# --------------------------------------------------------------------------
def first_section(scope, *headings):
    """section_after_heading for the first of several possible h4 headings."""
    for h in headings:
        sec = section_after_heading(scope, h)
        if sec is not None:
            return sec
    return None


def section_text(sec):
    """All text rows in a section, '; '-joined ('Boys: X; Girls: Y' style for label rows)."""
    if sec is None:
        return ""
    parts = []
    for div in sec.select("div.description"):
        lab = div.select_one("span.label")
        if lab is not None:
            parts.append(f"{clean(lab.get_text(' '))} {own_text(div)}".strip())
        else:
            parts.append(clean(div.get_text(" ")))
    return "; ".join(p for p in parts if p)


def overall_rating(link):
    """Overall School Ratings row: 'Good', 'Fair', ... or 'No Rating'."""
    if link is None:
        return ""
    word = rating_word(link)
    if word:
        return word
    no_rating = link.select_one(".no-rating-text")
    return clean(no_rating.get_text(" ")) if no_rating else ""


def rating_after_description(scope, fragment):
    """Rating (e.g. 'Fair') shown right after a description such as
    'Movement of students with special needs...'."""
    if scope is None:
        return ""
    for desc in scope.select("div.description"):
        if norm(fragment) in norm(desc.get_text(" ")):
            box = desc.find_next_sibling()
            if box is None:
                return ""
            word = rating_word(box)
            if word:
                return word
            return clean(box.get_text(" "))  # e.g. 'No Rating' / 'N/A'
    return ""


def assessment(scope, fragment):
    """(growth percentile, % participated) for a Performance on Assessments block."""
    if scope is None:
        return "", ""
    for block in scope.select("div.metric-bignum"):
        desc = block.select_one(".description")
        if desc and norm(fragment) in norm(desc.get_text(" ")):
            val = block.select_one(".school-value")
            m = re.search(r"([<>]?\d+(?:\.\d+)?%|N/A)\s+of students at this school participated",
                          clean(desc.get_text(" ")))
            return (clean(val.get_text(" ")) if val else ""), (m.group(1) if m else "")
    return "", ""


# --------------------------------------------------------------------------
# Main parser
# --------------------------------------------------------------------------
def parse_d75_page(html: str):
    """Return (row_dict, None) for a D75 page, or (None, reason) if skipped."""
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

    info = soup.select_one("#tab-content-info")
    ip = soup.select_one("#tab-content-ip")
    ss = soup.select_one("#tab-content-ss")
    rf = soup.select_one("#tab-content-rf")

    # ---------------- School Description ----------------
    # 1. Overall School Ratings (D75 schools currently show "No Rating")
    fr = info.select_one("div.framework-ratings") if info else None
    if fr:
        for href, col in (("#IP", "d75_sd_1ip"), ("#SS", "d75_sd_1ssc"), ("#RF", "d75_sd_1rf")):
            row[col] = overall_rating(fr.select_one(f'a[href="{href}"]'))

    # 2. Overview + Location
    ov = group(info, "gen")
    if ov is not None:
        for div in ov.select("div.metric-colon"):
            lab = norm(div.select_one("span.label").get_text(" ")) if div.select_one("span.label") else ""
            if lab == "school website":
                a = div.find("a")
                row["d75_sd_2w"] = clean(a.get_text()) if a else own_text(div)
        cv = colon_values(ov)
        row["d75_sd_2p"] = cv.get("principal", "")
        row["d75_sp_2g"] = cv.get("grades served", "")
        row["d75_sd_2e"] = cv.get("enrollment", "")
    loc = group(info, "location")
    if loc is not None:
        lines = [clean(d.get_text(" ")) for d in loc.select("div.address")]
        row["d75_sd_2l"] = ", ".join(l for l in lines if l)      # full address
        ph = loc.select_one("div.phone")
        row["d75_sd_2n"] = re.sub(r"^Phone:\s*", "", clean(ph.get_text())) if ph else ""

    # 3. Student Body -> Student Demographics (Surrounding Demographics skipped)
    cv = colon_values(section_after_heading(group(info, "sch-demog"), "Student Demographics"))
    row["d75_sd_3as"] = cv.get("asian", "")
    row["d75_sd_3bl"] = cv.get("black", "")
    row["d75_sd_3hs"] = cv.get("hispanic or latinx", "")
    row["d75_sd_3na"] = cv.get("native american", "")
    row["d75_sd_3pi"] = cv.get("native hawaiian pacific islander", "")
    row["d75_sd_3wh"] = cv.get("white", "")
    row["d75_sd_3ell"] = cv.get("english language learners", "")
    row["d75_sd_3eni"] = cv.get("economic need index", "")
    row["d75_sd_3f"] = cv.get("female", "")
    row["d75_sd_3m"] = cv.get("male", "")
    row["d75_sd_3nb"] = cv.get("neither female nor male", "")

    # 4. Programs (Classroom Settings skipped). Sports / extracurricular stay
    #    blank when a school's page doesn't have those sections.
    prog = group(info, "program")
    row["d75_sd_4qvar"] = survey_question(prog, "wide enough variety of programs").get("all", "")
    row["d75_sd_4art"] = section_text(first_section(prog, "Arts programs", "Arts Classes", "Arts"))
    row["d75_sd_4spt"] = section_text(first_section(prog, "PSAL Sports", "Sports"))
    row["d75_sd_4ec"] = section_text(first_section(prog, "Extracurricular Activities"))
    row["d75_sd_4ps"] = section_text(first_section(prog, "NYCPS Programs"))

    # 5. Staff/Faculty
    staff = group(info, "staff")
    cv = colon_values(section_after_heading(staff, "Teacher Demographics"))
    row["d75_sd_5as"] = cv.get("asian", "")
    row["d75_sd_5bl"] = cv.get("black", "")
    row["d75_sd_5hs"] = cv.get("hispanic or latinx", "")
    row["d75_sd_5na"] = cv.get("native american", "")
    row["d75_sd_5pi"] = cv.get("native hawaiian pacific islander", "")
    row["d75_sd_5wh"] = cv.get("white", "")
    cv = colon_values(section_after_heading(staff, "Staff Experience"))
    row["d75_sd_5py"] = cv.get("years of experience as principal at this school", "")
    row["d75_sd_5t3"] = cv.get("teachers with 3 or more years of experience", "")

    # ---------------- Instruction and Performance ----------------
    le = group(ip, "learning-env")
    row["d75_ip_1qp"] = bignum(le, "instruction/learning environment")
    row["d75_ip_1qch"] = survey_question(le, "respond to challenging questions").get("all", "")

    lre = group(ip, "lre")
    row["d75_ip_2mv"] = rating_after_description(lre, "Movement of students with special needs")
    row["d75_ip_2int"] = rating_after_description(lre, "Integration into General Education schools")

    swiep = group(ip, "swiep")
    se = value_list(swiep, "recommended special education programs")
    row["d75_ip_2sef"] = se.get("received in full", "")
    row["d75_ip_2sep"] = se.get("received in part", "")
    row["d75_ip_2sen"] = se.get("did not receive", "")
    rs = value_list(swiep, "recommended related services")
    row["d75_ip_2rsf"] = rs.get("received in full", "")
    row["d75_ip_2rsp"] = rs.get("received in part", "")
    row["d75_ip_2rsn"] = rs.get("did not receive", "")
    put_subgroups(row, "d75_ip_2q1", survey_question(swiep, "educational planning and IEP development process"),
                  SUFFIX_SETS["fam7"])
    put_subgroups(row, "d75_ip_2q2", survey_question(swiep, "receives what they need to achieve their Individualized Education Plan"),
                  SUFFIX_SETS["fam7"])
    put_subgroups(row, "d75_ip_2q3", survey_question(swiep, "wide enough variety of activities and services"),
                  SUFFIX_SETS["fam7"])

    perf = group(ip, "perf")
    row["d75_ip_3lag"], row["d75_ip_3lap"] = assessment(perf, "local assessments")
    row["d75_ip_3seg"], row["d75_ip_3sep"] = assessment(perf, "State Standard English")
    row["d75_ip_3smg"], row["d75_ip_3smp"] = assessment(perf, "State Standard Math")

    # ---------------- Safety and School Climate ----------------
    cv = colon_values(group(ss, "attendance"))
    row["d75_ssc_1ac"] = cv.get("average change in student attendance", "")
    row["d75_ssc_1ta"] = cv.get("teacher attendance", "")

    saf = group(ss, "safety")
    row["d75_ssc_2qp"] = bignum(saf, "survey questions about safety")
    row["d75_ssc_2q1"] = survey_question(saf, "students are safe in the hallways").get("all", "")

    lead = group(ss, "school-leadership")
    row["d75_ssc_3qp"] = bignum(lead, "survey questions about school leadership")
    row["d75_ssc_3q1"] = survey_question(lead, "sets high standards for student learning").get("all", "")
    row["d75_ssc_3q2"] = survey_question(lead, "encourages feedback through regular meetings").get("all", "")

    # Teaching Environment sits inside the school-leadership block on the page,
    # so search the whole Safety and School Climate tab for it.
    row["d75_ssc_4qp"] = bignum(ss, "survey questions about teaching environment")
    row["d75_ssc_4q1"] = survey_question(ss, "feel responsible that all students learn").get("all", "")

    # ---------------- Relationships with Families ----------------
    com = group(rf, "communication")
    row["d75_rf_1qp"] = bignum(com, "survey questions about communication")
    put_subgroups(row, "d75_rf_1q1", survey_question(com, "regularly communicates with them about how they can help"),
                  SUFFIX_SETS["fam7"])

    fam = group(rf, "family-involve")
    row["d75_rf_2qp"] = bignum(fam, "survey questions about family involvement")
    put_subgroups(row, "d75_rf_2q1", survey_question(fam, "communicated with their child's teacher about their child's performance"),
                  SUFFIX_SETS["fam7"])

    trust = group(rf, "relation-w-family")
    row["d75_rf_3qp"] = bignum(trust, "survey questions about family-school trust")
    put_subgroups(row, "d75_rf_3q1", survey_question(trust, "build trusting relationships with families"),
                  SUFFIX_SETS["fam7"])

    return row, None


# --------------------------------------------------------------------------------------------
# Live fetch (Playwright). The snapshot site is a JavaScript app, so the page must be rendered
# --------------------------------------------------------------------------------------------
def _short(e):
    return (str(e).strip().splitlines() or [repr(e)])[0][:200]


TAB_KEYS = ("info", "ip", "ss", "rf")


def _grab_all_tabs(page, timeout_ms):
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
    soup = BeautifulSoup(page.evaluate("document.body.outerHTML"), "lxml")
    for el in soup.select('[id^="tab-content-"]'):
        el.decompose()
    return str(soup) + "".join(tabs[k] for k in TAB_KEYS)


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
            row, reason = parse_d75_page(html)
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
    print(f"Wrote {len(rows)} D75 school row(s) to {output}", file=sys.stderr)
    return rows


def scrape_schools(limit=TRIAL_LIMIT, output=OUTPUT_CSV, include_id=True):
    schools = get_schools()
    print(f"{len(schools)} District 75 school(s) in {DEMOGRAPHICS_YEAR}", file=sys.stderr)
    if limit:
        schools = schools[:limit]
        print(f"TRIAL RUN: scraping only the first {len(schools)}", file=sys.stderr)
    jobs = [(dbn, [BASE_URL.format(year=SNAPSHOT_YEAR, dbn=dbn, type=t) for t in types])
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
    ap = argparse.ArgumentParser(description="Scrape NYC School Quality Snapshot D75 pages to CSV.")
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