# Contributing to Hierarchical Cumulative Voting

Thank you for your interest in contributing! This document outlines the process for reporting issues, proposing changes, and submitting code.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Enhancements](#suggesting-enhancements)
  - [Submitting Code Changes](#submitting-code-changes)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Pull Request Process](#pull-request-process)

---

## Code of Conduct

This project is part of the [SkillLab](https://github.com/skillab-project) EU Horizon Europe research initiative. All contributors are expected to engage respectfully and constructively. Harassment or disruptive behaviour of any kind will not be tolerated.

---

## Getting Started

Before contributing, please:

1. Read the [README](README.md) to understand the HCV algorithm, the TURF analysis pipeline, and how the ESCO mapping file drives the hierarchy.
2. Check the [open issues](https://github.com/skillab-project/hierarchical-cumulative-voting/issues) to see if your bug or idea has already been raised.
3. For significant changes — especially to the HCV priority propagation formula, the compensation factor logic, or the TURF skill selection strategy — open an issue first to discuss your approach before writing code.

---

## How to Contribute

### Reporting Bugs

Open an issue and include:

- A clear, descriptive title.
- Steps to reproduce, including the endpoint URL, pillar value, and any filter parameters used.
- Expected vs. actual behaviour, including any returned JSON.
- Environment details: OS, Python version, Docker version if applicable.
- Any error messages or tracebacks.

### Suggesting Enhancements

Describe the use case, your proposed solution, and any alternatives considered. Particularly welcome contributions include: additional ESCO pillar support, new data source endpoints, alternative skill selection strategies for TURF (e.g. top-N by coverage rather than raw frequency), and improvements to the caching or concurrency model.

### Submitting Code Changes

All contributions are made via **Pull Requests**. See [Pull Request Process](#pull-request-process) below.

---

## Development Setup

1. **Fork and clone your fork:**

   ```bash
   git clone https://github.com/<your-username>/hierarchical-cumulative-voting.git
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

4. **Configure `.env`:**

   ```env
   TRACKER_API=https://skillab-tracker.csd.auth.gr/api
   TRACKER_USERNAME=your_username
   TRACKER_PASSWORD=your_password
   ```

5. **Verify `new_ESCO_mapping.xlsx` is present** in the project root. This file is required at runtime and is already included in the repository.

6. **Start the development server:**

   ```bash
   uvicorn HCV:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## Coding Standards

- Follow [PEP 8](https://peps.python.org/pep-0008/) for all Python code.
- Add docstrings to new functions and classes, especially any that modify the HCV or TURF core logic.
- Keep functions focused on a single responsibility. The `run_hcv()` and `perform_turf_analysis_subset()` functions are the algorithmic core — changes to these should be carefully justified and tested.
- Do not commit credentials or secrets. Use `.env` for all configuration.
- Do not commit files in `Completed_Analyses/` — these are runtime artefacts and should remain gitignored.
- If you update `new_ESCO_mapping.xlsx`, document what changed and why in the PR description.

---

## Testing

```bash
pytest tests/
```

When contributing:

- Add or update tests for any new or changed behaviour.
- Ensure all existing tests pass before opening a PR.
- For changes to the HCV algorithm, include tests that verify: the output DataFrame contains the expected columns, ranks are correctly computed per level, and priority values are properly normalised (sum to ≤ 1.0 per level).
- For new endpoints, cover the main filter parameters and the expected response structure.

---

## Commit Message Guidelines

```
<type>: <short summary>
```

| Type       | When to use                                           |
|------------|-------------------------------------------------------|
| `feat`     | A new endpoint or algorithm variant                   |
| `fix`      | A bug fix                                             |
| `refactor` | Code restructuring without behaviour change           |
| `perf`     | Performance improvement (e.g. parallel fetch tuning)  |
| `test`     | Adding or updating tests                              |
| `docs`     | Documentation changes only                           |
| `chore`    | Dependency updates, CI config, tooling changes        |

Examples:

```
feat: add /TurfAnalysis/courses endpoint
fix: handle zero-frequency skill in HCV level-0 normalisation
perf: increase FETCH_WORKERS to 15 for large datasets
docs: document compensation factor formula in README
```

---

## Pull Request Process

1. **Branch naming:** e.g. `feat/turf-courses-endpoint` or `fix/hcv-zero-frequency`.
2. **Keep PRs focused:** One logical change per PR.
3. **Fill in the PR description** with what changed, why, and how it was tested.
4. **Link related issues** using `Closes #<issue-number>`.
5. **Review:** At least one maintainer review is required before merging.
6. **CI:** All automated checks must pass.

---

## Questions

Open a [discussion or issue](https://github.com/skillab-project/hierarchical-cumulative-voting/issues) if you have questions not covered here.
