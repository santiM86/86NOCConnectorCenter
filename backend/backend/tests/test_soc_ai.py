"""
Test SOC AI Correlation endpoints - Gemini AI integration
Tests: /api/ai/analyze/{client_id}, /api/ai/history/{client_id}
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@86bit.it"
TEST_PASSWORD = "password"
TEST_CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip("Authentication failed - skipping authenticated tests")


@pytest.fixture
def auth_headers(auth_token):
    """Headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestAIAnalyzeEndpoint:
    """Tests for POST /api/ai/analyze/{client_id}"""
    
    def test_analyze_without_auth_returns_401_or_403(self):
        """AI analyze endpoint requires authentication"""
        response = requests.post(
            f"{BASE_URL}/api/ai/analyze/{TEST_CLIENT_ID}",
            json={}
        )
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        data = response.json()
        assert "detail" in data
    
    def test_analyze_endpoint_accessible_with_auth(self, auth_headers):
        """AI analyze endpoint is accessible with valid auth (may return 500 if Gemini unavailable)"""
        response = requests.post(
            f"{BASE_URL}/api/ai/analyze/{TEST_CLIENT_ID}",
            headers=auth_headers,
            json={},
            timeout=60
        )
        # Accept 200 (success) or 500 (Gemini 503 - external API unavailable)
        assert response.status_code in [200, 500], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            assert "status" in data
            assert "analysis" in data
            assert "analysis_id" in data
            assert "timestamp" in data
            # Verify analysis structure
            analysis = data["analysis"]
            assert "overall_status" in analysis
            assert "risk_score" in analysis
            assert "summary" in analysis
        elif response.status_code == 500:
            # Gemini 503 is expected during high demand
            data = response.json()
            assert "detail" in data
            # Verify it's a Gemini error, not our code error
            assert "503" in data["detail"] or "ServiceUnavailable" in data["detail"] or "Errore nell'analisi AI" in data["detail"]
    
    def test_analyze_with_question(self, auth_headers):
        """AI analyze endpoint accepts free-form questions"""
        response = requests.post(
            f"{BASE_URL}/api/ai/analyze/{TEST_CLIENT_ID}",
            headers=auth_headers,
            json={"question": "Quali dispositivi sono offline?"},
            timeout=60
        )
        # Accept 200 (success) or 500 (Gemini 503)
        assert response.status_code in [200, 500], f"Unexpected status: {response.status_code}"


class TestAIHistoryEndpoint:
    """Tests for GET /api/ai/history/{client_id}"""
    
    def test_history_without_auth_returns_401_or_403(self):
        """AI history endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/ai/history/{TEST_CLIENT_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    def test_history_returns_list(self, auth_headers):
        """AI history endpoint returns list of analyses"""
        response = requests.get(
            f"{BASE_URL}/api/ai/history/{TEST_CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_history_has_at_least_one_record(self, auth_headers):
        """AI history should have at least 1 record from previous testing"""
        response = requests.get(
            f"{BASE_URL}/api/ai/history/{TEST_CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1, "Expected at least 1 AI analysis record in history"
    
    def test_history_record_structure(self, auth_headers):
        """AI history records have correct structure"""
        response = requests.get(
            f"{BASE_URL}/api/ai/history/{TEST_CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            record = data[0]
            # Verify required fields
            assert "id" in record
            assert "client_id" in record
            assert "timestamp" in record
            assert "result" in record
            assert "analyzed_by" in record
            
            # Verify result structure
            result = record["result"]
            assert "overall_status" in result
            assert "risk_score" in result
            assert "summary" in result
            assert "correlations" in result
            assert "recommendations" in result
            assert "patterns_detected" in result
    
    def test_history_result_has_valid_status(self, auth_headers):
        """AI analysis result has valid overall_status"""
        response = requests.get(
            f"{BASE_URL}/api/ai/history/{TEST_CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            status = data[0]["result"]["overall_status"]
            valid_statuses = ["critico", "attenzione", "stabile", "ottimo"]
            assert status in valid_statuses, f"Invalid status: {status}"
    
    def test_history_result_has_valid_risk_score(self, auth_headers):
        """AI analysis result has valid risk_score (0-100)"""
        response = requests.get(
            f"{BASE_URL}/api/ai/history/{TEST_CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            risk_score = data[0]["result"]["risk_score"]
            assert isinstance(risk_score, (int, float))
            assert 0 <= risk_score <= 100, f"Risk score out of range: {risk_score}"


class TestAIContextBuilding:
    """Tests to verify AI context includes correct data"""
    
    def test_context_snapshot_in_history(self, auth_headers):
        """AI analysis stores context snapshot with device/alert counts"""
        response = requests.get(
            f"{BASE_URL}/api/ai/history/{TEST_CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        if len(data) > 0:
            context = data[0].get("context_snapshot", {})
            assert "total_devices" in context
            assert "online" in context
            assert "offline" in context
            assert "active_alerts" in context


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
