"""
Test VA PDF Report Generation - Iteration 38
Tests the new GET /api/vulnerability/report/{client_id} endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@86bit.it"
TEST_PASSWORD = "password"
TEST_CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"  # 86BIT_Office


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def headers(auth_token):
    """Headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestVAPDFReportEndpoint:
    """Tests for GET /api/vulnerability/report/{client_id}"""

    def test_report_requires_authentication(self):
        """Test that report endpoint requires authentication (401/403 without token)"""
        response = requests.get(f"{BASE_URL}/api/vulnerability/report/{TEST_CLIENT_ID}")
        # Both 401 and 403 are valid for unauthenticated requests
        assert response.status_code in [401, 403], f"Expected 401 or 403, got {response.status_code}"
        print(f"✓ Report endpoint requires authentication ({response.status_code} without token)")

    def test_report_returns_pdf(self, headers):
        """Test that report endpoint returns a valid PDF file"""
        response = requests.get(
            f"{BASE_URL}/api/vulnerability/report/{TEST_CLIENT_ID}",
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        
        # Check Content-Type header
        content_type = response.headers.get("Content-Type", "")
        assert "application/pdf" in content_type, f"Expected application/pdf, got {content_type}"
        print(f"✓ Content-Type is application/pdf: {content_type}")

    def test_report_has_content_disposition(self, headers):
        """Test that report has Content-Disposition header with filename"""
        response = requests.get(
            f"{BASE_URL}/api/vulnerability/report/{TEST_CLIENT_ID}",
            headers=headers
        )
        assert response.status_code == 200
        
        # Check Content-Disposition header
        content_disp = response.headers.get("Content-Disposition", "")
        assert "attachment" in content_disp, f"Expected attachment in Content-Disposition, got {content_disp}"
        assert "filename=" in content_disp, f"Expected filename in Content-Disposition, got {content_disp}"
        assert ".pdf" in content_disp, f"Expected .pdf in filename, got {content_disp}"
        print(f"✓ Content-Disposition header correct: {content_disp}")

    def test_report_pdf_content_valid(self, headers):
        """Test that the PDF content starts with PDF magic bytes"""
        response = requests.get(
            f"{BASE_URL}/api/vulnerability/report/{TEST_CLIENT_ID}",
            headers=headers
        )
        assert response.status_code == 200
        
        # PDF files start with %PDF-
        content = response.content
        assert content[:5] == b'%PDF-', f"PDF should start with %PDF-, got {content[:10]}"
        print(f"✓ PDF content valid (starts with %PDF-), size: {len(content)} bytes")

    def test_report_pdf_has_reasonable_size(self, headers):
        """Test that the PDF has reasonable size (not empty, not too small)"""
        response = requests.get(
            f"{BASE_URL}/api/vulnerability/report/{TEST_CLIENT_ID}",
            headers=headers
        )
        assert response.status_code == 200
        
        content_length = len(response.content)
        # PDF should be at least 5KB (a minimal PDF with content)
        assert content_length > 5000, f"PDF too small: {content_length} bytes"
        # PDF should be less than 10MB (reasonable upper limit)
        assert content_length < 10_000_000, f"PDF too large: {content_length} bytes"
        print(f"✓ PDF size is reasonable: {content_length} bytes ({content_length/1024:.1f} KB)")

    def test_report_invalid_client_returns_404(self, headers):
        """Test that report returns 404 for invalid client"""
        response = requests.get(
            f"{BASE_URL}/api/vulnerability/report/invalid-client-id-12345",
            headers=headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Report returns 404 for invalid client")


class TestVADashboardStillWorks:
    """Verify existing VA dashboard functionality still works"""

    def test_dashboard_endpoint(self, headers):
        """Test VA dashboard endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/vulnerability/dashboard/{TEST_CLIENT_ID}",
            headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "overall_score" in data
        assert "devices" in data
        assert "vulnerabilities" in data
        print(f"✓ Dashboard works: score={data['overall_score']}, devices={len(data['devices'])}, vulns={len(data['vulnerabilities'])}")

    def test_history_endpoint(self, headers):
        """Test VA history endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/vulnerability/history/{TEST_CLIENT_ID}",
            headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ History works: {len(data)} scans in history")

    def test_device_endpoint(self, headers):
        """Test VA device detail endpoint still works"""
        # First get a device IP from dashboard
        dashboard_response = requests.get(
            f"{BASE_URL}/api/vulnerability/dashboard/{TEST_CLIENT_ID}",
            headers=headers
        )
        assert dashboard_response.status_code == 200
        devices = dashboard_response.json().get("devices", [])
        
        if devices:
            device_ip = devices[0]["device_ip"]
            response = requests.get(
                f"{BASE_URL}/api/vulnerability/device/{TEST_CLIENT_ID}/{device_ip}",
                headers=headers
            )
            assert response.status_code == 200
            data = response.json()
            assert "device_ip" in data
            assert "vulnerabilities" in data
            print(f"✓ Device detail works for {device_ip}: {len(data['vulnerabilities'])} vulns")
        else:
            print("⚠ No devices to test device detail endpoint")

    def test_request_scan_endpoint_exists(self, headers):
        """Test request-scan endpoint still exists (may return 400/409 but not 404)"""
        response = requests.post(
            f"{BASE_URL}/api/vulnerability/request-scan/{TEST_CLIENT_ID}",
            headers=headers,
            json={}
        )
        # Should not be 404 (endpoint exists)
        # May be 400 (connector offline) or 409 (scan in progress) or 200 (success)
        assert response.status_code != 404, f"request-scan endpoint should exist, got 404"
        print(f"✓ request-scan endpoint exists (status: {response.status_code})")

    def test_scan_status_endpoint(self, headers):
        """Test scan-status endpoint still works"""
        response = requests.get(
            f"{BASE_URL}/api/vulnerability/scan-status/{TEST_CLIENT_ID}",
            headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        print(f"✓ scan-status works: status={data.get('status')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
