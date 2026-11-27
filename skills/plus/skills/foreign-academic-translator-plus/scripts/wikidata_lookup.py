#!/usr/bin/env python3
"""Look up multilingual Wikidata item labels for a small batch of terms."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import sys
import time
import unicodedata
import zlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ENDPOINT = "https://www.wikidata.org/w/api.php"
USER_AGENT = (
    "AcademicTranslationSkills/4.1.0 "
    "(https://github.com/Koloyaaa/academic-translation-toolkit/issues)"
)
MAX_TERMS = 10
MAX_RESULTS = 5
MAX_RESPONSE_BYTES = 2_000_000
RESPONSE_CHUNK_BYTES = 64_000
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 2
MAX_LOOKUP_DURATION_SECONDS = 20.0
REQUEST_INTERVAL_SECONDS = 1.0
CACHE_SUCCESS_TTL_SECONDS = 30 * 24 * 60 * 60
CACHE_NOT_FOUND_TTL_SECONDS = 6 * 60 * 60
MAX_CACHE_ENTRIES = 2000
_LAST_REQUEST_STARTED = 0.0


class LookupError(Exception):
    """An expected API or network failure safe to report to the calling Skill."""


def _retry_delay(headers, attempt: int) -> float:
    value = headers.get("Retry-After", "").strip() if headers else ""
    if value:
        try:
            seconds = float(value)
            if math.isfinite(seconds) and seconds >= 0:
                return seconds + random.uniform(0.0, 0.5)
        except (TypeError, ValueError):
            pass
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
            if math.isfinite(seconds):
                return max(0.0, seconds) + random.uniform(0.0, 0.5)
        except (TypeError, ValueError, OverflowError):
            pass
    return 5.0 * (2**attempt) + random.uniform(0.0, 0.5)


def _lookup_time_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LookupError(
            f"Wikidata lookup exceeded its {MAX_LOOKUP_DURATION_SECONDS:.0f}-second total time budget."
        )
    return remaining


def _wait_before_retry(headers, attempt: int, deadline: float, failure_message: str) -> None:
    delay = _retry_delay(headers, attempt)
    remaining = _lookup_time_remaining(deadline)
    if delay >= remaining:
        raise LookupError(
            f"{failure_message} Retry-After/backoff exceeds the remaining time in the "
            f"{MAX_LOOKUP_DURATION_SECONDS:.0f}-second total lookup budget; "
            "the request was stopped without an early retry."
        )
    time.sleep(delay)
    _lookup_time_remaining(deadline)


def _pace_request(deadline: float) -> None:
    global _LAST_REQUEST_STARTED
    now = time.monotonic()
    _lookup_time_remaining(deadline)
    remaining = REQUEST_INTERVAL_SECONDS - (now - _LAST_REQUEST_STARTED)
    if _LAST_REQUEST_STARTED and remaining > 0:
        if remaining >= _lookup_time_remaining(deadline):
            raise LookupError(
                f"Wikidata request pacing exceeds the remaining time in the "
                f"{MAX_LOOKUP_DURATION_SECONDS:.0f}-second total lookup budget."
            )
        time.sleep(remaining)
    _lookup_time_remaining(deadline)
    _LAST_REQUEST_STARTED = time.monotonic()


def _response_socket(response):
    # urllib wraps the HTTP response around a buffered stream and socket.
    current = response
    for _ in range(3):
        fp = getattr(current, "fp", None)
        if fp is None:
            return None
        sock = getattr(getattr(fp, "raw", None), "_sock", None)
        if sock is not None and callable(getattr(sock, "settimeout", None)):
            return sock
        current = fp
    return None


def _read_response(response, deadline: float) -> bytes:
    reader = getattr(response, "read1", None)
    if not callable(reader):
        reader = getattr(getattr(response, "fp", None), "read1", None)
    if not callable(reader):
        reader = response.read

    payload = bytearray()
    while len(payload) <= MAX_RESPONSE_BYTES:
        remaining = _lookup_time_remaining(deadline)
        sock = _response_socket(response)
        if sock is not None:
            # Refresh the socket timeout so slow, chunked responses share the same deadline.
            sock.settimeout(remaining)
        chunk = reader(min(RESPONSE_CHUNK_BYTES, MAX_RESPONSE_BYTES + 1 - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
    _lookup_time_remaining(deadline)
    return bytes(payload)


def _request_json(params: dict[str, str], timeout: float, deadline: float) -> dict:
    url = f"{API_ENDPOINT}?{urlencode(params)}"
    for attempt in range(MAX_RETRIES + 1):
        _pace_request(deadline)
        request_timeout = min(timeout, _lookup_time_remaining(deadline))
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=request_timeout) as response:
                response_headers = response.headers
                payload = _read_response(response, deadline)
                content_encoding = response.headers.get("Content-Encoding", "").lower()
            try:
                if content_encoding == "gzip":
                    payload = gzip.decompress(payload)
                elif content_encoding == "deflate":
                    payload = zlib.decompress(payload)
            except (OSError, zlib.error) as error:
                raise LookupError("Wikidata returned invalid compressed data.") from error
            if len(payload) > MAX_RESPONSE_BYTES:
                raise LookupError("Wikidata returned an unexpectedly large response.")
            _lookup_time_remaining(deadline)
            result = json.loads(payload.decode("utf-8"))
            _lookup_time_remaining(deadline)
            if not isinstance(result, dict):
                raise LookupError("Wikidata returned an invalid JSON response.")
            if "error" in result:
                error = result.get("error") or {}
                error_code = str(error.get("code", "unknown"))
                failure_message = f"Wikidata API error: {error_code}."
                if error_code in {"maxlag", "ratelimited"} and attempt < MAX_RETRIES:
                    _wait_before_retry(response_headers, attempt, deadline, failure_message)
                    continue
                raise LookupError(failure_message)
            return result
        except HTTPError as error:
            failure_message = f"Wikidata returned HTTP {error.code}."
            if error.code in TRANSIENT_HTTP_CODES and attempt < MAX_RETRIES:
                _wait_before_retry(error.headers, attempt, deadline, failure_message)
                continue
            raise LookupError(failure_message) from error
        except (URLError, TimeoutError, OSError) as error:
            if attempt < MAX_RETRIES:
                reason = getattr(error, "reason", None)
                detail = type(reason).__name__ if reason is not None else type(error).__name__
                _wait_before_retry({}, attempt, deadline, f"Could not reach Wikidata ({detail}).")
                continue
            reason = getattr(error, "reason", None)
            detail = type(reason).__name__ if reason is not None else type(error).__name__
            raise LookupError(f"Could not reach Wikidata ({detail}).") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LookupError("Wikidata returned invalid JSON.") from error
    raise LookupError("Wikidata lookup failed after retries.")


def _cache_path() -> Path:
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Local"
    else:
        root = os.environ.get("XDG_CACHE_HOME")
        base = Path(root) if root else Path.home() / ".cache"
    return base / "AcademicTranslationSkills" / "wikidata-cache-v1.sqlite3"


def _open_cache():
    connection = None
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=2.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS term_cache ("
            "cache_key TEXT PRIMARY KEY, expires_at REAL NOT NULL, payload TEXT NOT NULL)"
        )
        connection.commit()
        return connection
    except (OSError, sqlite3.Error):
        if connection is not None:
            connection.close()
        return None


def _cache_key(term: str, source_language: str, target_language: str, limit: int) -> str:
    normalized_term = unicodedata.normalize("NFKC", term).strip().casefold()
    key_data = [
        "v1",
        normalized_term,
        source_language.strip().lower().replace("_", "-"),
        _target_languages(target_language),
        limit,
    ]
    encoded = json.dumps(key_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cache_get(connection, key: str, term: str) -> dict | None:
    if connection is None:
        return None
    try:
        row = connection.execute(
            "SELECT expires_at, payload FROM term_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        if row[0] <= time.time():
            connection.execute("DELETE FROM term_cache WHERE cache_key = ?", (key,))
            connection.commit()
            return None
        result = json.loads(row[1])
        if (
            not isinstance(result, dict)
            or result.get("status") not in {"OK", "NOT_FOUND"}
            or result.get("target_labels_status") == "UNAVAILABLE"
        ):
            return None
        result["term"] = term
        return result
    except (sqlite3.Error, json.JSONDecodeError, TypeError):
        return None


def _cache_store(connection, key: str, result: dict) -> None:
    if connection is None:
        return
    status = result.get("status")
    if status == "NOT_FOUND":
        ttl = CACHE_NOT_FOUND_TTL_SECONDS
    elif status == "OK" and result.get("target_labels_status") != "UNAVAILABLE":
        candidates = result.get("candidates", [])
        if any("target_label" not in candidate for candidate in candidates):
            return
        ttl = (
            CACHE_NOT_FOUND_TTL_SECONDS
            if any(candidate.get("target_label") is None for candidate in candidates)
            else CACHE_SUCCESS_TTL_SECONDS
        )
    else:
        return

    now = time.time()
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    try:
        connection.execute("DELETE FROM term_cache WHERE expires_at <= ?", (now,))
        connection.execute(
            "INSERT OR REPLACE INTO term_cache (cache_key, expires_at, payload) VALUES (?, ?, ?)",
            (key, now + ttl, payload),
        )
        connection.execute(
            "DELETE FROM term_cache WHERE cache_key NOT IN "
            "(SELECT cache_key FROM term_cache ORDER BY expires_at DESC LIMIT ?)",
            (MAX_CACHE_ENTRIES,),
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()


def _target_languages(language: str) -> list[str]:
    normalized = language.strip().lower().replace("_", "-")
    if normalized.startswith("zh"):
        return list(dict.fromkeys([normalized, "zh-cn", "zh-hans", "zh", "zh-sg"]))
    return [normalized]


def _search_term(
    term: str, source_language: str, limit: int, timeout: float, deadline: float
) -> dict:
    try:
        payload = _request_json(
            {
                "action": "wbsearchentities",
                "format": "json",
                "formatversion": "2",
                "search": term,
                "language": source_language,
                "uselang": source_language,
                "type": "item",
                "limit": str(limit),
                "maxlag": "5",
            },
            timeout,
            deadline,
        )
    except LookupError as error:
        return {"term": term, "status": "UNAVAILABLE", "message": str(error), "candidates": []}

    candidates = []
    for item in payload.get("search", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        match = item.get("match") if isinstance(item.get("match"), dict) else {}
        candidates.append(
            {
                "id": item["id"],
                "source_label": item.get("label", ""),
                "source_description": item.get("description", ""),
                "matched_text": match.get("text", ""),
                "match_type": match.get("type", ""),
                "url": f"https://www.wikidata.org/wiki/{item['id']}",
            }
        )
    return {
        "term": term,
        "status": "OK" if candidates else "NOT_FOUND",
        "candidates": candidates,
    }


def _attach_target_labels(
    results: list[dict], target_language: str, timeout: float, deadline: float
) -> None:
    ids = list(
        dict.fromkeys(
            candidate["id"]
            for result in results
            for candidate in result.get("candidates", [])
        )
    )
    if not ids:
        return

    try:
        payload = _request_json(
            {
                "action": "wbgetentities",
                "format": "json",
                "formatversion": "2",
                "ids": "|".join(ids),
                "props": "labels|descriptions|aliases",
                "languages": "|".join(_target_languages(target_language)),
                "maxlag": "5",
            },
            timeout,
            deadline,
        )
    except LookupError as error:
        for result in results:
            if result.get("candidates"):
                result["target_labels_status"] = "UNAVAILABLE"
                result["target_labels_message"] = str(error)
        return

    entities = payload.get("entities", [])
    if isinstance(entities, dict):
        entity_map = entities
    else:
        entity_map = {entity.get("id"): entity for entity in entities if isinstance(entity, dict)}

    languages = _target_languages(target_language)
    for result in results:
        for candidate in result.get("candidates", []):
            entity = entity_map.get(candidate["id"], {})
            labels = entity.get("labels", {}) if isinstance(entity, dict) else {}
            descriptions = entity.get("descriptions", {}) if isinstance(entity, dict) else {}
            aliases = entity.get("aliases", {}) if isinstance(entity, dict) else {}
            for language in languages:
                label = labels.get(language, {}).get("value")
                if label:
                    candidate["target_label"] = label
                    candidate["target_label_language"] = language
                    candidate["target_description"] = descriptions.get(language, {}).get("value", "")
                    candidate["target_aliases"] = [
                        alias.get("value", "") for alias in aliases.get(language, []) if alias.get("value")
                    ][:5]
                    break
            if "target_label" not in candidate:
                candidate["target_label"] = None
                candidate["target_label_language"] = None
                candidate["target_description"] = ""
                candidate["target_aliases"] = []


def lookup(
    terms: list[str],
    source_language: str,
    target_language: str,
    limit: int,
    timeout: float,
    cache_enabled: bool = True,
) -> dict:
    deadline = time.monotonic() + MAX_LOOKUP_DURATION_SECONDS
    unique_terms = []
    seen = set()
    for term in terms:
        normalized = term.strip()
        key = unicodedata.normalize("NFKC", normalized).casefold()
        if normalized and key not in seen:
            unique_terms.append(normalized)
            seen.add(key)

    cache_connection = _open_cache() if cache_enabled else None
    results_by_index = [None] * len(unique_terms)
    fresh_entries = []
    fresh_results = []
    paused_after_failure = False

    try:
        for index, term in enumerate(unique_terms):
            key = _cache_key(term, source_language, target_language, limit)
            cached = _cache_get(cache_connection, key, term)
            if cached is not None:
                results_by_index[index] = cached
            else:
                fresh_entries.append((index, term, key))

        for fresh_index, (index, term, key) in enumerate(fresh_entries):
            result = _search_term(term, source_language, limit, timeout, deadline)
            results_by_index[index] = result
            fresh_results.append(result)

            if result.get("status") == "UNAVAILABLE":
                paused_after_failure = True
                for pending_index, pending_term, _ in fresh_entries[fresh_index + 1 :]:
                    results_by_index[pending_index] = {
                        "term": pending_term,
                        "status": "UNAVAILABLE",
                        "message": (
                            "Wikidata lookup was paused after an earlier API failure; "
                            "this term was not sent."
                        ),
                        "candidates": [],
                    }
                break

        if paused_after_failure:
            for result in fresh_results:
                if result.get("status") == "OK" and result.get("candidates"):
                    result["target_labels_status"] = "UNAVAILABLE"
                    result["target_labels_message"] = (
                        "Target-language labels were not requested after Wikidata became unavailable."
                    )
        else:
            label_results = [result for result in fresh_results if result.get("candidates")]
            if label_results:
                _attach_target_labels(label_results, target_language, timeout, deadline)

        if cache_connection is not None:
            for (index, term, key), result in zip(fresh_entries, fresh_results):
                _cache_store(cache_connection, key, result)

        results = [result for result in results_by_index if result is not None]
        has_unavailable = any(
            result.get("status") == "UNAVAILABLE"
            or result.get("target_labels_status") == "UNAVAILABLE"
            for result in results
        )
        usage_note = (
            "Candidates are community-maintained knowledge-base entries, not authoritative subject dictionaries. "
            "Choose only a contextually suitable match; use contextual translation if results are ambiguous, "
            "lack a target-language label, or are unavailable."
        )
        if has_unavailable:
            usage_note += " Some lookups were skipped or unavailable; do not treat them as NOT_FOUND."

        return {
            "source": "Wikidata",
            "api": API_ENDPOINT,
            "data_license": "CC0 1.0",
            "source_language": source_language,
            "target_language": target_language,
            "results": results,
            "usage_note": usage_note,
        }
    finally:
        if cache_connection is not None:
            cache_connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Look up a few source-language terms in Wikidata and return target-language labels."
    )
    parser.add_argument("terms", nargs="+", help="one or more individual terms or short phrases")
    parser.add_argument("--source-language", required=True, help="Wikidata language code, such as en or fr")
    parser.add_argument("--target-language", default="zh-cn", help="target label language (default: zh-cn)")
    parser.add_argument("--limit", type=int, default=5, help="candidate limit per term (1-5)")
    parser.add_argument("--timeout", type=float, default=10.0, help="request timeout in seconds")
    parser.add_argument("--no-cache", action="store_true", help="skip the local Wikidata term cache")
    args = parser.parse_args()

    distinct_terms = {term.strip().casefold() for term in args.terms if term.strip()}
    if not distinct_terms:
        parser.error("Provide at least one non-empty term or short phrase.")
    if len(distinct_terms) > MAX_TERMS:
        parser.error(f"Use at most {MAX_TERMS} distinct terms per call.")
    language_pattern = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,15}$")
    if not language_pattern.fullmatch(args.source_language) or not language_pattern.fullmatch(args.target_language):
        parser.error("Language values must be Wikidata language codes, such as en, fr, or zh-cn.")
    if not 1 <= args.limit <= MAX_RESULTS:
        parser.error(f"--limit must be between 1 and {MAX_RESULTS}.")
    if not 0.5 <= args.timeout <= 60:
        parser.error("--timeout must be between 0.5 and 60 seconds.")

    result = lookup(
        args.terms,
        args.source_language,
        args.target_language,
        args.limit,
        args.timeout,
        cache_enabled=not args.no_cache,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
