from __future__ import annotations
import random
import logging
import time
from dataclasses import dataclass
from typing import Any
import requests
from .config import Settings
from .storage import PostgresStorage

LOGGER = logging.getLogger(__name__)


class RiotApiError(RuntimeError):
    pass

@dataclass(frozen=True)
class PlayerContext:
    puuid: str
    summoner_id: str

class RiotApiClient:
    def __init__(self, api_key: str, region: str, platform: str, timeout_seconds: int = 20) -> None:
        self._region = region
        self._platform = platform
        self._timeout = timeout_seconds
        self._session = requests.Session()
        self._session.headers.update({"X-Riot-Token": api_key})

    def _request_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        max_retries = 5
        attempt = 0
        while True:
            response = self._session.get(url, params=params, timeout=self._timeout)
            if response.status_code == 429:
                if attempt >= max_retries:
                    raise RiotApiError(f"Rate limit exceeded for {url} after {max_retries} retries")
                retry_after = response.headers.get("Retry-After")
                try:
                    wait_seconds = float(retry_after) if retry_after else float(min(2 ** attempt, 30))
                except(ValueError,TypeError):
                    wait_seconds = float(min(2 ** attempt,30))   
                wait_seconds = wait_seconds + random.uniform(0,0.5)
                
                LOGGER.warning("Riot API rate limited (429). Retrying in %s second(s).", wait_seconds)
                time.sleep(wait_seconds)
                attempt += 1
                continue

            if not response.ok:
                raise RiotApiError(f"Riot API request failed: {response.status_code} {response.text}")

            return response.json()

    def get_puuid(self, game_name: str, tag_line: str) -> str:
        url = f"https://{self._region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        payload = self._request_json(url)
        return str(payload["puuid"])

    def get_summoner(self, puuid: str) -> dict[str, Any]:
        url = f"https://{self._platform}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        payload = self._request_json(url)
        if not isinstance(payload, dict):
            raise RiotApiError("Expected object response for Summoner-V4")
        return payload

    def list_match_ids(self, puuid: str, start: int = 0, count: int = 100) -> list[str]:
        url = f"https://{self._region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        payload = self._request_json(url, params={"start": start, "count": count})
        if not isinstance(payload, list):
            raise RiotApiError("Expected list response for Match-V5 match IDs")
        return [str(match_id) for match_id in payload]

    def get_match_detail(self, match_id: str) -> dict[str, Any]:
        url = f"https://{self._region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        payload = self._request_json(url)
        if not isinstance(payload, dict):
            raise RiotApiError("Expected object response for Match-V5 match detail")
        return payload


def resolve_player_context(client: RiotApiClient, settings: Settings) -> PlayerContext:
    puuid = client.get_puuid(settings.riot_game_name, settings.riot_tag_line)
    summoner = client.get_summoner(puuid)
    summoner_id = str(summoner["id"])
    return PlayerContext(puuid=puuid, summoner_id=summoner_id)


def find_new_match_ids(
    client: RiotApiClient,
    puuid: str,
    last_match_id: str | None,
    page_size: int = 100,
    max_pages: int = 20,
) -> list[str]:
    new_ids: list[str] = []
    pages_fetched = 0
    watermark_hit = False

    for page_idx in range(max_pages):
        start = page_idx * page_size
        LOGGER.info(f"Fetching match IDs page {page_idx+1} (start={start}, count={page_size})")
        page = client.list_match_ids(puuid=puuid, start=start, count=page_size)
        if not page:
            LOGGER.info(f"Page {page_idx+1} returned 0 matches. Stopping search.")
            break

        pages_fetched = pages_fetched + 1
        LOGGER.info(f"Fetched {len(page)} match IDs from page {page_idx+1}")

        for match_id in page:
            if last_match_id and match_id == last_match_id:
                watermark_hit = True
                LOGGER.info(f"Watermark hit at page {page_idx+1} with match ID {last_match_id}. Stopping search.")
                LOGGER.info(f"Total new match IDs found: {len(new_ids)}")
                LOGGER.info(f"Pages fetched before watermark stop: {pages_fetched}" )
                return new_ids
            new_ids.append(match_id)

        if len(page) < page_size:
            LOGGER.info(f"Page {page_idx+1} has fewer items than requested page size {page_size}. Reached the end of available results.")
            break

    LOGGER.info(f"Finished scanning match ID pages. Total new match IDs found: {len(new_ids)}")
    LOGGER.info(f"Pages fetched in this run: {pages_fetched}" )
    if watermark_hit:
        LOGGER.info("Watermark was reached during this scan.")
    else:
        LOGGER.info("Watermark was not reached during this scan.")
    return new_ids


def extract_incremental(settings: Settings, storage: PostgresStorage,dry_run:bool = False) -> int:
    client = RiotApiClient(
        api_key=settings.riot_api_key,
        region=settings.riot_region,
        platform=settings.riot_platform,
    )
    player = resolve_player_context(client, settings)
    watermark = storage.get_watermark(player.puuid)
    match_ids = find_new_match_ids(client, puuid=player.puuid, last_match_id=watermark.last_match_id)

    if not match_ids:
        LOGGER.info(f"No new matches found for puuid={player.puuid}")
        return 0

    total_matches = len(match_ids)
    
    if dry_run:
        LOGGER.info(f"[Dry_run] candidate new match IDs found {total_matches}. Skipping database writes and watermark updates")
        return total_matches

    LOGGER.info(f"Starting match detail extraction for {total_matches} new matches...")
    
    for idx,match_id in enumerate(match_ids,start=1):
        payload = client.get_match_detail(match_id)
        storage.upsert_raw_match(player.puuid, match_id, payload)
        
        if idx % 20 == 0 or idx == total_matches:
            LOGGER.info(f"Match detail progress: {idx}/{total_matches} matches processed.")

    storage.update_watermark(player.puuid, latest_match_id=match_ids[0])
    return len(match_ids)


def extract_backfill(settings: Settings, storage: PostgresStorage, limit: int,dry_run:bool = False) -> int:
    client = RiotApiClient(
        api_key=settings.riot_api_key,
        region=settings.riot_region,
        platform=settings.riot_platform,
    )
    player = resolve_player_context(client, settings)
    collected: list[str] = []

    page_size = 100
    pages = (limit + page_size - 1) // page_size
    for page_idx in range(pages):
        start = page_idx * page_size
        fetch_count = min(page_size,limit-len(collected))
        LOGGER.info(f"Fetching backfill match IDs page {page_idx+1} (start={start}, count={fetch_count})...")
        page = client.list_match_ids(puuid=player.puuid, start=start, count=min(page_size, limit - len(collected)))
        if not page:
            LOGGER.info(f"Backfill page {page_idx+1} return 0 matches.stopping search")
            break
        LOGGER.info(f"fetched {len(page)} backfill match IDs from page {page_idx+1}")
        collected.extend(page)
        if len(collected) >= limit:
            break

    match_ids = collected[:limit]
    total_matches = len(match_ids)
    
    if dry_run:
        LOGGER.info("[Dry_run] candidate new match IDs found %s. Skipping database writes and watermark updates", total_matches)
        return total_matches

    for idx, match_id in enumerate(match_ids, start=1):
        payload = client.get_match_detail(match_id)
        storage.upsert_raw_match(player.puuid, match_id, payload)

        if idx % 20 == 0 or idx == total_matches:
            LOGGER.info(f"backfill matches detail progress:{idx}/{total_matches} matches processed.")
    if match_ids:
        storage.update_watermark(player.puuid, latest_match_id=match_ids[0])

    return len(match_ids)

