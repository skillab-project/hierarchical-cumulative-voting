import time
import re
import math
from fastapi import FastAPI, Query
import pandas as pd
import networkx as nx
import json
from pathlib import Path
import requests as req
import os
from dotenv import load_dotenv
from typing import Optional, List
from fastapi import Query
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, asynccontextmanager


# === Load environment variables ===
load_dotenv()

API = os.getenv("TRACKER_API")
print(API)
USERNAME = os.getenv("TRACKER_USERNAME")
PASSWORD = os.getenv("TRACKER_PASSWORD")

# Number of parallel workers for page fetching — keeps the API happy without hammering it
FETCH_WORKERS = 10
# Page size used across all endpoints
PAGE_SIZE = 300

def _cleanup_stale_sentinels():
    """
    On startup, delete any files that still contain the in-progress sentinel.
    These are leftovers from a previous run that crashed mid-analysis and
    would otherwise permanently block retries for those filters.
    """
    folder = Path("Completed_Analyses")
    if not folder.exists():
        return
    cleaned = 0
    for f in folder.iterdir():
        if not f.is_file():
            continue
        try:
            contents = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(contents, dict) and contents.get("status") == "in_progress":
                f.unlink()
                print(f"🧹 Removed stale sentinel: {f.name}")
                cleaned += 1
        except Exception:
            pass  # ignore unreadable / non-JSON files
    if cleaned == 0:
        print("✅ No stale sentinel files found.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    _cleanup_stale_sentinels()
    yield

app = FastAPI(
    title="Skill Hierarchy & Concentration API",
    root_path="/hcv",
    lifespan=lifespan)

# Sentinel value written to a file when analysis starts.
# Any reader seeing this knows the analysis is still running.
ANALYSIS_IN_PROGRESS = {"status": "in_progress", "message": "Analysis is currently running for these filters. Please try again later."}

def get_token() -> str:
    res = req.post(f"{API}/login", json={"username": USERNAME, "password": PASSWORD})
    return res.text.replace('"', '')

def _parse_csv_str(v: Optional[str]) -> Optional[List[str]]:
    if not v:
        return None
    return [x.strip() for x in v.split(",") if x.strip()]

def _parse_csv_int(v: Optional[str]) -> Optional[List[int]]:
    if not v:
        return None
    return [int(x.strip()) for x in v.split(",") if x.strip()]


def fetch_all_pages(request_body: dict, endpoint: str) -> list:
    """
    Fetch all pages from a tracker endpoint in parallel.

    Authenticates once, probes page 1 for the total count, then dispatches
    remaining pages concurrently with a ThreadPoolExecutor.  Results are
    reassembled in page order so the caller gets a deterministic list.

    Returns a flat list of all 'items' across every page.
    """
    # --- Single login for the entire fetch ---
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}

    def fetch_page(p: int) -> dict:
        r = req.post(
            f"{API}/{endpoint}",
            headers=headers,
            params={"page": p, "page_size": PAGE_SIZE},
            data=request_body,
            timeout=1200,
        )
        return r.json() if r.status_code == 200 else {}

    # Probe page 1 to learn the total record count
    probe = fetch_page(1)
    total_count = probe.get("count", 0)
    if total_count == 0:
        return []

    items = list(probe.get("items", []))
    total_pages = math.ceil(total_count / PAGE_SIZE)

    print(f"📊 {endpoint}: {total_count} records across {total_pages} pages. Fetching in parallel…")

    if total_pages == 1:
        return items

    # Fetch pages 2..N in parallel
    page_results: dict = {}
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        future_to_page = {
            executor.submit(fetch_page, p): p for p in range(2, total_pages + 1)
        }
        completed = 0
        for future in as_completed(future_to_page):
            p = future_to_page[future]
            try:
                data = future.result()
                page_results[p] = data.get("items", [])
            except Exception as exc:
                print(f"⚠️  Page {p} failed: {exc}")
                page_results[p] = []
            completed += 1
            if completed % 50 == 0:
                print(f"📦 Progress: {completed}/{total_pages - 1} pages fetched.")

    # Reassemble in page order — keeps result list deterministic
    for p in range(2, total_pages + 1):
        items.extend(page_results.get(p, []))

    print(f"✅ Fetched {len(items)} records from /{endpoint}.")
    return items


def create_skills_list(items: list) -> list:
    """
    Extract the 'skills' field from a list of item dicts.
    Accepts the unwrapped items list (not the full API response envelope).
    """
    return [item.get("skills", []) for item in items]


def create_children_dictionary(column, skills_df):
    skills_by_level = defaultdict(dict)
    for _, row in skills_df.iterrows():
        skill_id = row['conceptUri']
        skill_levels = row[column]
        children = row['children']
        for level in skill_levels:
            skills_by_level[level][skill_id] = children
    return skills_by_level

def create_ancestors_dict(column, skills_df):
    ancestors_dict = {}
    for index, row in skills_df.iterrows():
        skill_id = row['conceptUri']
        ancestors = row[column]
        all_ancestors = []
        if ancestors:
            for ancestor_list in ancestors:
                for skill in ancestor_list:
                    all_ancestors.append(skill)
            final_ancestors = list(set(all_ancestors))
            ancestors_dict[skill_id] = final_ancestors
    return ancestors_dict

def find_unique_ids(children_dict):
    unique_skill_ids = set()
    for level, skills in children_dict.items():
        for skill_id, children in skills.items():
            unique_skill_ids.add(skill_id)
            unique_skill_ids.update(children)
    unique_skill_ids = list(unique_skill_ids)
    return unique_skill_ids

def compute_relative_frequencies(list_of_skills):
    frequency_dict = {}
    for skill_list in list_of_skills:
        for skill in skill_list:
            if skill in frequency_dict.keys():
                frequency_dict[skill] += 1
            else:
                frequency_dict[skill] = 1

    for key, value in frequency_dict.items():
        frequency_dict[key] = value / len(list_of_skills)

    return frequency_dict

def create_final_skill_list(list_of_skills, unique_skill_ids, ancestors_dict):
    new_skills_list = []
    for skill_list in list_of_skills:
        temp_list = []
        for skill in skill_list:
            if skill in unique_skill_ids:
                for ancestor in ancestors_dict[skill]:
                    temp_list.append(ancestor)
                temp_list.append(skill)
        new_skills_list.append(temp_list)

    filtered_skills = [skill_list for skill_list in new_skills_list if skill_list]

    final_skills_list = []
    for skill_list in filtered_skills:
        new_list = set(skill_list)
        new_list = [item for item in new_list]
        final_skills_list.append(new_list)

    return final_skills_list

def filter_skills_hierarchy(children_dict, valid_skill_ids):
    filtered_skills_hierarchy = {}
    for level, ancestors in children_dict.items():
        filtered_level = {}
        for ancestor, children in ancestors.items():
            if ancestor in valid_skill_ids or any(child in valid_skill_ids for child in children):
                filtered_children = [child for child in children if child in valid_skill_ids]
                if ancestor in valid_skill_ids or filtered_children:
                    filtered_level[ancestor] = filtered_children
        filtered_skills_hierarchy[level] = filtered_level
    return filtered_skills_hierarchy

def compute_hhi(level_dict):
    return sum((p * 100) ** 2 for p in level_dict.values())

def classify(hhi):
    return "competitive" if hhi < 2500 else "monopolized"

def load_esco() -> tuple[pd.DataFrame, dict]:
    """
    Load and parse the ESCO Excel mapping file.
    Returns (skills_df, skill_labels_dict).
    Called once per request rather than once per endpoint handler.
    """
    skills_df = pd.read_excel('new_ESCO_mapping.xlsx')
    for col in ['skills_levels', 'knowledge_levels', 'traversal_levels',
                'skills_ancestors', 'knowledge_ancestors', 'traversal_ancestors', 'children']:
        skills_df[col] = skills_df[col].apply(eval)

    skill_labels_dict = {
        row['conceptUri']: row['preferredLabel']
        for _, row in skills_df.iterrows()
    }
    return skills_df, skill_labels_dict


def run_hcv(pillar: str, skills_list: list) -> list:
    """
    Runs the full Hierarchical Cumulative Voting algorithm for given pillar and skills_list.
    Returns JSON-ready HCV list.
    """
    skills_df, skill_labels_dict = load_esco()

    levels_column = f"{pillar}_levels"
    ancestors_column = f"{pillar}_ancestors"

    pillar_children = dict(create_children_dictionary(levels_column, skills_df))
    pillar_ancestors = create_ancestors_dict(ancestors_column, skills_df)

    print('Applying HCV...')
    unique_ids = find_unique_ids(pillar_children)
    final_skills_list = create_final_skill_list(skills_list, unique_ids, pillar_ancestors)

    frequency_dict = compute_relative_frequencies(final_skills_list)
    valid_skill_ids = list(set(frequency_dict.keys()))
    filtered = filter_skills_hierarchy(pillar_children, valid_skill_ids)

    ancestors_dict = {}
    HCV_df = pd.DataFrame(columns=[
        'skill', 'level', 'ancestor', 'relative frequency', 'ancestor frequency',
        'compensation factor', 'intermediate priority', 'normalized priority'
    ])

    for level in range(len(filtered)):
        if level == 0:
            intermediate = []
            for skill in filtered[level]:
                c = len(filtered[level][skill])
                for child in filtered[level][skill]:
                    p = frequency_dict[child] * frequency_dict[skill]
                    intermediate.append(p)
                for child in filtered[level][skill]:
                    p = frequency_dict[child] * frequency_dict[skill]
                    norm = p / sum(intermediate)
                    ancestors_dict[child] = norm
                    HCV_df.loc[len(HCV_df)] = [
                        skill_labels_dict[child], level + 1, skill_labels_dict[skill],
                        frequency_dict[child], 1, c, p, norm
                    ]
        else:
            intermediate = []
            for skill in filtered[level]:
                c = len(filtered[level][skill])
                for child in filtered[level][skill]:
                    p = frequency_dict[child] * ancestors_dict[skill] * c
                    intermediate.append(p)
            for skill in filtered[level]:
                c = len(filtered[level][skill])
                for child in filtered[level][skill]:
                    p = frequency_dict[child] * ancestors_dict[skill] * c
                    norm = p / sum(intermediate)
                    ancestors_dict[child] = norm
                    HCV_df.loc[len(HCV_df)] = [
                        skill_labels_dict[child], level + 1, skill_labels_dict[skill],
                        frequency_dict[child], ancestors_dict[skill], c, p, norm
                    ]

    HCV_df['rank'] = HCV_df.groupby('level')['normalized priority'].rank(method='dense', ascending=False)

    return json.loads(HCV_df.to_json(orient='records'))

def create_skills_df(skills_list, selected_skills):
    """
    Creates a binary (yes/no) DataFrame based on a specific list of skills.
    """
    data = []
    for i, skills in enumerate(skills_list):
        row = ['yes' if skill in skills else 'no' for skill in selected_skills]
        data.append([i] + row)
    df = pd.DataFrame(data, columns=['list_index'] + selected_skills)
    return df


def perform_turf_analysis_subset(df, n_skills, skill_labels_dict, combinations):
    n_combination = combinations
    turf_results = []
    from itertools import combinations

    skill_columns = df.columns

    valid_skill_columns = [col for col in skill_columns if df[col].isin(['yes', 'no']).all()]

    if n_skills > len(valid_skill_columns):
        raise ValueError(
            f"n_skills ({n_skills}) cannot exceed the number of valid skill columns ({len(valid_skill_columns)}).")

    if n_combination < 1 or n_combination > n_skills:
        raise ValueError(f"n_combination ({n_combination}) must be between 1 and n_skills ({n_skills}).")

    if df.empty:
        raise ValueError("Input DataFrame is empty or does not contain valid skill columns.")

    skill_columns = valid_skill_columns[:n_skills]
    print(f"\nAnalyzing combinations of these skills: {', '.join(skill_columns)}")

    all_no_rows = df[skill_columns].eq('no').all(axis=1)
    if all_no_rows.any():
        print(f"\nRemoving {all_no_rows.sum()} row(s) where all skills are 'no':")
        if 'id' in df.columns and 'url' in df.columns:
            print(df.loc[all_no_rows, ['id', 'url']])
        else:
            print("The columns 'id' and/or 'url' are not present in the DataFrame.")
        df = df[~all_no_rows]

    skill_combinations = list(combinations(skill_columns, n_combination))

    total_cases = len(df)

    for combo in skill_combinations:
        reach_mask = df[list(combo)].eq('yes').any(axis=1)
        reach = reach_mask.sum()
        reach_percentage = (reach / total_cases) * 100

        jobs_with_skills = df[reach_mask]
        if len(jobs_with_skills) > 0:
            yes_count = jobs_with_skills[list(combo)].eq('yes').sum().sum()
            frequency_count = yes_count
            frequency = yes_count / reach if reach > 0 else 0
        else:
            frequency_count = 0
            frequency = 0

        combo_list = list(combo)
        combination_string = combo_list[0]
        for i in range(1, len(combo_list)):
            combination_string += '+' + combo_list[i]

        turf_results.append({
            'Combination': combination_string,
            'Reach': reach,
            'Reach %': round(reach_percentage, 2),
            'Frequency': frequency_count,
            'Frequency Ratio': round(frequency, 2),
            'Combination Number': n_combination
        })

    results_df = pd.DataFrame(turf_results)
    results_df = results_df.sort_values(['Reach', 'Frequency'], ascending=[False, False])
    TURF_JSON = results_df.to_json(orient='records')
    TURF_JSON = json.loads(TURF_JSON)

    return TURF_JSON


def _ensure_folder(folder: Path):
    """Create the output folder if it doesn't exist."""
    if not folder.exists():
        folder.mkdir(parents=True)
        print(f"Folder '{folder}' created.")
    else:
        print(f"Folder '{folder}' already exists, moving on.")


def _check_file(file_path: str):
    """
    Check whether a cached result file exists.

    Returns a tuple (should_return_early: bool, response).
    - If the file doesn't exist              → (False, None)       — proceed with analysis
    - If the file contains the in-progress   → (True,  ANALYSIS_IN_PROGRESS sentinel)
      sentinel, another request is already
      running for these filters
    - If the file contains a completed       → (True,  <cached result>) — return cached result
      result
    """
    if not os.path.exists(file_path):
        return False, None

    with open(file_path, "r", encoding="utf-8") as f:
        contents = json.loads(f.read())

    if isinstance(contents, dict) and contents.get("status") == "in_progress":
        print("Analysis already in progress for this file.")
        return True, ANALYSIS_IN_PROGRESS

    print("File with completed result exists, returning cached result.")
    return True, contents


def _reserve_file(file_path: str):
    """
    Write the in-progress sentinel to the file immediately so that any
    concurrent request for the same filters knows an analysis is running.
    """
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(ANALYSIS_IN_PROGRESS, f, indent=4, ensure_ascii=False)
    print(f"Reserved file '{file_path}' with in-progress sentinel.")


def _save_result(file_path: str, result):
    """Overwrite the sentinel with the finished result."""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=4, ensure_ascii=False)
    print("JSON saved successfully!")


@contextmanager
def _analysis_file(file_path: str):
    """
    Context manager that guarantees the reserved sentinel file is removed
    if any exception is raised during analysis.

    Usage:
        _reserve_file(file_path)
        with _analysis_file(file_path):
            ... run analysis ...
            _save_result(file_path, result)

    On success  → file already contains the finished result (written by _save_result).
    On exception → sentinel file is deleted so the next request can retry,
                   then the exception is re-raised so FastAPI returns a 500.
    """
    try:
        yield
    except Exception as exc:
        print(f"❌ Analysis failed for '{file_path}': {exc}. Deleting sentinel file so the next request can retry.")
        try:
            os.remove(file_path)
            print(f"🗑️  Deleted sentinel file '{file_path}'.")
        except OSError as remove_err:
            print(f"⚠️  Could not delete sentinel file '{file_path}': {remove_err}")
        raise


@app.get("/HierarchicalCumulativeVoting/jobs")
def hcv_jobs(
        pillar: str,
        keywords: Optional[str] = Query(None, description="Comma-separated keywords"),
        keywords_logic: Optional[str] = Query(None, description="Logic for keywords (e.g. AND, OR)"),
        ids: Optional[str] = Query(None, description="Comma-separated job IDs (integers)"),
        skill_ids: Optional[str] = Query(None, description="Comma-separated skill IDs"),
        skill_ids_logic: Optional[str] = Query(None, description="Logic for skill IDs (e.g. AND, OR)"),
        occupation_ids: Optional[str] = Query(None, description="Comma-separated occupation IDs"),
        occupation_ids_logic: Optional[str] = Query(None, description="Logic for occupation IDs (e.g. AND, OR)"),
        organization_ids: Optional[str] = Query(None, description="Comma-separated organization IDs (integers)"),
        min_upload_date: Optional[str] = Query(None, description="Min upload date (YYYY-MM-DD)"),
        max_upload_date: Optional[str] = Query(None, description="Max upload date (YYYY-MM-DD)"),
        location_code: Optional[str] = Query(None, description="Comma-separated location codes"),
        sources: Optional[str] = Query(None, description="Comma-separated sources"),
):
    folder = Path("Completed_Analyses")
    _ensure_folder(folder)

    request_body: dict = {}

    kws = _parse_csv_str(keywords)
    if kws:
        request_body["keywords"] = kws
    if keywords_logic:
        request_body["keywords_logic"] = keywords_logic

    job_ids = _parse_csv_int(ids)
    if job_ids:
        request_body["ids"] = job_ids

    s_ids = _parse_csv_str(skill_ids)
    if s_ids:
        request_body["skill_ids"] = s_ids
    if skill_ids_logic:
        request_body["skill_ids_logic"] = skill_ids_logic

    occ_ids = _parse_csv_str(occupation_ids)
    if occ_ids:
        request_body["occupation_ids"] = occ_ids
    if occupation_ids_logic:
        request_body["occupation_ids_logic"] = occupation_ids_logic

    org_ids = _parse_csv_int(organization_ids)
    if org_ids:
        request_body["organization_ids"] = org_ids

    if min_upload_date:
        request_body["min_upload_date"] = min_upload_date
    if max_upload_date:
        request_body["max_upload_date"] = max_upload_date

    locs = _parse_csv_str(location_code)
    if locs:
        request_body["location_code"] = locs

    srcs = _parse_csv_str(sources)
    if srcs:
        request_body["sources"] = srcs

    filename = "completed_analysis_hcv_jobs_{}".format(pillar)
    for key in request_body:
        if request_body[key]:
            for value in request_body[key]:
                if key == 'occupation_ids':
                    match = re.search(r'C\d+$', value)
                    reg_occupation = match.group(0)
                    filename = filename + "_" + reg_occupation
                else:
                    filename = filename + "_" + value

    file_path = os.path.join(folder, filename)

    should_return, cached = _check_file(file_path)
    if should_return:
        return cached

    _reserve_file(file_path)

    print("Request body sent to /jobs:", request_body)
    with _analysis_file(file_path):
        items = fetch_all_pages(request_body, endpoint='jobs')
        if not items:
            _save_result(file_path, [])
            return []

        print(f"Number of jobs: {len(items)}")
        skills_list = create_skills_list(items)

        HCV_JSON = run_hcv(pillar, skills_list)
        _save_result(file_path, HCV_JSON)
    return HCV_JSON


@app.get("/HierarchicalCumulativeVoting/policies")
def hcv_policies(
        pillar: str,
        keywords: Optional[str] = Query(None, description="Comma-separated keywords"),
        keywords_logic: Optional[str] = Query(None, description="Logic for keywords (e.g. AND, OR)"),
        ids: Optional[str] = Query(None, description="Comma-separated law policy IDs (integers)"),
        skill_ids: Optional[str] = Query(None, description="Comma-separated skill IDs"),
        skill_ids_logic: Optional[str] = Query(None, description="Logic for skill IDs (e.g. AND, OR)"),
        min_publication_date: Optional[str] = Query(None, description="Min publication date (YYYY-MM-DD)"),
        max_publication_date: Optional[str] = Query(None, description="Max publication date (YYYY-MM-DD)"),
        min_page_count: Optional[int] = Query(None, description="Minimum page count (>= this value)"),
        max_page_count: Optional[int] = Query(None, description="Maximum page count (<= this value)"),
        type_: Optional[str] = Query(None, alias="type", description="Law policy type"),
        sources: Optional[str] = Query(None, description="Comma-separated sources"),
):
    folder = Path("Completed_Analyses")
    _ensure_folder(folder)

    request_body: dict = {}

    kws = _parse_csv_str(keywords)
    if kws:
        request_body["keywords"] = kws
    if keywords_logic:
        request_body["keywords_logic"] = keywords_logic

    policy_ids = _parse_csv_int(ids)
    if policy_ids:
        request_body["ids"] = policy_ids

    s_ids = _parse_csv_str(skill_ids)
    if s_ids:
        request_body["skill_ids"] = s_ids
    if skill_ids_logic:
        request_body["skill_ids_logic"] = skill_ids_logic

    if min_publication_date:
        request_body["min_publication_date"] = min_publication_date
    if max_publication_date:
        request_body["max_publication_date"] = max_publication_date

    if min_page_count is not None:
        request_body["min_page_count"] = min_page_count
    if max_page_count is not None:
        request_body["max_page_count"] = max_page_count

    if type_:
        request_body["type"] = type_

    srcs = _parse_csv_str(sources)
    if srcs:
        request_body["sources"] = srcs

    filename = "completed_analysis_hcv_policies_{}".format(pillar)
    for key in request_body:
        if request_body[key]:
            for value in request_body[key]:
                if key == 'occupation_ids':
                    match = re.search(r'C\d+$', value)
                    reg_occupation = match.group(0)
                    filename = filename + "_" + reg_occupation
                else:
                    filename = filename + "_" + value

    file_path = os.path.join(folder, filename)

    should_return, cached = _check_file(file_path)
    if should_return:
        return cached

    _reserve_file(file_path)

    print("Request body sent to /policies:", request_body)
    with _analysis_file(file_path):
        items = fetch_all_pages(request_body, endpoint='law-policies')
        if not items:
            _save_result(file_path, [])
            return []

        print(f"Number of policies: {len(items)}")
        skills_list = create_skills_list(items)

        HCV_JSON = run_hcv(pillar, skills_list)
        _save_result(file_path, HCV_JSON)
    return HCV_JSON


@app.get("/HierarchicalCumulativeVoting/profiles")
def hcv_profiles(
        pillar: str,
        occupation: Optional[str] = Query(None, description="Occupation ID"),
        keywords: Optional[str] = Query(None, description="Comma-separated keywords"),
        keywords_logic: Optional[str] = Query(None, description="Logic for keywords (e.g. AND, OR)"),
        ids: Optional[str] = Query(None, description="Comma-separated profile IDs (integers)"),
        skill_ids: Optional[str] = Query(None, description="Comma-separated skill IDs"),
        skill_ids_logic: Optional[str] = Query(None, description="Logic for skill IDs (e.g. AND, OR)"),
        sources: Optional[str] = Query(None, description="Comma-separated sources"),
):
    folder = Path("Completed_Analyses")
    _ensure_folder(folder)

    request_body: dict = {}

    kws = _parse_csv_str(keywords)
    if kws:
        request_body["keywords"] = kws
    if keywords_logic:
        request_body["keywords_logic"] = keywords_logic

    profile_ids = _parse_csv_int(ids)
    if profile_ids:
        request_body["ids"] = profile_ids

    s_ids = _parse_csv_str(skill_ids)
    if s_ids:
        request_body["skill_ids"] = s_ids
    if skill_ids_logic:
        request_body["skill_ids_logic"] = skill_ids_logic

    srcs = _parse_csv_str(sources)
    if srcs:
        request_body["sources"] = srcs

    filename = "completed_analysis_hcv_profiles_{}".format(pillar)
    for key in request_body:
        if request_body[key]:
            for value in request_body[key]:
                if key == 'occupation_ids':
                    match = re.search(r'C\d+$', value)
                    reg_occupation = match.group(0)
                    filename = filename + "_" + reg_occupation
                else:
                    filename = filename + "_" + value

    file_path = os.path.join(folder, filename)

    should_return, cached = _check_file(file_path)
    if should_return:
        return cached

    _reserve_file(file_path)

    print("Request body sent to /profiles:", request_body)
    with _analysis_file(file_path):
        items = fetch_all_pages(request_body, endpoint='profiles')
        if not items:
            _save_result(file_path, [])
            return []

        print(f"Number of profiles: {len(items)}")
        skills_list = create_skills_list(items)

        HCV_JSON = run_hcv(pillar, skills_list)
        _save_result(file_path, HCV_JSON)
    return HCV_JSON


@app.get("/HierarchicalCumulativeVoting/courses")
def hcv_courses(
        pillar: str,
        occupation: Optional[str] = Query(None, description="Occupation ID"),
        keywords: Optional[str] = Query(None, description="Comma-separated keywords"),
        keywords_logic: Optional[str] = Query(None, description="Logic for keywords (e.g. AND, OR)"),
        ids: Optional[str] = Query(None, description="Comma-separated course IDs (integers)"),
        skill_ids: Optional[str] = Query(None, description="Comma-separated skill IDs"),
        skill_ids_logic: Optional[str] = Query(None, description="Logic for skill IDs (e.g. AND, OR)"),
        min_creation_date: Optional[str] = Query(None, description="Min creation date (YYYY-MM-DD)"),
        max_creation_date: Optional[str] = Query(None, description="Max creation date (YYYY-MM-DD)"),
        min_rating: Optional[float] = Query(None, description="Min rating (>= this value)"),
        max_rating: Optional[float] = Query(None, description="Max rating (<= this value)"),
        min_price: Optional[float] = Query(None, description="Min price (>= this value)"),
        max_price: Optional[float] = Query(None, description="Max price (<= this value)"),
        sources: Optional[str] = Query(None, description="Comma-separated sources"),
):
    folder = Path("Completed_Analyses")
    _ensure_folder(folder)

    request_body: dict = {}

    kws = _parse_csv_str(keywords)
    if kws:
        request_body["keywords"] = kws
    if keywords_logic:
        request_body["keywords_logic"] = keywords_logic

    course_ids = _parse_csv_int(ids)
    if course_ids:
        request_body["ids"] = course_ids

    s_ids = _parse_csv_str(skill_ids)
    if s_ids:
        request_body["skill_ids"] = s_ids
    if skill_ids_logic:
        request_body["skill_ids_logic"] = skill_ids_logic

    if min_creation_date:
        request_body["min_creation_date"] = min_creation_date
    if max_creation_date:
        request_body["max_creation_date"] = max_creation_date

    if min_rating is not None:
        request_body["min_rating"] = min_rating
    if max_rating is not None:
        request_body["max_rating"] = max_rating

    if min_price is not None:
        request_body["min_price"] = min_price
    if max_price is not None:
        request_body["max_price"] = max_price

    srcs = _parse_csv_str(sources)
    if srcs:
        request_body["sources"] = srcs

    filename = "completed_analysis_hcv_courses_{}".format(pillar)
    for key in request_body:
        if request_body[key]:
            for value in request_body[key]:
                if key == 'occupation_ids':
                    match = re.search(r'C\d+$', value)
                    reg_occupation = match.group(0)
                    filename = filename + "_" + reg_occupation
                else:
                    filename = filename + "_" + value

    file_path = os.path.join(folder, filename)

    should_return, cached = _check_file(file_path)
    if should_return:
        return cached

    _reserve_file(file_path)

    print("Request body sent to /courses:", request_body)
    with _analysis_file(file_path):
        items = fetch_all_pages(request_body, endpoint='courses')
        if not items:
            _save_result(file_path, [])
            return []

        print(f"Number of courses: {len(items)}")
        skills_list = create_skills_list(items)

        HCV_JSON = run_hcv(pillar, skills_list)
        _save_result(file_path, HCV_JSON)
    return HCV_JSON


@app.get("/TurfAnalysis/jobs")
def turf_jobs(
        pillar: str,
        combinations: int,
        keywords: Optional[str] = Query(None, description="Comma-separated keywords"),
        keywords_logic: Optional[str] = Query(None, description="Logic for keywords (e.g. AND, OR)"),
        ids: Optional[str] = Query(None, description="Comma-separated job IDs (integers)"),
        skill_ids: Optional[str] = Query(None, description="Comma-separated skill IDs"),
        skill_ids_logic: Optional[str] = Query(None, description="Logic for skill IDs (e.g. AND, OR)"),
        occupation_ids: Optional[str] = Query(None, description="Comma-separated occupation IDs"),
        occupation_ids_logic: Optional[str] = Query(None, description="Logic for occupation IDs (e.g. AND, OR)"),
        organization_ids: Optional[str] = Query(None, description="Comma-separated organization IDs (integers)"),
        min_upload_date: Optional[str] = Query(None, description="Min upload date (YYYY-MM-DD)"),
        max_upload_date: Optional[str] = Query(None, description="Max upload date (YYYY-MM-DD)"),
        location_code: Optional[str] = Query(None, description="Comma-separated location codes"),
        sources: Optional[str] = Query(None, description="Comma-separated sources"),
):
    folder = Path("Completed_Analyses")
    _ensure_folder(folder)

    request_body: dict = {}

    kws = _parse_csv_str(keywords)
    if kws:
        request_body["keywords"] = kws
    if keywords_logic:
        request_body["keywords_logic"] = keywords_logic

    job_ids = _parse_csv_int(ids)
    if job_ids:
        request_body["ids"] = job_ids

    s_ids = _parse_csv_str(skill_ids)
    if s_ids:
        request_body["skill_ids"] = s_ids
    if skill_ids_logic:
        request_body["skill_ids_logic"] = skill_ids_logic

    occ_ids = _parse_csv_str(occupation_ids)
    if occ_ids:
        request_body["occupation_ids"] = occ_ids
    if occupation_ids_logic:
        request_body["occupation_ids_logic"] = occupation_ids_logic

    org_ids = _parse_csv_int(organization_ids)
    if org_ids:
        request_body["organization_ids"] = org_ids

    if min_upload_date:
        request_body["min_upload_date"] = min_upload_date
    if max_upload_date:
        request_body["max_upload_date"] = max_upload_date

    locs = _parse_csv_str(location_code)
    if locs:
        request_body["location_code"] = locs

    srcs = _parse_csv_str(sources)
    if srcs:
        request_body["sources"] = srcs

    filename = "completed_analysis_turf_jobs_{}_{}".format(pillar, combinations)
    for key in request_body:
        if request_body[key]:
            for value in request_body[key]:
                if key == 'occupation_ids':
                    match = re.search(r'C\d+$', value)
                    reg_occupation = match.group(0)
                    filename = filename + "_" + reg_occupation
                else:
                    filename = filename + "_" + value

    file_path = os.path.join(folder, filename)

    should_return, cached = _check_file(file_path)
    if should_return:
        return cached

    _reserve_file(file_path)

    print("Request body sent to /jobs:", request_body)
    with _analysis_file(file_path):
        _, skill_labels_dict = load_esco()

        items = fetch_all_pages(request_body, endpoint='jobs')
        if not items:
            _save_result(file_path, [])
            return []

        print(f"Number of jobs: {len(items)}")
        skills_list = create_skills_list(items)

        all_skills_flat = [skill for sublist in skills_list for skill in sublist]
        skill_counts = Counter(all_skills_flat)
        top_20_tuples = skill_counts.most_common(20)
        top_20_skills = [item[0] for item in top_20_tuples]
        print(f"Top 20 frequent skills selected: {top_20_skills}")

        skills_df = create_skills_df(skills_list, top_20_skills)
        TURF_JSON = perform_turf_analysis_subset(skills_df, len(top_20_skills), skill_labels_dict, combinations)

        _save_result(file_path, TURF_JSON)
    return TURF_JSON


@app.get("/TurfAnalysis/policies")
def turf_policies(
        pillar: str,
        combinations: int,
        occupation: Optional[str] = Query(None, description="Occupation ID"),
        keywords: Optional[str] = Query(None, description="Comma-separated keywords"),
        keywords_logic: Optional[str] = Query(None, description="Logic for keywords (e.g. AND, OR)"),
        ids: Optional[str] = Query(None, description="Comma-separated law policy IDs (integers)"),
        skill_ids: Optional[str] = Query(None, description="Comma-separated skill IDs"),
        skill_ids_logic: Optional[str] = Query(None, description="Logic for skill IDs (e.g. AND, OR)"),
        min_publication_date: Optional[str] = Query(None, description="Min publication date (YYYY-MM-DD)"),
        max_publication_date: Optional[str] = Query(None, description="Max publication date (YYYY-MM-DD)"),
        min_page_count: Optional[int] = Query(None, description="Minimum page count (>= this value)"),
        max_page_count: Optional[int] = Query(None, description="Maximum page count (<= this value)"),
        type_: Optional[str] = Query(None, alias="type", description="Law policy type"),
        sources: Optional[str] = Query(None, description="Comma-separated sources"),
):
    folder = Path("Completed_Analyses")
    _ensure_folder(folder)

    request_body: dict = {}

    kws = _parse_csv_str(keywords)
    if kws:
        request_body["keywords"] = kws
    if keywords_logic:
        request_body["keywords_logic"] = keywords_logic

    policy_ids = _parse_csv_int(ids)
    if policy_ids:
        request_body["ids"] = policy_ids

    s_ids = _parse_csv_str(skill_ids)
    if s_ids:
        request_body["skill_ids"] = s_ids
    if skill_ids_logic:
        request_body["skill_ids_logic"] = skill_ids_logic

    if min_publication_date:
        request_body["min_publication_date"] = min_publication_date
    if max_publication_date:
        request_body["max_publication_date"] = max_publication_date

    if min_page_count is not None:
        request_body["min_page_count"] = min_page_count
    if max_page_count is not None:
        request_body["max_page_count"] = max_page_count

    if type_:
        request_body["type"] = type_

    srcs = _parse_csv_str(sources)
    if srcs:
        request_body["sources"] = srcs

    filename = "completed_analysis_turf_policies_{}_{}".format(pillar, combinations)
    for key in request_body:
        if request_body[key]:
            for value in request_body[key]:
                if key == 'occupation_ids':
                    match = re.search(r'C\d+$', value)
                    reg_occupation = match.group(0)
                    filename = filename + "_" + reg_occupation
                else:
                    filename = filename + "_" + value

    file_path = os.path.join(folder, filename)

    should_return, cached = _check_file(file_path)
    if should_return:
        return cached

    _reserve_file(file_path)

    print("Request body sent to /policies:", request_body)
    with _analysis_file(file_path):
        _, skill_labels_dict = load_esco()

        items = fetch_all_pages(request_body, endpoint='law-policies')
        if not items:
            _save_result(file_path, [])
            return []

        print(f"Number of policies: {len(items)}")
        skills_list = create_skills_list(items)

        all_skills_flat = [skill for sublist in skills_list for skill in sublist]
        skill_counts = Counter(all_skills_flat)
        top_20_tuples = skill_counts.most_common(20)
        top_20_skills = [item[0] for item in top_20_tuples]
        print(f"Top 20 frequent skills selected: {top_20_skills}")

        skills_df = create_skills_df(skills_list, top_20_skills)
        TURF_JSON = perform_turf_analysis_subset(skills_df, len(top_20_skills), skill_labels_dict, combinations)

        _save_result(file_path, TURF_JSON)
    return TURF_JSON


@app.get("/TurfAnalysis/profiles")
def turf_profiles(
        pillar: str,
        combinations: int,
        occupation: Optional[str] = Query(None, description="Occupation ID"),
        keywords: Optional[str] = Query(None, description="Comma-separated keywords"),
        keywords_logic: Optional[str] = Query(None, description="Logic for keywords (e.g. AND, OR)"),
        ids: Optional[str] = Query(None, description="Comma-separated profile IDs (integers)"),
        skill_ids: Optional[str] = Query(None, description="Comma-separated skill IDs"),
        skill_ids_logic: Optional[str] = Query(None, description="Logic for skill IDs (e.g. AND, OR)"),
        sources: Optional[str] = Query(None, description="Comma-separated sources"),
):
    folder = Path("Completed_Analyses")
    _ensure_folder(folder)

    request_body: dict = {}

    kws = _parse_csv_str(keywords)
    if kws:
        request_body["keywords"] = kws
    if keywords_logic:
        request_body["keywords_logic"] = keywords_logic

    profile_ids = _parse_csv_int(ids)
    if profile_ids:
        request_body["ids"] = profile_ids

    s_ids = _parse_csv_str(skill_ids)
    if s_ids:
        request_body["skill_ids"] = s_ids
    if skill_ids_logic:
        request_body["skill_ids_logic"] = skill_ids_logic

    srcs = _parse_csv_str(sources)
    if srcs:
        request_body["sources"] = srcs

    filename = "completed_analysis_turf_profiles_{}_{}".format(pillar, combinations)
    for key in request_body:
        if request_body[key]:
            for value in request_body[key]:
                if key == 'occupation_ids':
                    match = re.search(r'C\d+$', value)
                    reg_occupation = match.group(0)
                    filename = filename + "_" + reg_occupation
                else:
                    filename = filename + "_" + value

    file_path = os.path.join(folder, filename)

    should_return, cached = _check_file(file_path)
    if should_return:
        return cached

    _reserve_file(file_path)

    print("Request body sent to /profiles:", request_body)
    with _analysis_file(file_path):
        _, skill_labels_dict = load_esco()

        items = fetch_all_pages(request_body, endpoint='profiles')
        if not items:
            _save_result(file_path, [])
            return []

        print(f"Number of profiles: {len(items)}")
        skills_list = create_skills_list(items)

        all_skills_flat = [skill for sublist in skills_list for skill in sublist]
        skill_counts = Counter(all_skills_flat)
        top_20_tuples = skill_counts.most_common(20)
        top_20_skills = [item[0] for item in top_20_tuples]
        print(f"Top 20 frequent skills selected: {top_20_skills}")

        skills_df = create_skills_df(skills_list, top_20_skills)
        TURF_JSON = perform_turf_analysis_subset(skills_df, len(top_20_skills), skill_labels_dict, combinations)

        _save_result(file_path, TURF_JSON)
    return TURF_JSON


@app.get("/TurfAnalysis/courses")
def turf_courses(
        pillar: str,
        combinations: int,
        occupation: Optional[str] = Query(None, description="Occupation ID"),
        keywords: Optional[str] = Query(None, description="Comma-separated keywords"),
        keywords_logic: Optional[str] = Query(None, description="Logic for keywords (e.g. AND, OR)"),
        ids: Optional[str] = Query(None, description="Comma-separated course IDs (integers)"),
        skill_ids: Optional[str] = Query(None, description="Comma-separated skill IDs"),
        skill_ids_logic: Optional[str] = Query(None, description="Logic for skill IDs (e.g. AND, OR)"),
        min_creation_date: Optional[str] = Query(None, description="Min creation date (YYYY-MM-DD)"),
        max_creation_date: Optional[str] = Query(None, description="Max creation date (YYYY-MM-DD)"),
        min_rating: Optional[float] = Query(None, description="Min rating (>= this value)"),
        max_rating: Optional[float] = Query(None, description="Max rating (<= this value)"),
        min_price: Optional[float] = Query(None, description="Min price (>= this value)"),
        max_price: Optional[float] = Query(None, description="Max price (<= this value)"),
        sources: Optional[str] = Query(None, description="Comma-separated sources"),
):
    folder = Path("Completed_Analyses")
    _ensure_folder(folder)

    request_body: dict = {}

    kws = _parse_csv_str(keywords)
    if kws:
        request_body["keywords"] = kws
    if keywords_logic:
        request_body["keywords_logic"] = keywords_logic

    course_ids = _parse_csv_int(ids)
    if course_ids:
        request_body["ids"] = course_ids

    s_ids = _parse_csv_str(skill_ids)
    if s_ids:
        request_body["skill_ids"] = s_ids
    if skill_ids_logic:
        request_body["skill_ids_logic"] = skill_ids_logic

    if min_creation_date:
        request_body["min_creation_date"] = min_creation_date
    if max_creation_date:
        request_body["max_creation_date"] = max_creation_date

    if min_rating is not None:
        request_body["min_rating"] = min_rating
    if max_rating is not None:
        request_body["max_rating"] = max_rating

    if min_price is not None:
        request_body["min_price"] = min_price
    if max_price is not None:
        request_body["max_price"] = max_price

    srcs = _parse_csv_str(sources)
    if srcs:
        request_body["sources"] = srcs

    filename = "completed_analysis_turf_courses_{}_{}".format(pillar, combinations)
    for key in request_body:
        if request_body[key]:
            for value in request_body[key]:
                if key == 'occupation_ids':
                    match = re.search(r'C\d+$', value)
                    reg_occupation = match.group(0)
                    filename = filename + "_" + reg_occupation
                else:
                    filename = filename + "_" + value

    file_path = os.path.join(folder, filename)

    should_return, cached = _check_file(file_path)
    if should_return:
        return cached

    _reserve_file(file_path)

    print("Request body sent to /courses:", request_body)
    with _analysis_file(file_path):
        _, skill_labels_dict = load_esco()

        items = fetch_all_pages(request_body, endpoint='courses')
        if not items:
            _save_result(file_path, [])
            return []

        print(f"Number of courses: {len(items)}")
        skills_list = create_skills_list(items)

        all_skills_flat = [skill for sublist in skills_list for skill in sublist]
        skill_counts = Counter(all_skills_flat)
        top_20_tuples = skill_counts.most_common(20)
        top_20_skills = [item[0] for item in top_20_tuples]
        print(f"Top 20 frequent skills selected: {top_20_skills}")

        skills_df = create_skills_df(skills_list, top_20_skills)
        TURF_JSON = perform_turf_analysis_subset(skills_df, len(top_20_skills), skill_labels_dict, combinations)

        _save_result(file_path, TURF_JSON)
    return TURF_JSON


@app.get("/SkillsConcentration")
def skills_concentration(
        pillar: str,
        occupation_ids: Optional[str] = Query(None, description="Comma-separated occupation IDs"),
):
    folder = Path("Completed_Analyses")
    _ensure_folder(folder)

    occ_ids = _parse_csv_str(occupation_ids)

    filename = "completed_analysis_concentration_jobs_{}".format(pillar)
    for occ_id in (occ_ids or []):
        match = re.search(r'C\d+$', occ_id)
        reg_occupation = match.group(0) if match else occ_id
        filename = filename + "_" + reg_occupation

    file_path = os.path.join(folder, filename)

    should_return, cached = _check_file(file_path)
    if should_return:
        return cached

    _reserve_file(file_path)

    with _analysis_file(file_path):
        concentration_JSON = []
        for occ_id in occ_ids:
            request_body = {"occupation_ids": occ_id}
            print("Request body sent to /jobs:", request_body)

            items = fetch_all_pages(request_body, endpoint='jobs')
            if not items:
                continue

            print(f"Number of jobs for {occ_id}: {len(items)}")
            skills_list = create_skills_list(items)

            HCV_JSON = run_hcv(pillar, skills_list)
            level1, level2, level3, level4 = {}, {}, {}, {}

            for item in HCV_JSON:
                level = item["level"]
                skill = item["skill"]
                norm_prio = item["normalized priority"]
                if level == 1:
                    level1[skill] = norm_prio
                elif level == 2:
                    level2[skill] = norm_prio
                elif level == 3:
                    level3[skill] = norm_prio
                elif level == 4:
                    level4[skill] = norm_prio

            for lvl, d in {1: level1, 2: level2, 3: level3, 4: level4}.items():
                hhi = compute_hhi(d)
                status = classify(hhi)
                concentration_JSON.append({
                    "occupation": occ_id,
                    "level": lvl,
                    "Herfindahl - Hirschman Index": hhi,
                    "status": status
                })

        _save_result(file_path, concentration_JSON)
    return concentration_JSON