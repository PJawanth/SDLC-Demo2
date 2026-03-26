"""Tests for the Incident Management Dashboard."""
import json
from datetime import datetime, timedelta

import pytest

import app as app_module


@pytest.fixture(autouse=True)
def reset_incidents():
    """Clear and re-seed incidents before every test."""
    app_module.INCIDENTS.clear()
    app_module._next_id = 1
    app_module._seed_data()
    yield


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestIsOverdue:
    def test_overdue_when_past(self):
        inc = {"due_at": (datetime.utcnow() - timedelta(hours=1)).isoformat()}
        assert app_module.is_overdue(inc) is True

    def test_not_overdue_when_future(self):
        inc = {"due_at": (datetime.utcnow() + timedelta(hours=1)).isoformat()}
        assert app_module.is_overdue(inc) is False


class TestShouldEscalate:
    def test_critical_open_is_escalated(self):
        inc = {"severity": "Critical", "status": "Open",
               "due_at": (datetime.utcnow() + timedelta(hours=5)).isoformat()}
        assert app_module.should_escalate(inc) is True

    def test_critical_closed_is_not_escalated(self):
        inc = {"severity": "Critical", "status": "Closed",
               "due_at": (datetime.utcnow() + timedelta(hours=5)).isoformat()}
        assert app_module.should_escalate(inc) is False

    def test_high_overdue_is_escalated(self):
        inc = {"severity": "High", "status": "Open",
               "due_at": (datetime.utcnow() - timedelta(hours=2)).isoformat()}
        assert app_module.should_escalate(inc) is True

    def test_high_not_overdue_is_not_escalated(self):
        inc = {"severity": "High", "status": "Open",
               "due_at": (datetime.utcnow() + timedelta(hours=5)).isoformat()}
        assert app_module.should_escalate(inc) is False

    def test_closed_high_overdue_is_not_escalated(self):
        inc = {"severity": "High", "status": "Closed",
               "due_at": (datetime.utcnow() - timedelta(hours=2)).isoformat()}
        assert app_module.should_escalate(inc) is False


class TestGetEscalationReason:
    def test_critical_reason(self):
        inc = {"severity": "Critical", "status": "Open",
               "due_at": (datetime.utcnow() + timedelta(hours=5)).isoformat()}
        assert "Critical" in app_module.get_escalation_reason(inc)

    def test_high_overdue_reason(self):
        inc = {"severity": "High", "status": "Open",
               "due_at": (datetime.utcnow() - timedelta(hours=2)).isoformat()}
        reason = app_module.get_escalation_reason(inc)
        assert "overdue" in reason.lower()

    def test_closed_has_no_reason(self):
        inc = {"severity": "Critical", "status": "Closed",
               "due_at": (datetime.utcnow() + timedelta(hours=5)).isoformat()}
        assert app_module.get_escalation_reason(inc) == ""


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_dashboard_renders(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Incident Management Dashboard" in resp.data


class TestListIncidents:
    def test_returns_json_list(self, client):
        resp = client.get("/incidents")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1


class TestCreateIncident:
    def _valid_payload(self):
        return {
            "title": "Test incident",
            "description": "Something broke",
            "severity": "High",
            "impacted_service": "Billing",
            "owner": "Tester",
            "due_at": (datetime.utcnow() + timedelta(hours=4)).isoformat(),
        }

    def test_create_valid_incident(self, client):
        resp = client.post("/incidents", json=self._valid_payload())
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Test incident"
        assert data["status"] == "Open"

    def test_create_critical_incident_auto_escalated(self, client):
        payload = self._valid_payload()
        payload["severity"] = "Critical"
        resp = client.post("/incidents", json=payload)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["escalated"] is True
        assert "Critical" in data["escalation_reason"]

    def test_validation_missing_title(self, client):
        payload = self._valid_payload()
        payload["title"] = ""
        resp = client.post("/incidents", json=payload)
        assert resp.status_code == 400
        errors = resp.get_json()["errors"]
        assert any("title" in e for e in errors)

    def test_validation_missing_multiple_fields(self, client):
        resp = client.post("/incidents", json={})
        assert resp.status_code == 400
        errors = resp.get_json()["errors"]
        assert len(errors) >= 2

    def test_validation_invalid_severity(self, client):
        payload = self._valid_payload()
        payload["severity"] = "Extreme"
        resp = client.post("/incidents", json=payload)
        assert resp.status_code == 400


class TestUpdateStatus:
    def test_update_to_closed_clears_escalation(self, client):
        # Find a critical (escalated) incident
        incidents = client.get("/incidents").get_json()
        critical = next(i for i in incidents if i["severity"] == "Critical" and i["status"] != "Closed")
        assert critical["escalated"] is True

        resp = client.post(f"/incidents/{critical['id']}/status", json={"status": "Closed"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["escalated"] is False
        assert data["escalation_reason"] == ""

    def test_invalid_status_rejected(self, client):
        resp = client.post("/incidents/1/status", json={"status": "Banana"})
        assert resp.status_code == 400

    def test_not_found(self, client):
        resp = client.post("/incidents/9999/status", json={"status": "Open"})
        assert resp.status_code == 404


class TestOverdueHighEscalation:
    def test_high_overdue_incident_is_escalated_in_list(self, client):
        """The seeded High-severity overdue incident should appear escalated."""
        incidents = client.get("/incidents").get_json()
        high_overdue = [i for i in incidents
                        if i["severity"] == "High"
                        and app_module.is_overdue(i)
                        and i["status"] != "Closed"]
        assert len(high_overdue) >= 1
        for inc in high_overdue:
            assert inc["escalated"] is True
            assert "overdue" in inc["escalation_reason"].lower()
