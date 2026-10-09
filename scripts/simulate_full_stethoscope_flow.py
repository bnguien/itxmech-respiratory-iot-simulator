"""
Full end-to-end stethoscope flow simulation script.

This script exercises the complete firmware upload flow without MQTT listen mode —
it runs immediately using the provided visit ID and WAV file.

Usage:
    python scripts/simulate_full_stethoscope_flow.py \\
        --visit-id <UUID> \\
        --wav /path/to/test-16k-mono.wav

Steps:
    [1/5] Validating WAV
    [2/5] Requesting signed upload URL
    [3/5] Uploading WAV to Supabase Storage
    [4/5] Completing recording
    [5/5] Done

Secrets and signed URL tokens are never printed in full.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import settings
from common.http_client import (
    WebClientError,
    complete_recording,
    request_upload_url,
    upload_wav_to_storage,
)
from common.models import utc_now
from common.wav_utils import WavValidationError, validate_wav

# Use a clean, readable format for this script's output
logging.basicConfig(
    level=logging.WARNING,  # Suppress noisy library logs; we print our own steps
    format="%(message)s",
)
logger = logging.getLogger(__name__)

_DIVIDER = "─" * 60


def _print_header(visit_id: str, wav_path: Path) -> None:
    print()
    print(_DIVIDER)
    print("  RespiCare Stethoscope Full-Flow Simulator")
    print(_DIVIDER)
    print(f"  Device ID  : {settings.stethoscope_device_id}")
    print(f"  Visit ID   : {visit_id}")
    print(f"  WAV file   : {wav_path}")
    print(f"  Web URL    : {settings.web_base_url}")
    print(f"  Started    : {utc_now()}")
    print(_DIVIDER)
    print()


def _step(n: int, total: int, description: str) -> None:
    print(f"  [{n}/{total}] {description}")


def _ok(message: str) -> None:
    print(f"         ✓  {message}")


def _fail(message: str) -> None:
    print(f"         ✗  {message}", file=sys.stderr)


def _safe_url_snippet(url: str, max_chars: int = 55) -> str:
    return url[:max_chars] + "…" if len(url) > max_chars else url


def run_flow(visit_id: str, wav_path: Path) -> bool:
    """
    Execute all five steps of the full stethoscope upload flow.
    Returns True on success, False on failure.
    """
    _print_header(visit_id, wav_path)
    total_steps = 5

    # ----------------------------------------------------------------
    # Step 1: Validate WAV
    # ----------------------------------------------------------------
    _step(1, total_steps, "Validating WAV file")
    try:
        meta = validate_wav(wav_path)
        _ok(
            f"{meta.path.name}  |  {meta.channels}ch  "
            f"{meta.sample_rate} Hz  {meta.sample_width_bits}-bit  "
            f"{meta.duration_seconds:.1f}s"
        )
    except (FileNotFoundError, WavValidationError) as exc:
        _fail(str(exc))
        return False

    print()

    # ----------------------------------------------------------------
    # Step 2: Request signed upload URL
    # ----------------------------------------------------------------
    _step(2, total_steps, "Requesting signed upload URL from web backend")
    try:
        t0 = time.monotonic()
        upload_resp = request_upload_url(visit_id)
        elapsed = time.monotonic() - t0
        _ok(f"Recording ID : {upload_resp.recording_id}")
        _ok(f"Upload URL   : {_safe_url_snippet(upload_resp.upload_url)}")
        _ok(f"Latency      : {elapsed * 1000:.0f} ms")
    except (WebClientError, Exception) as exc:
        _fail(f"Upload URL request failed: {exc}")
        return False

    recording_id = upload_resp.recording_id
    print()

    # ----------------------------------------------------------------
    # Step 3: Upload WAV to Supabase Storage
    # ----------------------------------------------------------------
    _step(3, total_steps, "Uploading WAV to Supabase Storage")
    file_size = wav_path.stat().st_size
    try:
        t0 = time.monotonic()
        upload_wav_to_storage(upload_resp.upload_url, wav_path)
        elapsed = time.monotonic() - t0
        _ok(f"Uploaded {file_size:,} bytes in {elapsed:.2f}s")
    except (WebClientError, Exception) as exc:
        _fail(f"WAV upload failed: {exc}")
        return False

    print()

    # ----------------------------------------------------------------
    # Step 4: Complete recording
    # ----------------------------------------------------------------
    _step(4, total_steps, "Calling recording complete endpoint")
    try:
        t0 = time.monotonic()
        complete_recording(recording_id)
        elapsed = time.monotonic() - t0
        _ok(f"Recording '{recording_id}' marked complete ({elapsed * 1000:.0f} ms)")
        _ok("Web backend will now trigger AI analysis automatically.")
    except (WebClientError, Exception) as exc:
        _fail(f"Complete request failed: {exc}")
        return False

    print()

    # ----------------------------------------------------------------
    # Step 5: Done
    # ----------------------------------------------------------------
    _step(5, total_steps, "Done")
    print()
    print(_DIVIDER)
    print("  ✓  Full flow completed successfully.")
    print(f"     Visit ID     : {visit_id}")
    print(f"     Recording ID : {recording_id}")
    print(_DIVIDER)
    print()
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full RespiCare stethoscope upload flow.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--visit-id",
        metavar="UUID",
        required=True,
        help="Visit UUID to simulate.",
    )
    parser.add_argument(
        "--wav",
        metavar="PATH",
        help="Path to the WAV file to upload.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Resolve WAV path: CLI > config default
    wav_str = args.wav or (str(settings.default_wav_path) if settings.default_wav_path else None)
    if not wav_str:
        print(
            "Error: no WAV file specified. "
            "Use --wav /path/to/file.wav or set DEFAULT_WAV_PATH in .env",
            file=sys.stderr,
        )
        sys.exit(1)

    wav_path = Path(wav_str)
    success = run_flow(visit_id=args.visit_id, wav_path=wav_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
