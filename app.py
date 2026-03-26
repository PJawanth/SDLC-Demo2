from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory data store (swap for DB later)
# ---------------------------------------------------------------------------
INCIDENTS: list[dict] = []
_next_id = 1


def _seed_data():
    """Populate sample incidents for demo purposes."""
    global _next_id
    now = datetime.utcnow()
    samples = [
        {
            "title": "Database cluster failover",
            "description": "Primary DB node unresponsive, automatic failover triggered.",
            "severity": "Critical",
            "impacted_service": "Payment Service",
            "owner": "Alice",
            "created_at": (now - timedelta(hours=6)).isoformat(),
            "due_at": (now + timedelta(hours=2)).isoformat(),
            "status": "Open",
        },
        {
            "title": "High memory usage on API gateway",
            "description": "Memory utilisation exceeded 90% on api-gw-03.",
            "severity": "High",
            "impacted_service": "API Gateway",
            "owner": "Bob",
            "created_at": (now - timedelta(hours=12)).isoformat(),
            "due_at": (now - timedelta(hours=1)).isoformat(),  # overdue
            "status": "In Progress",
        },
        {
            "title": "SSL certificate expiring soon",
            "description": "Certificate for *.example.com expires in 7 days.",
            "severity": "Medium",
            "impacted_service": "Web Portal",
            "owner": "Carol",
            "created_at": (now - timedelta(days=2)).isoformat(),
            "due_at": (now + timedelta(days=5)).isoformat(),
            "status": "Open",
        },
        {
            "title": "Minor UI alignment issue",
            "description": "Footer overlaps on mobile view.",
            "severity": "Low",
            "impacted_service": "Web Portal",
            "owner": "Dave",
            "created_at": (now - timedelta(days=5)).isoformat(),
            "due_at": (now + timedelta(days=10)).isoformat(),
            "status": "Open",
        },
        {
            "title": "Network latency spike in US-East",
            "description": "Latency exceeded 500ms for 15 minutes.",
            "severity": "Critical",
            "impacted_service": "CDN",
            "owner": "Eve",
            "created_at": (now - timedelta(hours=3)).isoformat(),
            "due_at": (now + timedelta(hours=1)).isoformat(),
            "status": "In Progress",
        },
        {
            "title": "Resolved auth token leak",
            "description": "Leaked token was rotated and revoked.",
            "severity": "Critical",
            "impacted_service": "Auth Service",
            "owner": "Frank",
            "created_at": (now - timedelta(days=1)).isoformat(),
            "due_at": (now - timedelta(hours=12)).isoformat(),
            "status": "Closed",
        },
    ]
    for s in samples:
        _add_incident(s)


# ---------------------------------------------------------------------------
# Helper / business-logic functions
# ---------------------------------------------------------------------------

VALID_SEVERITIES = {"Low", "Medium", "High", "Critical"}
VALID_STATUSES = {"Open", "In Progress", "Resolved", "Closed"}
REQUIRED_FIELDS = ["title", "description", "severity", "impacted_service", "owner", "due_at"]


def is_overdue(incident: dict) -> bool:
    """Return True when the incident's due date is in the past."""
    try:
        due = datetime.fromisoformat(incident["due_at"])
    except (KeyError, ValueError):
        return False
    return due < datetime.utcnow()


def should_escalate(incident: dict) -> bool:
    """Determine whether an incident needs escalation."""
    if incident.get("status") == "Closed":
        return False
    if incident.get("severity") == "Critical":
        return True
    if incident.get("severity") == "High" and is_overdue(incident):
        return True
    return False


def get_escalation_reason(incident: dict) -> str:
    """Return a human-readable escalation reason, or empty string."""
    if incident.get("status") == "Closed":
        return ""
    if incident.get("severity") == "Critical":
        return "Critical severity — automatic escalation"
    if incident.get("severity") == "High" and is_overdue(incident):
        return "High severity incident is overdue"
    return ""


def _apply_escalation(incident: dict) -> None:
    """Set escalation fields based on current state."""
    incident["escalated"] = should_escalate(incident)
    incident["escalation_reason"] = get_escalation_reason(incident)


def _add_incident(data: dict) -> dict:
    """Create an incident dict, assign an id, apply escalation, and store it."""
    global _next_id
    now = datetime.utcnow().isoformat()
    incident = {
        "id": _next_id,
        "title": data["title"],
        "description": data["description"],
        "severity": data["severity"],
        "impacted_service": data["impacted_service"],
        "owner": data["owner"],
        "created_at": data.get("created_at", now),
        "due_at": data["due_at"],
        "status": data.get("status", "Open"),
        "escalated": False,
        "escalation_reason": "",
    }
    _apply_escalation(incident)
    INCIDENTS.append(incident)
    _next_id += 1
    return incident


def _validate_new_incident(data: dict) -> list[str]:
    """Return a list of validation error messages (empty = valid)."""
    errors = []
    for field in REQUIRED_FIELDS:
        if not data.get(field, "").strip():
            errors.append(f"'{field}' is required.")
    if data.get("severity") and data["severity"] not in VALID_SEVERITIES:
        errors.append(f"Invalid severity. Must be one of: {', '.join(sorted(VALID_SEVERITIES))}.")
    if data.get("due_at"):
        try:
            datetime.fromisoformat(data["due_at"])
        except ValueError:
            errors.append("'due_at' must be a valid ISO-format datetime.")
    return errors


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    severity_filter = request.args.get("severity", "")
    status_filter = request.args.get("status", "")
    escalated_filter = request.args.get("escalated", "")

    # Re-apply escalation on every view so overdue flags stay current
    for inc in INCIDENTS:
        _apply_escalation(inc)

    filtered = INCIDENTS[:]
    if severity_filter:
        filtered = [i for i in filtered if i["severity"] == severity_filter]
    if status_filter:
        filtered = [i for i in filtered if i["status"] == status_filter]
    if escalated_filter == "true":
        filtered = [i for i in filtered if i["escalated"]]
    elif escalated_filter == "false":
        filtered = [i for i in filtered if not i["escalated"]]

    # Summary metrics (always computed on full dataset)
    total = len(INCIDENTS)
    open_count = sum(1 for i in INCIDENTS if i["status"] == "Open")
    critical_count = sum(1 for i in INCIDENTS if i["severity"] == "Critical")
    escalated_count = sum(1 for i in INCIDENTS if i["escalated"])

    return render_template(
        "index.html",
        incidents=filtered,
        total=total,
        open_count=open_count,
        critical_count=critical_count,
        escalated_count=escalated_count,
        severity_filter=severity_filter,
        status_filter=status_filter,
        escalated_filter=escalated_filter,
        severities=sorted(VALID_SEVERITIES),
        statuses=sorted(VALID_STATUSES),
        is_overdue=is_overdue,
    )


@app.route("/incidents", methods=["GET"])
def list_incidents():
    for inc in INCIDENTS:
        _apply_escalation(inc)
    return jsonify(INCIDENTS)


@app.route("/incidents", methods=["POST"])
def create_incident():
    # Support both JSON and form-encoded payloads
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    errors = _validate_new_incident(data)
    if errors:
        if request.is_json:
            return jsonify({"errors": errors}), 400
        return redirect(url_for("dashboard", error="|".join(errors)))

    incident = _add_incident(data)

    if request.is_json:
        return jsonify(incident), 201
    return redirect(url_for("dashboard"))


@app.route("/incidents/<int:incident_id>/status", methods=["POST"])
def update_status(incident_id: int):
    incident = next((i for i in INCIDENTS if i["id"] == incident_id), None)
    if incident is None:
        if request.is_json:
            return jsonify({"error": "Incident not found"}), 404
        return redirect(url_for("dashboard"))

    if request.is_json:
        new_status = (request.get_json() or {}).get("status", "")
    else:
        new_status = request.form.get("status", "")

    if new_status not in VALID_STATUSES:
        if request.is_json:
            return jsonify({"error": f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}"}), 400
        return redirect(url_for("dashboard"))

    incident["status"] = new_status
    _apply_escalation(incident)

    if request.is_json:
        return jsonify(incident)
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_seed_data()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
