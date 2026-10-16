"""Audited MyToolsPlan bridge for authorized Envato downloads.

The official Envato MCP supplies catalog URLs, not bytes.  This adapter uses
the operator's OS-keyring credential to obtain a short-lived bridge session,
then consumes only the bridge's data endpoints.  Signed media URLs and portal
cookies never enter a Clipforge artifact or log.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from stat import S_IFLNK, S_IFMT, S_IFREG
from typing import Literal, cast

from clipforge.assets.credentials import PortalCredentials, require_portal_credentials
from clipforge.assets.mcp_client import AssetError

_PORTAL = "https://app.mytoolsplan.com"
_BRIDGE_PATH = "/go/envato-elements-server-1"
_MAX_RESPONSE = 2_000_000
_MAX_DOWNLOAD = 200_000_000
_SAFE_HOST_SUFFIXES = (".envatousercontent.com", ".mytoolsplan.site")
_MEDIA_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "audio": (".wav", ".mp3", ".m4a", ".aac", ".flac", ".aiff", ".ogg"),
    "video": (".mp4", ".mov", ".webm", ".mkv", ".avi"),
    "image": (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"),
    "graphic": (".svg", ".json", ".png", ".jpg", ".jpeg", ".webp"),
    "template": (".zip", ".aep", ".mogrt", ".prproj"),
    "unknown": (),
}
_PORTAL_ITEM_TYPES = {"music", "video", "photo", "graphics"}
_DOWNLOAD_URL = re.compile(r'"downloadUrl","((?:\\.|[^"\\])*)"')
_LICENSE = re.compile(
    r'"id","(?P<id>[A-Za-z0-9-]+)".*?'
    r'"itemUuid","(?P<item_uuid>[A-Za-z0-9-]+)".*?'
    r'"name","(?P<name>[^"]*)".*?'
    r'"licenseType","(?P<license_type>[^"]+)".*?'
    r'"createdAt","(?P<created_at>[^"]+)".*?'
    r'"licenseFileDownloadUrl","(?P<file_url>https?://[^"]+)".*?'
    r'"licenseFilePending",(?P<pending>true|false)',
    re.IGNORECASE,
)


def _safe_https_url(value: str, *, label: str, allow_envato_api: bool = False) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise AssetError(f"{label} is not a safe HTTPS URL", code="portal_protocol_error")
    host = (parsed.hostname or "").casefold()
    allowed = allow_envato_api and host == "elements.envato.com"
    if not host or (not allowed and not any(host.endswith(suffix) for suffix in _SAFE_HOST_SUFFIXES)):
        raise AssetError(f"{label} host is not allowlisted", code="portal_protocol_error")
    return parsed


def _decode_data_string(raw: str) -> str:
    try:
        value = json.loads(f'"{raw}"')
    except json.JSONDecodeError as exc:
        raise AssetError("portal data response contained an invalid URL", code="portal_protocol_error") from exc
    if not isinstance(value, str):
        raise AssetError("portal data response contained an invalid string", code="portal_protocol_error")
    return value


@dataclass(frozen=True, slots=True)
class PortalLicense:
    license_id: str
    item_uuid: str
    name: str
    license_type: str
    created_at: str
    certificate_url: str
    pending: bool


@dataclass(frozen=True, slots=True)
class PortalDownload:
    media_path: Path
    license_path: Path
    media_sha256: str
    license_sha256: str
    media_bytes: int
    license_bytes: int
    license: PortalLicense


@dataclass(frozen=True, slots=True)
class PortalItemIdentity:
    """Public item identity resolved from the portal page."""

    item_id: str
    item_uuid: str
    title: str
    item_type: str


class EnvatoPortalBridge:
    """One short-lived, in-memory portal session."""

    def __init__(self, credentials: PortalCredentials | None = None) -> None:
        self.credentials = credentials or require_portal_credentials()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        self._domain: str | None = None
        self._bsid: str | None = None

    def authenticate(self) -> None:
        self._request(_PORTAL + "/login", method="GET", headers={"User-Agent": "Clipforge-Envato-Bridge/1"})
        self._request(
            _PORTAL + "/login",
            method="POST",
            body=urllib.parse.urlencode(
                {"amember_login": self.credentials.username, "amember_pass": self.credentials.password}
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Clipforge-Envato-Bridge/1",
            },
        )
        ip_request = urllib.request.Request(
            "https://api.ipify.org?format=json", headers={"User-Agent": "Clipforge-Envato-Bridge/1"}
        )
        try:
            with urllib.request.urlopen(ip_request, timeout=15) as response:
                ip_payload = json.loads(response.read(1024).decode("utf-8"))
            ip = ip_payload.get("ip", "") if isinstance(ip_payload, dict) else ""
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise AssetError("portal fingerprint service was unavailable", code="portal_unavailable") from exc
        if not isinstance(ip, str) or not ip:
            raise AssetError("portal fingerprint service returned no IP", code="portal_protocol_error")
        fingerprint = hashlib.sha256(("|ip:" + ip).encode("utf-8")).hexdigest()
        body = json.dumps({"fingerprint": fingerprint}).encode("utf-8")
        response = self._request(
            _PORTAL + _BRIDGE_PATH,
            method="POST",
            body=body,
            headers={"Content-Type": "application/json", "User-Agent": "Clipforge-Envato-Bridge/1"},
        )
        try:
            payload = json.loads(response.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AssetError("portal bridge returned malformed JSON", code="portal_protocol_error") from exc
        if not isinstance(payload, dict):
            raise AssetError("portal bridge returned malformed JSON", code="portal_protocol_error")
        domain = payload.get("domain")
        token = payload.get("token")
        if payload.get("success") is not True or not isinstance(domain, str) or not isinstance(token, str):
            raise AssetError("portal bridge refused authentication", code="portal_auth_failed")
        parsed = _safe_https_url("https://" + domain, label="portal bridge domain")
        self._domain = f"{parsed.scheme}://{parsed.netloc}"
        bootstrap = self._request(
            f"{self._domain}/?token={urllib.parse.quote(token, safe='')}",
            method="GET",
            headers={"User-Agent": "Clipforge-Envato-Bridge/1"},
        ).decode("utf-8", errors="replace")
        match = re.search(r"document\.cookie='_bsid=([^;]+)", bootstrap)
        if match is None or not re.fullmatch(r"[A-Za-z0-9._~-]{16,256}", match.group(1)):
            raise AssetError("portal bridge session cookie was not returned", code="portal_protocol_error")
        self._bsid = match.group(1)

    def fetch_item(
        self,
        *,
        item_uuid: str,
        item_type: str,
        project_name: str,
        media_path: Path,
        license_path: Path,
    ) -> PortalDownload:
        self._require_session()
        try:
            canonical_uuid = str(uuid.UUID(item_uuid))
        except ValueError as exc:
            raise AssetError("portal item UUID is malformed", code="portal_protocol_error") from exc
        if canonical_uuid != item_uuid.casefold():
            raise AssetError("portal item UUID is malformed", code="portal_protocol_error")
        if item_type not in _PORTAL_ITEM_TYPES:
            raise AssetError("portal item type is unsupported", code="unsupported_media")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{1,100}", project_name):
            raise AssetError("portal license name is malformed", code="portal_protocol_error")
        license_record = self._create_license(item_uuid, project_name)
        if license_record.pending:
            raise AssetError("portal license certificate is still pending", code="license_pending")
        signed_url = self._signed_download_url(item_uuid, item_type)
        media_bytes, media_hash = self._download_to(signed_url, media_path, max_bytes=_MAX_DOWNLOAD)
        certificate_bytes, certificate_hash = self._download_to(
            f"{self._domain}/license-certificate/{license_record.license_id}/download",
            license_path,
            max_bytes=2_000_000,
            expected_prefix=b"%PDF",
        )
        return PortalDownload(
            media_path=media_path,
            license_path=license_path,
            media_sha256=media_hash,
            license_sha256=certificate_hash,
            media_bytes=media_bytes,
            license_bytes=certificate_bytes,
            license=license_record,
        )

    def resolve_item(self, item_page_url: str) -> PortalItemIdentity:
        """Resolve an MCP item page to the portal UUID before downloading it."""
        self._require_session()
        parsed = _safe_https_url(item_page_url, label="Envato item page", allow_envato_api=True)
        if parsed.hostname != "elements.envato.com" or parsed.query or parsed.fragment:
            raise AssetError("Envato item page URL is not canonical", code="portal_protocol_error")
        parts = parsed.path.split("/")
        if len(parts) != 2 or not parts[1] or parts[1] in {".", ".."}:
            raise AssetError("Envato item page URL is not an item path", code="portal_protocol_error")
        raw = self._request(f"{self._domain}/{parts[1]}", method="GET").decode("utf-8", errors="replace")
        match = re.search(r"window\.INITIAL_HYDRATION_DATA\s*=\s*(\"(?:\\.|[^\"\\])*\")", raw)
        if match is None:
            raise AssetError("portal item page had no identity data", code="portal_protocol_error")
        try:
            encoded = json.loads(match.group(1))
            payload = json.loads(base64.b64decode(encoded, validate=True))
            item = payload["page"]["data"]["data"]["item"]
            item_id = item["id"]
            item_uuid = item["itemUuid"]
            title = item["title"]
            item_type = item["itemType"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AssetError("portal item identity was malformed", code="portal_protocol_error") from exc
        if not all(
            isinstance(value, str) and value.strip() for value in (item_id, item_uuid, title, item_type)
        ):
            raise AssetError("portal item identity was incomplete", code="portal_protocol_error")
        if not all(isinstance(value, str) for value in (item_id, item_uuid, title, item_type)):
            raise AssetError("portal item identity was malformed", code="portal_protocol_error")
        assert isinstance(item_id, str)
        assert isinstance(item_uuid, str)
        assert isinstance(title, str)
        assert isinstance(item_type, str)
        try:
            canonical_uuid = str(uuid.UUID(item_uuid))
        except ValueError as exc:
            raise AssetError("portal item UUID was malformed", code="portal_protocol_error") from exc
        if canonical_uuid != item_uuid.casefold():
            raise AssetError("portal item UUID was malformed", code="portal_protocol_error")
        return PortalItemIdentity(item_id=item_id, item_uuid=canonical_uuid, title=title, item_type=item_type)

    def _signed_download_url(self, item_uuid: str, item_type: str) -> str:
        raw = self._portal_data("/download.data", {"itemUuid": item_uuid, "itemType": item_type})
        match = _DOWNLOAD_URL.search(raw)
        if match is None:
            raise AssetError("portal did not return a signed download URL", code="portal_download_failed")
        url = _decode_data_string(match.group(1))
        _safe_https_url(url, label="signed Envato download")
        return url

    def _create_license(self, item_uuid: str, project_name: str) -> PortalLicense:
        boundary = "----Clipforge" + secrets.token_hex(16)
        body = b"".join(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
                for key, value in {"itemUuid": item_uuid, "projectName": project_name}.items()
            )
        ) + f"--{boundary}--\r\n".encode("ascii")
        raw = self._request(
            f"{self._domain}/item-licenses.data",
            method="POST",
            body=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json, text/x-script, */*",
            },
        ).decode("utf-8", errors="replace")
        match = _LICENSE.search(raw)
        if match is None:
            raise AssetError("portal did not return a license certificate", code="license_failed")
        if match.group("item_uuid") != item_uuid:
            raise AssetError("portal license item does not match the requested item", code="license_failed")
        certificate = _decode_data_string(match.group("file_url"))
        # This URL is public license metadata only.  The bytes are fetched via
        # the authenticated bridge route below, never from a user-controlled
        # redirect or directly from Envato's API.
        _safe_https_url(certificate, label="license certificate URL", allow_envato_api=True)
        return PortalLicense(
            license_id=match.group("id"),
            item_uuid=match.group("item_uuid"),
            name=_decode_data_string(match.group("name")),
            license_type=match.group("license_type"),
            created_at=match.group("created_at"),
            certificate_url=certificate,
            pending=match.group("pending") == "true",
        )

    def _portal_data(self, path: str, query: dict[str, str]) -> str:
        return self._request(
            f"{self._domain}{path}?{urllib.parse.urlencode(query)}",
            method="GET",
            headers={"Accept": "text/x-script, application/json, */*"},
        ).decode("utf-8", errors="replace")

    def _require_session(self) -> None:
        if self._domain is None or self._bsid is None:
            raise AssetError("portal bridge is not authenticated", code="portal_auth_required")

    def _request(
        self, url: str, *, method: str, body: bytes | None = None, headers: dict[str, str] | None = None
    ) -> bytes:
        request_headers = {"User-Agent": "Clipforge-Envato-Bridge/1", **(headers or {})}
        if (
            self._bsid is not None
            and urllib.parse.urlparse(url).hostname == urllib.parse.urlparse(self._domain or "").hostname
        ):
            request_headers["Cookie"] = f"_bsid={self._bsid}"
            request_headers.setdefault("Referer", f"{self._domain}/")
        try:
            request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
            with self._opener.open(request, timeout=30) as response:
                raw = response.read(_MAX_RESPONSE)
                if len(raw) >= _MAX_RESPONSE:
                    raise AssetError("portal response exceeded the safety limit", code="portal_protocol_error")
                if response.status >= 400:
                    raise AssetError("portal request failed", code="portal_unavailable")
                return cast(bytes, raw)
        except AssetError:
            raise
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise AssetError("portal request failed", code="portal_unavailable") from exc

    def _download_to(
        self,
        url: str,
        destination: Path,
        *,
        max_bytes: int,
        expected_prefix: bytes | None = None,
    ) -> tuple[int, str]:
        _safe_https_url(url, label="portal download")
        if destination.is_symlink():
            raise AssetError("portal download target is a symlink", code="symlink")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.partial")
        digest = hashlib.sha256()
        size = 0
        try:
            with (
                urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "Clipforge-Envato-Bridge/1"}), timeout=60
                ) as response,
                temporary.open("wb") as sink,
            ):
                _safe_https_url(response.geturl(), label="portal download redirect")
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise AssetError("portal download exceeded the safety limit", code="file_size_limit")
                    digest.update(chunk)
                    sink.write(chunk)
            if (
                expected_prefix is not None
                and temporary.read_bytes()[: len(expected_prefix)] != expected_prefix
            ):
                raise AssetError("portal certificate is not a PDF", code="license_invalid")
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return size, digest.hexdigest()


def extract_media_archive(
    archive: Path,
    destination: Path,
    *,
    media_kind: Literal["audio", "video", "image", "graphic", "template", "unknown"],
    max_bytes: int,
) -> tuple[Path, int, str]:
    """Extract one deterministic media member without trusting archive paths.

    Envato's download endpoint normally returns a ZIP.  Extraction is kept
    outside the portal session and is deliberately strict: traversal names,
    symlinks and oversized members fail closed instead of silently choosing an
    unrelated file. When an item contains lossless and compressed variants,
    the first allowlisted extension in the media policy wins; multiple files
    of that preferred format remain ambiguous and fail closed.
    """
    if archive.is_symlink() or not archive.is_file():
        raise AssetError("portal archive is missing", code="portal_download_failed")
    if not zipfile.is_zipfile(archive):
        raise AssetError("portal download is not a supported ZIP archive", code="unsupported_media")
    extensions = _MEDIA_EXTENSIONS[media_kind]
    if not extensions:
        raise AssetError("media kind has no safe portal extraction policy", code="unsupported_media")
    try:
        with zipfile.ZipFile(archive) as bundle:
            candidates: dict[str, list[zipfile.ZipInfo]] = {extension: [] for extension in extensions}
            for member in bundle.infolist():
                name = member.filename
                path = Path(name)
                if (
                    not name
                    or "\x00" in name
                    or "\\" in name
                    or path.is_absolute()
                    or any(part in {"", ".", ".."} for part in path.parts)
                ):
                    raise AssetError("portal archive contains an unsafe path", code="portal_protocol_error")
                if "__MACOSX" in path.parts or path.name.startswith("._"):
                    continue
                mode = S_IFMT(member.external_attr >> 16)
                if mode == S_IFLNK:
                    raise AssetError("portal archive contains a symlink", code="portal_protocol_error")
                if member.is_dir() or (mode and mode != S_IFREG):
                    continue
                suffix = path.suffix.casefold()
                if suffix in candidates:
                    candidates[suffix].append(member)
            selected: zipfile.ZipInfo | None = None
            for extension in extensions:
                matches = candidates[extension]
                if len(matches) > 1:
                    raise AssetError(
                        "portal archive contains multiple files of the preferred media format",
                        code="ambiguous_media",
                    )
                if matches:
                    selected = matches[0]
                    break
            if selected is None:
                raise AssetError(
                    "portal archive contains no supported media file",
                    code="ambiguous_media",
                )
            member = selected
            if member.file_size <= 0 or member.file_size > max_bytes:
                raise AssetError("portal media member exceeds the safety limit", code="file_size_limit")
            suffix = Path(member.filename).suffix.lower()
            target = destination if destination.suffix else destination.with_suffix(suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise AssetError("portal extraction target is a symlink", code="symlink")
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
            digest = hashlib.sha256()
            size = 0
            try:
                with bundle.open(member) as source, temporary.open("wb") as sink:
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise AssetError(
                                "portal media member exceeds the safety limit", code="file_size_limit"
                            )
                        digest.update(chunk)
                        sink.write(chunk)
                if size != member.file_size:
                    raise AssetError("portal archive member was truncated", code="portal_protocol_error")
                os.replace(temporary, target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
    except zipfile.BadZipFile as exc:
        raise AssetError("portal download is a corrupt ZIP archive", code="portal_download_failed") from exc
    return target, size, digest.hexdigest()
