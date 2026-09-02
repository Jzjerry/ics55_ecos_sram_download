#!/usr/bin/env python3
"""Download an SRAM PDK package from ECOS Factory.

The script uses only Python's standard library. It validates the SRAM
configuration locally, calls the generate endpoint, downloads the returned
GitHub Release asset, and verifies its SHA-256 digest.

Examples:
    python3 download_sram_pdk.py
    python3 download_sram_pdk.py --words 4096 --bits 64 --mux 8
    python3 download_sram_pdk.py --preview --mux 16 --words 1024 --bits 32
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://factory.openecos.com"
DEFAULT_USER_AGENT = "ecos-sram-pdk-downloader/1.0"
CHUNK_SIZE = 1024 * 1024

# mux: (minimum words, maximum words, word step, minimum bits, maximum bits)
MUX_RULES: dict[int, tuple[int, int, int, int, int]] = {
    4: (32, 4096, 32, 2, 160),
    8: (64, 8192, 64, 2, 80),
    16: (128, 16384, 128, 2, 40),
    32: (256, 32768, 256, 2, 20),
}

PVT_CORNERS = (
    "TT1P2V25CCTYP",
    "TT1P2V85CCTYP",
    "FF1P32VM40CCMIN",
    "FF1P32V0CCMIN",
    "FF1P32V125CCMIN",
    "SS1P08VM40CCMAX",
    "SS1P08V0CCMAX",
    "SS1P08V125CCMAX",
)
RINGS = ("ringless", "port", "ring")


class SramError(RuntimeError):
    """An expected configuration, API, or download failure."""


def validate_config(config: dict[str, Any]) -> None:
    """Validate a payload against the published SRAM contract."""
    integer_fields = (
        "words",
        "bits",
        "mux",
        "vt",
        "lowPower",
        "redundancy",
        "wordWrite",
        "busFormat",
    )
    for field in integer_fields:
        if type(config.get(field)) is not int:  # bool must not count as an int.
            raise SramError(f"{field} must be an integer")

    mux = config["mux"]
    if mux not in MUX_RULES:
        raise SramError(f"mux must be one of: {', '.join(map(str, MUX_RULES))}")

    words = config["words"]
    min_words, max_words, step, min_bits, max_bits = MUX_RULES[mux]
    if not min_words <= words <= max_words:
        raise SramError(
            f"words for mux={mux} must be between {min_words} and {max_words}"
        )
    if (words - min_words) % step != 0:
        raise SramError(f"words for mux={mux} must use a step of {step}")

    bits = config["bits"]
    if not min_bits <= bits <= max_bits:
        raise SramError(
            f"bits for mux={mux} must be between {min_bits} and {max_bits}"
        )

    allowed_values = {
        "vt": (0, 2, 5),
        "lowPower": (0, 2),
        "redundancy": (0, 3),
        "wordWrite": (0, 1),
        "busFormat": (0, 1),
    }
    for field, values in allowed_values.items():
        if config[field] not in values:
            allowed = ", ".join(map(str, values))
            raise SramError(f"{field} must be one of: {allowed}")

    if config.get("ring") not in RINGS:
        raise SramError(f"ring must be one of: {', '.join(RINGS)}")
    if config.get("corner") not in PVT_CORNERS:
        raise SramError(f"corner must be one of: {', '.join(PVT_CORNERS)}")


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    """Build the exact JSON payload expected by the API."""
    return {
        "words": args.words,
        "bits": args.bits,
        "mux": args.mux,
        "vt": args.vt,
        "lowPower": args.low_power,
        "redundancy": args.redundancy,
        "wordWrite": args.word_write,
        "busFormat": args.bus_format,
        "ring": args.ring,
        "corner": args.corner,
    }


def _error_body(error: HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace").strip()
    except OSError:
        body = ""
    return f": {body[:500]}" if body else ""


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    user_agent: str,
) -> dict[str, Any]:
    """POST JSON and decode an object response."""
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as error:
        raise SramError(f"POST {url} failed with HTTP {error.code}{_error_body(error)}") from error
    except (URLError, socket.timeout, TimeoutError, OSError) as error:
        raise SramError(f"POST {url} failed: {error}") from error

    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SramError(f"POST {url} returned invalid JSON") from error
    if not isinstance(decoded, dict):
        raise SramError(f"POST {url} returned JSON that is not an object")
    return decoded


def _validate_http_url(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SramError(f"generate response field {field!r} is missing")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SramError(f"generate response field {field!r} is not an HTTP(S) URL")
    return value


def extract_artifact(response: dict[str, Any]) -> tuple[str, str | None, str, str]:
    """Extract and validate download metadata from a generate response."""
    if response.get("ok") is not True:
        detail = response.get("error") or response.get("message") or "unknown API error"
        raise SramError(f"generate request was rejected: {detail}")

    value = response.get("value")
    if not isinstance(value, dict):
        raise SramError("generate response does not contain an object value")

    download_url = _validate_http_url(value.get("downloadUrl"), "downloadUrl")
    mirror_value = value.get("mirrorUrl")
    mirror_url = None
    if mirror_value:
        mirror_url = _validate_http_url(mirror_value, "mirrorUrl")

    asset_name = value.get("assetName")
    if not isinstance(asset_name, str) or not asset_name:
        raise SramError("generate response field 'assetName' is missing")
    if (
        Path(asset_name).name != asset_name
        or "\\" in asset_name
        or asset_name in {".", ".."}
    ):
        raise SramError("assetName must be a plain file name")

    sha256 = value.get("sha256")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise SramError("generate response field 'sha256' must be a 64-character hex digest")

    return download_url, mirror_url, asset_name, sha256.lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_once(
    url: str,
    destination: Path,
    *,
    timeout: float,
    user_agent: str,
) -> None:
    request = Request(
        url,
        headers={"Accept": "application/octet-stream", "User-Agent": user_agent},
    )
    try:
        with urlopen(request, timeout=timeout) as response, destination.open("wb") as stream:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                stream.write(chunk)
    except HTTPError as error:
        raise SramError(f"download failed with HTTP {error.code}{_error_body(error)}") from error
    except (URLError, socket.timeout, TimeoutError, OSError) as error:
        raise SramError(f"download failed: {error}") from error


def download_artifact(
    urls: Iterable[str],
    destination: Path,
    expected_sha256: str,
    *,
    timeout: float,
    user_agent: str,
    force: bool = False,
) -> bool:
    """Download, verify, and atomically install an artifact.

    Returns False when an existing file already has the requested digest.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        if destination.is_file() and sha256_file(destination) == expected_sha256:
            return False
        raise SramError(
            f"refusing to overwrite existing file with a different digest: {destination}"
        )

    errors: list[str] = []
    unique_urls = list(dict.fromkeys(urls))
    for url in unique_urls:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{destination.name}.",
                suffix=".part",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            _download_once(url, temporary_path, timeout=timeout, user_agent=user_agent)
            actual_sha256 = sha256_file(temporary_path)
            if actual_sha256 != expected_sha256:
                raise SramError(
                    f"SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
                )
            os.replace(temporary_path, destination)
            return True
        except (SramError, OSError) as error:
            errors.append(f"{url}: {error}")
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    joined = "\n  ".join(errors)
    raise SramError(f"all download URLs failed:\n  {joined}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and download an SRAM PDK package from ECOS Factory."
    )
    parser.add_argument("--words", type=int, default=2048, help="memory depth (default: 2048)")
    parser.add_argument("--bits", type=int, default=32, help="data width (default: 32)")
    parser.add_argument("--mux", type=int, default=8, help="column mux: 4, 8, 16, or 32")
    parser.add_argument("--vt", type=int, default=0, help="VT option: 0, 2, or 5")
    parser.add_argument(
        "--low-power",
        "--lowPower",
        type=int,
        default=0,
        dest="low_power",
        help="low-power option: 0 or 2",
    )
    parser.add_argument(
        "--redundancy", type=int, default=0, help="repair option: 0 or 3"
    )
    parser.add_argument(
        "--word-write",
        "--wordWrite",
        type=int,
        default=0,
        dest="word_write",
        help="write mode: 0 or 1",
    )
    parser.add_argument(
        "--bus-format",
        "--busFormat",
        type=int,
        default=1,
        dest="bus_format",
        help="bus format: 0 or 1",
    )
    parser.add_argument(
        "--ring", choices=RINGS, default="ringless", help="ring option (default: ringless)"
    )
    parser.add_argument(
        "--corner",
        choices=PVT_CORNERS,
        default="TT1P2V25CCTYP",
        help="PVT corner used for preview (default: TT1P2V25CCTYP)",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"ECOS Factory base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="directory for the downloaded tar.gz (default: current directory)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="call /preview and print its JSON without downloading",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing artifact after verifying the new download",
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="HTTP timeout in seconds (default: 60)"
    )
    parser.add_argument(
        "--user-agent", default=DEFAULT_USER_AGENT, help="HTTP User-Agent header"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.timeout <= 0:
        print("error: --timeout must be greater than zero", file=sys.stderr)
        return 2

    payload = build_payload(args)
    try:
        validate_config(payload)
        endpoint = "preview" if args.preview else "generate"
        response = post_json(
            f"{args.base_url.rstrip('/')}/api/ip/sram/{endpoint}",
            payload,
            timeout=args.timeout,
            user_agent=args.user_agent,
        )
        print(json.dumps(response, ensure_ascii=False, indent=2))

        if args.preview:
            if response.get("ok") is not True:
                raise SramError("preview request was rejected")
            return 0

        download_url, mirror_url, asset_name, expected_sha256 = extract_artifact(response)
        destination = args.output_dir / asset_name
        urls = [download_url]
        if mirror_url:
            urls.append(mirror_url)
        installed = download_artifact(
            urls,
            destination,
            expected_sha256,
            timeout=args.timeout,
            user_agent=args.user_agent,
            force=args.force,
        )
        if installed:
            print(f"Downloaded and verified: {destination}")
        else:
            print(f"Already verified, skipped download: {destination}")
        print(f"SHA-256: {expected_sha256}")
        return 0
    except SramError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
