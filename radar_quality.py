"""Freshness, durable identity and review gates, independent of fetch transport."""

import csv
import datetime as dt
import hashlib
import json
import re
import tempfile
from pathlib import Path

UTC = dt.timezone.utc


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def stable_id(url):
    return "PR-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def atomic_json(path, data):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_seen(path, previous_csv):
    """CSV recovery covers a crash after output replacement but before state write."""
    seen = {}
    path = Path(path)
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or not isinstance(payload.get("seen"), dict)
        ):
            raise ValueError(
                "Invalid seen-state schema; refusing to reset deduplication"
            )
        seen.update(payload["seen"])
    if Path(previous_csv).exists():
        with Path(previous_csv).open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("Source_URL"):
                    seen.setdefault(row["Source_URL"], row.get("Retrieved_At_UTC", ""))
    return seen


def select_fresh(signals, seen, max_age_days, now=None):
    now = now or dt.datetime.now(UTC)
    cutoff = now - dt.timedelta(days=max_age_days)
    counts = {"duplicate": 0, "stale": 0, "invalid_date": 0, "future": 0}
    result, current = [], set()
    for signal in signals:
        published = timestamp(signal.created_utc)
        if published is None:
            counts["invalid_date"] += 1
        elif published > now + dt.timedelta(minutes=5):
            counts["future"] += 1
        elif published < cutoff:
            counts["stale"] += 1
        elif signal.url in seen or signal.url in current:
            counts["duplicate"] += 1
        else:
            current.add(signal.url)
            result.append(signal)
    return result, counts


def review_reason(signal):
    text = (signal.title + " " + signal.body).lower()
    if re.search(
        r"\b(sarcasm|satire|just kidding|intelligence agenc(?:y|ies))\b|/s\b", text
    ):
        return "possible_irony_or_sensitive_context; human_review_required"
    return "keyword_match_only; willingness_to_pay_and_competition_unverified"


def evaluate(signal):
    import pain_point_radar_engine as engine

    opportunity = engine.heuristic_evaluate_signal(signal)
    opportunity.id = stable_id(signal.url)
    opportunity.verdict = "WATCHLIST (待人工验证；规则分不代表付费意愿)"
    opportunity.workaround_and_flaws = (
        "尚未从原帖验证；需人工确认当前替代方案与实际成本"
    )
    opportunity.scoring_rationale = (
        "Keyword-category heuristic only; no independently verified budget or competition. "
        + review_reason(signal)
    )
    return opportunity
