import pytest
import pandas as pd
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, mock_open
import io
import os

from HCV import app, compute_hhi, _parse_csv_str

client = TestClient(app)


# ==========================================
# 1. MOCK DATA
# ==========================================

# Level 0 matches the loop 'for level in range(len(filtered))'
MOCK_ESCO_DF = pd.DataFrame({
    'conceptUri': ['uri:parent', 'uri:child'],
    'preferredLabel': ['Parent Skill', 'Child Skill'],
    'skills_levels': ["[0]", "[0]"],  # String for eval()
    'knowledge_levels': ["[]", "[]"],
    'traversal_levels': ["[]", "[]"],
    'skills_ancestors': ["[[]]", "[['uri:parent']]"],
    'knowledge_ancestors': ["[[]]", "[[]]"],
    'traversal_ancestors': ["[[]]", "[[]]"],
    'children': ["['uri:child']", "[]"]
})

# ==========================================
# 2. UNIT TESTS
# ==========================================

def test_parse_csv_str():
    assert _parse_csv_str("a, b, c") == ["a", "b", "c"]
    assert _parse_csv_str("") is None

def test_compute_hhi():
    data = {"skill_a": 1.0}
    assert compute_hhi(data) == 10000.0

@patch("pandas.read_excel")
def test_run_hcv_logic(mock_excel):
    """Tests the HCV algorithm logic directly."""
    # Ensure a fresh copy of mock data
    mock_excel.return_value = MOCK_ESCO_DF.copy()
    from HCV import run_hcv
    
    mock_skills_list = [["uri:child"], ["uri:child"]]
    result = run_hcv("skills", mock_skills_list)
    
    assert len(result) > 0
    assert result[0]["skill"] == "Child Skill"
    assert "normalized priority" in result[0]


@patch("HCV.req.post")
@patch("pandas.read_excel")
@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
def test_hcv_jobs_endpoint(mock_file, mock_exists, mock_excel, mock_post):
    """Test HCV Jobs and delete created file."""
    mock_exists.return_value = False 
    mock_excel.return_value = MOCK_ESCO_DF.copy()
    
    mock_login = MagicMock(); mock_login.text = '"fake_token"'; mock_login.status_code = 200
    mock_api_data = MagicMock(); mock_api_data.json.return_value = {"count": 1, "items": [{"skills": ["uri:child"]}]}
    mock_api_data.status_code = 200
    mock_post.side_effect = [mock_login, mock_api_data, mock_login, mock_api_data]

    # Predict filename: completed_analysis_hcv_jobs_skills_python
    target_file = os.path.join("Completed_Analyses", "completed_analysis_hcv_jobs_skills_python")

    try:
        response = client.get("/HierarchicalCumulativeVoting/jobs?pillar=skills&keywords=python")
        assert response.status_code == 200
    finally:
        if os.path.exists(target_file):
            os.remove(target_file)
            print(f"\n🗑️ Deleted test file: {target_file}")


@patch("HCV.create_skills_df")
@patch("HCV.fetch_all_pages")
@patch("pandas.read_excel")
@patch("os.path.exists")
@patch("builtins.open", new_callable=mock_open)
def test_turf_analysis_endpoint(mock_file, mock_exists, mock_excel, mock_fetch, mock_df):
    """Test Turf Analysis and delete created file."""
    mock_exists.return_value = False # Force creation logic
    mock_excel.return_value = MOCK_ESCO_DF.copy()
    
    # fetch_all_pages returns the items list directly
    mock_fetch.return_value = [{"skills": ["uri:child"]}]
    
    # Mock the dataframe returned by create_skills_df
    # The column name must match the skill URI passed into it
    mock_df.return_value = pd.DataFrame({"list_index": [0], "uri:child": ["yes"]})

    try:
        response = client.get("/TurfAnalysis/jobs?pillar=skills&combinations=1&keywords=python")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert data[0]["Reach"] == 1
    finally:
        pass