from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

def validate_match_payload(match_payload: dict[str, Any], target_puuid: str) -> tuple[bool, str | None]:
    """Validates the structure and required fields of a Riot Match-V5 payload."""
    if not isinstance(match_payload, dict):
        return False, "Match payload is not a valid dictionary"

    metadata = match_payload.get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("matchId"):
        return False, "Missing or invalid 'metadata.matchId'"

    info = match_payload.get("info")
    if not isinstance(info, dict):
        return False, "Missing or invalid 'info' object"

    participants = info.get("participants")
    if not isinstance(participants, list):
        return False, "Missing or invalid 'info.participants' list"

    if info.get("gameCreation") is None:
        return False, "Missing 'info.gameCreation'"

    participant = next((item for item in participants if isinstance(item, dict) and item.get("puuid") == target_puuid), None)
    if not participant:
        return False, f"Participant with PUUID '{target_puuid}' not found in match"

    required_participant_fields = [
        "championId",
        "teamId",
        "kills",
        "deaths",
        "assists",
        "win",
    ]
    for field in required_participant_fields:
        if field not in participant or participant[field] is None:
            return False, f"Missing required participant field: '{field}'"

    return True, None


def extract_self_participant_row(match_payload: dict[str, Any], target_puuid: str) -> dict[str, Any]:
    metadata = match_payload["metadata"]
    info = match_payload["info"]
    participants = info["participants"]

    participant = next(item for item in participants if item["puuid"] == target_puuid)

    game_creation_ms = int(info["gameCreation"])
    match_dt = datetime.fromtimestamp(game_creation_ms / 1000, tz=timezone.utc)

    return {
        "match_id": metadata["matchId"],
        "puuid": target_puuid,
        "match_date": match_dt.date().isoformat(),
        "champion_id": participant.get("championId"),
        "champion_name": participant.get("championName"),
        "queue_id": info.get("queueId"),
        "game_duration_seconds": info.get("gameDuration"),
        "win": participant.get("win"),
        "kills": participant.get("kills"),
        "deaths": participant.get("deaths"),
        "assists": participant.get("assists"),
        "gold_earned": participant.get("goldEarned"),
        "total_minions_killed": participant.get("totalMinionsKilled"),
        "neutral_minions_killed": participant.get("neutralMinionsKilled"),
        "total_damage_dealt_to_champions": participant.get("totalDamageDealtToChampions"),
    }

