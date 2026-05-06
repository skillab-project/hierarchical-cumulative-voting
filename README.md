# Hierarchical Cumulative Voting (HCV) Back-End

[![GitHub Repo](https://img.shields.io/badge/GitHub-Repo-blue?logo=github)](https://github.com/skillab-project/hierarchical-cumulative-voting)

## Description

This project implements the backend API for the **Hierarchical Cumulative Voting (HCV)** framework — an open-source tool for ranking and prioritising ESCO skills across the full skill hierarchy, and for running **TURF (Total Unduplicated Reach and Frequency) analysis** on skill combinations.

It is built with FastAPI (Python) and exposes two families of endpoints:

**HCV endpoints** (`/HierarchicalCumulativeVoting/...`) — given a data source (jobs, policies, profiles, or courses) and an ESCO skill pillar, the algorithm:
1. Fetches all matching documents from the SkillLab Tracker API, paginated in parallel with up to 10 concurrent workers (page size 300).
2. Loads the ESCO skill hierarchy from `new_ESCO_mapping.xlsx`.
3. Expands each document's skill list to include all ancestor skills at every hierarchy level.
4. Computes relative skill frequencies across all documents.
5. Runs the HCV algorithm level by level: at level 0, each child's priority is `freq(child) × freq(ancestor)`, normalised over all children at that level; at deeper levels, the ancestor's accumulated normalised priority propagates downward, weighted by a compensation factor equal to the number of children at that level.
6. Returns a ranked DataFrame (as JSON) with: `skill`, `level`, `ancestor`, `relative frequency`, `ancestor frequency`, `compensation factor`, `intermediate priority`, `normalized priority`, `rank`.

**TURF endpoints** (`/TurfAnalysis/...`) — given the same data sources and filters, the algorithm:
1. Fetches all documents and selects the **top 20 most frequently occurring skills**.
2. Builds a binary presence matrix (yes/no per skill per document).
3. Evaluates all skill combinations of the requested size `n` drawn from the top 20.
4. Returns, for each combination: `Reach` (number of documents covered by at least one skill in the combo), `Reach %`, `Frequency` (total occurrences), and `Frequency Ratio`, sorted by reach then frequency.

Results from all long-running analyses are cached to `Completed_Analyses/` using an in-progress sentinel mechanism. Stale sentinel files from crashed runs are automatically cleaned up at application startup via a FastAPI `lifespan` handler.

The service is part of the [SkillLab](https://github.com/skillab-project) EU Horizon Europe project.

---

## Getting Started Guide

### Prerequisites

- **Python 3.11** or newer ([Download Python](https://www.python.org/downloads/))
- **Git** ([Download Git](https://git-scm.com/downloads))
- **Access to the SkillLab Tracker API** — credentials for `TRACKER_API`, `TRACKER_USERNAME`, and `TRACKER_PASSWORD`.
- **`new_ESCO_mapping.xlsx`** — included in the repository root. This file contains the full ESCO skill hierarchy (concept URIs, preferred labels, hierarchy levels, ancestors, children) and **must be present at runtime**.

---

### Installation Steps

1. **Clone the repository:**

   ```bash
   git clone https://github.com/skillab-project/hierarchical-cumulative-voting.git
   cd hierarchical-cumulative-voting
   ```

2. **Create and activate a virtual environment:**

   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux/macOS
   venv\Scripts\activate      # Windows
   ```

3. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure your `.env` file:**

   ```env
   TRACKER_API=https://skillab-tracker.csd.auth.gr/api
   TRACKER_USERNAME=your_username
   TRACKER_PASSWORD=your_password
   ```

   > The `.env` file is included as an empty placeholder. The app reads these at startup via `python-dotenv`.

5. **Verify the ESCO mapping file is present** in the project root:

   ```
   new_ESCO_mapping.xlsx
   ```

---

## Running the Application

### Locally

```bash
uvicorn HCV:app --host 0.0.0.0 --port 8000 --reload
```

The API will be accessible at `http://localhost:8000`. Interactive documentation (Swagger UI) is at `http://localhost:8000/docs`.

> In production the app is mounted under the `/hcv` root path. For local development the default root `/` applies.

> On startup, any stale in-progress sentinel files left by previously crashed runs are automatically removed so subsequent requests can retry.

### With Docker

```bash
docker-compose up --build
```

Or manually:

```bash
docker build -t hierarchical-cumulative-voting .
docker run -p 8009:8000 --env-file .env hierarchical-cumulative-voting
```

---

## ESCO Skill Pillars

Both HCV and TURF endpoints require a `pillar` parameter specifying which branch of the ESCO skill hierarchy to analyse:

| Value        | Description                         |
|--------------|-------------------------------------|
| `skills`     | Skill pillar (procedural know-how)  |
| `knowledge`  | Knowledge pillar (declarative)      |
| `traversal`  | Transversal / cross-cutting skills  |

---

## API Endpoints

### HCV — Hierarchical Cumulative Voting

All HCV endpoints return a JSON array of skill ranking records. Example record:

```json
{
  "skill": "python",
  "level": 2,
  "ancestor": "programming languages",
  "relative frequency": 0.43,
  "ancestor frequency": 1.0,
  "compensation factor": 5,
  "intermediate priority": 0.215,
  "normalized priority": 0.031,
  "rank": 1.0
}
```

Results are cached to `Completed_Analyses/` keyed by pillar and all filter values. Subsequent identical requests return the cached result instantly.

#### `GET /HierarchicalCumulativeVoting/jobs`

| Parameter             | Type    | Description                                          |
|-----------------------|---------|------------------------------------------------------|
| `pillar`              | string  | **Required.** `skills`, `knowledge`, or `traversal`  |
| `keywords`            | string  | Comma-separated keywords                             |
| `keywords_logic`      | string  | `AND` or `OR`                                        |
| `ids`                 | string  | Comma-separated job IDs (integers)                   |
| `skill_ids`           | string  | Comma-separated ESCO skill URIs                      |
| `skill_ids_logic`     | string  | `AND` or `OR`                                        |
| `occupation_ids`      | string  | Comma-separated ESCO occupation URIs                 |
| `occupation_ids_logic`| string  | `AND` or `OR`                                        |
| `organization_ids`    | string  | Comma-separated organization IDs (integers)          |
| `min_upload_date`     | string  | `YYYY-MM-DD`                                         |
| `max_upload_date`     | string  | `YYYY-MM-DD`                                         |
| `location_code`       | string  | Comma-separated location codes                       |
| `sources`             | string  | Comma-separated sources (e.g. `linkedin,indeed`)     |

#### `GET /HierarchicalCumulativeVoting/policies`

| Parameter              | Type    | Description              |
|------------------------|---------|--------------------------|
| `pillar`               | string  | **Required.**            |
| `keywords`             | string  |                          |
| `ids`                  | string  | Comma-separated policy IDs (integers) |
| `skill_ids`            | string  |                          |
| `min_publication_date` | string  | `YYYY-MM-DD`             |
| `max_publication_date` | string  | `YYYY-MM-DD`             |
| `min_page_count`       | integer |                          |
| `max_page_count`       | integer |                          |
| `type`                 | string  | Law policy type          |
| `sources`              | string  |                          |

#### `GET /HierarchicalCumulativeVoting/profiles`

Same filter parameters as jobs, minus occupation and location fields.

#### `GET /HierarchicalCumulativeVoting/courses`

Same as jobs plus: `min_creation_date`, `max_creation_date`, `min_rating`, `max_rating`, `min_price`, `max_price`.

---

### TURF — Total Unduplicated Reach and Frequency

All TURF endpoints accept the same filter parameters as their HCV counterparts, with these **additional required parameters:**

| Parameter      | Type    | Description                                                                |
|----------------|---------|----------------------------------------------------------------------------|
| `pillar`       | string  | **Required.** `skills`, `knowledge`, or `traversal`                        |
| `combinations` | integer | **Required.** Size of each skill combo to evaluate (e.g. `2` for pairs)   |

> TURF analysis always operates on the **top 20 most frequent skills** in the retrieved dataset. `combinations` must be between 1 and 20.

**Response** — a JSON array sorted by `Reach` descending then `Frequency` descending:

```json
[
  {
    "Combination": "python+machine learning",
    "Reach": 8430,
    "Reach %": 67.44,
    "Frequency": 12500,
    "Frequency Ratio": 1.48,
    "Combination Number": 2
  }
]
```

#### `GET /TurfAnalysis/jobs`
#### `GET /TurfAnalysis/policies`
#### `GET /TurfAnalysis/profiles`
#### `GET /TurfAnalysis/courses`

---

## Caching & Concurrency

- Completed results are persisted to `Completed_Analyses/` as JSON files named after the pillar and active filter values.
- An **in-progress sentinel** (`{"status": "in_progress"}`) is written to the cache file before analysis starts. Concurrent requests for the same filters receive this sentinel immediately rather than triggering a duplicate run.
- On startup, any **stale sentinel files** left by previously crashed processes are deleted automatically.
- If an analysis fails mid-run, the sentinel file is deleted and the exception is re-raised, allowing the next request to retry cleanly.

---

## Running the Tests

```bash
pytest tests/
```

---

## Project Structure

```
hierarchical-cumulative-voting/
├── HCV.py                   # FastAPI app, HCV algorithm, TURF analysis, all endpoints
├── new_ESCO_mapping.xlsx    # ESCO skill hierarchy mapping (required at runtime)
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container image definition
├── docker-compose.yml       # Compose configuration
├── .env                     # Environment variables (fill in before running)
├── Completed_Analyses/      # Cached analysis results (auto-created at runtime)
├── jenkins/                 # CI/CD pipeline configuration
└── tests/                   # Test suite
```

---

## Technologies

- **Python 3.11**
- **FastAPI** — REST API framework
- **Uvicorn** — ASGI server
- **pandas / openpyxl** — ESCO mapping file parsing and DataFrame operations
- **concurrent.futures** — Parallel page fetching (`ThreadPoolExecutor`, 10 workers, page size 300)
- **python-dotenv** — Environment variable management
- **Docker / Docker Compose** — Containerised deployment

---

## License

This project is licensed under the **Eclipse Public License 2.0 (EPL-2.0)**. See the [LICENSE](LICENSE) file for details.
