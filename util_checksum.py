# ============================================================================
# CLAUDE CONTEXT - STAC-COMPLIANT CHECKSUM UTILITIES
# ============================================================================
# STATUS: Utility - Content integrity using Multihash format
# PURPOSE: Compute STAC file:checksum compliant hashes for blob storage
# CREATED: 21 JAN 2026
# LAST_REVIEWED: 21 JAN 2026
# ============================================================================
"""
STAC-Compliant Checksum Utilities.

Implements file:checksum per STAC file extension specification using
Multihash self-describing format.

Multihash Format:
    [algorithm code (varint)][digest length (varint)][digest bytes]

    SHA-256 example: 1220{64 hex chars}
      - 12 = SHA-256 algorithm code
      - 20 = 32 bytes (0x20 in hex)
      - {digest} = actual SHA-256 hash

Standards:
    - STAC file extension: https://github.com/stac-extensions/file
    - Multihash spec: https://multiformats.io/multihash/

Usage:
    from util_checksum import compute_multihash, verify_multihash

    # Compute checksum (returns STAC-compliant multihash string)
    checksum = compute_multihash(cog_bytes)
    # Returns: "1220a1b2c3d4..."

    # Verify checksum
    is_valid = verify_multihash(cog_bytes, checksum)

Performance:
    SHA-256 throughput: ~200 MB/s on modern CPU
    500 MB file: ~2.5 seconds (CPU only, no I/O if bytes in memory)

Exports:
    compute_multihash: Compute SHA-256 multihash from bytes
    verify_multihash: Verify bytes match expected multihash
    parse_multihash: Extract algorithm and digest from multihash
    MULTIHASH_SHA2_256: Algorithm code constant
"""

import hashlib
import time
from typing import Union, Tuple, Optional

# Logger setup
from util_logger import LoggerFactory, ComponentType
logger = LoggerFactory.create_logger(ComponentType.SERVICE, "checksum")


# ============================================================================
# MULTIHASH ALGORITHM CODES (from multiformats spec)
# ============================================================================

MULTIHASH_SHA2_256 = 0x12  # SHA-256: code 0x12, 32-byte digest
MULTIHASH_SHA2_512 = 0x13  # SHA-512: code 0x13, 64-byte digest
MULTIHASH_MD5 = 0xd5       # MD5: code 0xd5, 16-byte digest (legacy)

# Algorithm metadata
ALGORITHMS = {
    MULTIHASH_SHA2_256: {'name': 'sha256', 'digest_size': 32},
    MULTIHASH_SHA2_512: {'name': 'sha512', 'digest_size': 64},
    MULTIHASH_MD5: {'name': 'md5', 'digest_size': 16},
}


# ============================================================================
# CORE FUNCTIONS
# ============================================================================

def compute_multihash(
    data: Union[bytes, memoryview],
    algorithm: int = MULTIHASH_SHA2_256,
    log_performance: bool = False
) -> str:
    """
    Compute hash in STAC-compliant Multihash format.

    Args:
        data: Bytes to hash (e.g., COG file content)
        algorithm: Multihash algorithm code (default: SHA-256)
        log_performance: If True, log computation time

    Returns:
        Multihash hex string (e.g., "1220abcd1234...")

    Example:
        >>> checksum = compute_multihash(cog_bytes)
        >>> print(checksum)
        '12209f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08'
    """
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unsupported algorithm code: {algorithm:#x}")

    algo_info = ALGORITHMS[algorithm]
    hash_name = algo_info['name']

    start_time = time.time()

    # Compute digest
    hasher = hashlib.new(hash_name)
    hasher.update(data)
    digest = hasher.digest()

    elapsed = time.time() - start_time

    if log_performance:
        size_mb = len(data) / (1024 * 1024)
        throughput = size_mb / elapsed if elapsed > 0 else 0
        logger.info(
            f"Computed {hash_name.upper()} multihash: "
            f"{size_mb:.1f} MB in {elapsed:.2f}s ({throughput:.0f} MB/s)"
        )

    # Build multihash: [code][length][digest]
    multihash_bytes = bytes([algorithm, len(digest)]) + digest

    return multihash_bytes.hex()


def verify_multihash(data: bytes, expected_hash: str) -> bool:
    """
    Verify data matches expected Multihash.

    Parses the algorithm from the multihash itself (self-describing format).

    Args:
        data: Bytes to verify
        expected_hash: Multihash hex string

    Returns:
        True if hash matches, False otherwise

    Example:
        >>> is_valid = verify_multihash(cog_bytes, stored_checksum)
        >>> if not is_valid:
        ...     raise IntegrityError("File corrupted")
    """
    try:
        # Parse algorithm from expected hash
        algorithm, _ = parse_multihash(expected_hash)

        # Compute hash with same algorithm
        computed = compute_multihash(data, algorithm=algorithm)

        return computed == expected_hash
    except Exception as e:
        logger.warning(f"Multihash verification failed: {e}")
        return False


def parse_multihash(multihash_hex: str) -> Tuple[int, bytes]:
    """
    Parse multihash to extract algorithm code and digest.

    Args:
        multihash_hex: Multihash hex string

    Returns:
        Tuple of (algorithm_code, digest_bytes)

    Raises:
        ValueError: If multihash format is invalid

    Example:
        >>> algo, digest = parse_multihash("1220abcd...")
        >>> print(f"Algorithm: {algo:#x}, Digest: {digest.hex()}")
    """
    try:
        multihash_bytes = bytes.fromhex(multihash_hex)

        if len(multihash_bytes) < 2:
            raise ValueError("Multihash too short")

        algorithm = multihash_bytes[0]
        digest_length = multihash_bytes[1]
        digest = multihash_bytes[2:]

        if len(digest) != digest_length:
            raise ValueError(
                f"Digest length mismatch: expected {digest_length}, got {len(digest)}"
            )

        if algorithm not in ALGORITHMS:
            raise ValueError(f"Unknown algorithm code: {algorithm:#x}")

        return algorithm, digest

    except Exception as e:
        raise ValueError(f"Invalid multihash format: {e}")


def get_algorithm_name(multihash_hex: str) -> str:
    """
    Get human-readable algorithm name from multihash.

    Args:
        multihash_hex: Multihash hex string

    Returns:
        Algorithm name (e.g., "sha256")
    """
    algorithm, _ = parse_multihash(multihash_hex)
    return ALGORITHMS[algorithm]['name']


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def compute_sha256_multihash(data: Union[bytes, memoryview]) -> str:
    """
    Compute SHA-256 multihash (convenience wrapper).

    Args:
        data: Bytes to hash

    Returns:
        SHA-256 multihash hex string
    """
    return compute_multihash(data, algorithm=MULTIHASH_SHA2_256)


def format_checksum_for_stac(multihash_hex: str) -> str:
    """
    Format multihash for STAC file:checksum field.

    Currently just returns the hex string, but could be extended
    to support different encodings (base58, base64) if needed.

    Args:
        multihash_hex: Multihash hex string

    Returns:
        STAC-compliant checksum string
    """
    # STAC file extension specifies lowercase hex
    return multihash_hex.lower()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Core functions
    'compute_multihash',
    'verify_multihash',
    'parse_multihash',
    'get_algorithm_name',

    # Convenience
    'compute_sha256_multihash',
    'format_checksum_for_stac',

    # Constants
    'MULTIHASH_SHA2_256',
    'MULTIHASH_SHA2_512',
    'MULTIHASH_MD5',
    'ALGORITHMS',
]
