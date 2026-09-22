from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.models import AIProvider
from app.schemas import AIDraftResponse
from app.security import decrypt_secret

BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal", "metadata.azure.internal"}


class ProviderSafetyError(ValueError):
    pass


def classify_and_validate_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ProviderSafetyError(
            "Provider URL must be an absolute HTTP(S) URL without embedded credentials."
        )
    host = parsed.hostname.lower()
    if host in BLOCKED_HOSTS or host.endswith(".internal"):
        raise ProviderSafetyError(
            "The selected provider host is blocked by the outbound endpoint policy."
        )
    classification = "remote"
    is_private = host == "localhost" or host.endswith(".local")
    try:
        address = ipaddress.ip_address(host)
        if address.is_loopback or address.is_private:
            is_private = True
        if (
            address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        ):
            raise ProviderSafetyError(
                "Link-local, multicast, unspecified, and reserved provider addresses are blocked."
            )
    except ValueError:
        # Hostnames other than .local remain remote. No blind DNS request is made here.
        pass
    if is_private:
        classification = "local"
    if parsed.scheme == "http" and (
        classification == "remote" or not get_settings().allow_private_http
    ):
        raise ProviderSafetyError(
            "HTTP is allowed only for explicitly enabled local or private-network providers."
        )
    return classification


def _headers(provider: AIProvider) -> dict[str, str]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    api_key = decrypt_secret(provider.encrypted_api_key)
    bearer = decrypt_secret(provider.encrypted_bearer_token)
    custom = decrypt_secret(provider.encrypted_headers)
    if api_key:
        headers["X-API-Key"] = api_key
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if custom:
        decoded = json.loads(custom)
        if not isinstance(decoded, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in decoded.items()
        ):
            raise ProviderSafetyError("Provider custom headers are invalid.")
        headers.update(decoded)
    return headers


def _prompt(raw_note: str, metadata: dict[str, object]) -> str:
    return f"""You are CareerForge's factual writing assistant. Return ONLY one JSON object with keys:
title, action, metric, impact, supporting_narrative, suggested_categories, suggested_tags,
suggested_technologies, identified_facts, assumptions, placeholders, questions, quality_checks.
Use only facts supplied below. Never invent counts, dates, systems, time savings, downtime,
security or business outcomes. For missing facts use visible bracketed placeholders and concise questions.
Every result is an AI Draft — Review Required.

Raw note:
{raw_note}

User-provided metadata:
{json.dumps(metadata, ensure_ascii=False)}"""


async def generate_draft(
    provider: AIProvider, raw_note: str, metadata: dict[str, object]
) -> AIDraftResponse:
    classification = classify_and_validate_url(provider.base_url)
    if classification == "remote" and not metadata.get("remote_confirmation"):
        raise ProviderSafetyError(
            "Remote provider requires explicit confirmation after reviewing transmitted data."
        )
    endpoint = provider.base_url.rstrip("/") + "/api/generate"
    payload = {
        "model": provider.default_model,
        "prompt": _prompt(raw_note, metadata),
        "stream": False,
        "format": "json",
    }
    timeout = httpx.Timeout(provider.timeout_seconds)
    max_bytes = get_settings().max_ai_response_bytes
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.post(endpoint, headers=_headers(provider), json=payload)
        response.raise_for_status()
        content = response.content
    if len(content) > max_bytes:
        raise ProviderSafetyError("Provider response exceeded the configured size limit.")
    try:
        response_json = json.loads(content)
        result = json.loads(response_json["response"])
        return AIDraftResponse.model_validate(result)
    except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as exc:
        raise ProviderSafetyError(
            "The provider returned invalid structured JSON; no draft was saved."
        ) from exc


async def list_models(provider: AIProvider) -> list[str]:
    classify_and_validate_url(provider.base_url)
    endpoint = provider.base_url.rstrip("/") + "/api/tags"
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(provider.timeout_seconds), follow_redirects=False
    ) as client:
        response = await client.get(endpoint, headers=_headers(provider))
        response.raise_for_status()
    body = response.json()
    return [
        str(item["name"])
        for item in body.get("models", [])
        if isinstance(item, dict) and item.get("name")
    ]
