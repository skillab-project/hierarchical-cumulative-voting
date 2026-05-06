import pytest
import os
import shutil
from fastapi.testclient import TestClient
from dotenv import load_dotenv

from HCV import app

load_dotenv()

TRACKER_CREDS = os.getenv("TRACKER_USERNAME") and os.getenv("TRACKER_PASSWORD")
EXCEL_EXISTS = os.path.exists("new_ESCO_mapping.xlsx")
CACHE_FOLDER = "Completed_Analyses"


@pytest.fixture(scope="session")
def client():
    """
    Session-scoped TestClient that uses the app as a context manager,
    which properly triggers the lifespan (startup/shutdown) events.
    This ensures _cleanup_stale_sentinels() runs before any test.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def cleanup_only_new_files():
    """
    Snapshot fixture: 
    1. Records files existing before tests.
    2. Runs tests.
    3. Deletes only the files created during the session.
    """
    # Capture state BEFORE tests
    pre_existing_files = set()
    if os.path.exists(CACHE_FOLDER):
        pre_existing_files = set(os.listdir(CACHE_FOLDER))
    else:
        # Create folder if it doesn't exist so os.listdir doesn't crash
        os.makedirs(CACHE_FOLDER, exist_ok=True)

    yield # --- Tests run here ---

    # Capture state AFTER tests
    if os.path.exists(CACHE_FOLDER):
        current_files = set(os.listdir(CACHE_FOLDER))
        # Find the difference (newly created files)
        new_files = current_files - pre_existing_files

        for filename in new_files:
            file_path = os.path.join(CACHE_FOLDER, filename)
            try:
                os.remove(file_path)
                print(f"\n🗑️ Cleaned up test artifact: {filename}")
            except Exception as e:
                print(f"\n⚠️ Could not remove {filename}: {e}")


@pytest.mark.skipif(not TRACKER_CREDS, reason="TRACKER_USERNAME or TRACKER_PASSWORD missing in .env")
@pytest.mark.skipif(not EXCEL_EXISTS, reason="new_ESCO_mapping.xlsx not found in root directory")
class TestHCVAnalysis:
    def test_hcv_jobs_endpoint(self, client):
        """Tests the Hierarchical Cumulative Voting for Jobs."""
        response = client.get(
            "/HierarchicalCumulativeVoting/jobs",
            params={
                "pillar": "skills",
                "keywords": "python",
                "location_code": "EL"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_hcv_policies_endpoint(self, client):
        """Tests HCV logic for Law/Policy documents."""
        response = client.get(
            "/HierarchicalCumulativeVoting/policies",
            params={
                "pillar": "knowledge",
                "keywords": "artificial intelligence"
            }
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

@pytest.mark.skipif(not TRACKER_CREDS or not EXCEL_EXISTS, reason="Dependencies missing")
class TestTurfAnalysis:

    def test_turf_jobs_endpoint(self, client):
        """Tests the Total Unduplicated Reach and Frequency (TURF) analysis."""
        response = client.get(
            "/TurfAnalysis/jobs",
            params={
                "pillar": "skills",
                "combinations": 2,
                "location_code": "EL",
                "keywords": "sql"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
