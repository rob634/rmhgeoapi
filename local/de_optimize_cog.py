#!/usr/bin/env python3
"""
De-optimize COG to Regular GeoTIFF for Testing

Converts a Cloud Optimized GeoTIFF (COG) to a standard (non-optimized) GeoTIFF
for testing the raster pipeline's ability to convert to COG.

Author: Robert and Geospatial Claude Legion
Date: 8 OCT 2025
"""

import sys


def de_optimize_cog(input_path: str, output_path: str) -> None:
    """
    Convert COG to regular GeoTIFF (remove optimizations).

    Args:
        input_path: Path to input COG file
        output_path: Path to output regular GeoTIFF
    """
    try:
        import rasterio
        from rasterio.shutil import copy
    except ImportError as e:
        print(f"ERROR: Failed to import rasterio: {e}", file=sys.stderr)
        print("This script must run in an environment with rasterio installed.", file=sys.stderr)
        sys.exit(1)

    print(f"Reading COG: {input_path}")

    with rasterio.open(input_path) as src:
        print(f"  CRS: {src.crs}")
        print(f"  Shape: {src.shape}")
        print(f"  Bands: {src.count}")
        print(f"  Dtype: {src.dtypes[0]}")
        print(f"  Bounds: {src.bounds}")
        print(f"  Transform: {src.transform}")

        # Get source metadata
        profile = src.profile.copy()

        # Remove COG optimizations
        profile.update({
            'tiled': False,          # Remove internal tiling
            'compress': None,        # Remove compression
            'interleave': 'band',    # Band interleaving (not pixel)
            'blockxsize': None,      # Remove block structure
            'blockysize': None,
        })

        # Remove COG-specific profile keys if present
        profile.pop('BIGTIFF', None)
        profile.pop('COPY_SRC_OVERVIEWS', None)

        print(f"\nWriting regular GeoTIFF: {output_path}")
        print(f"  Tiled: {profile.get('tiled', False)}")
        print(f"  Compression: {profile.get('compress', 'None')}")
        print(f"  Interleave: {profile.get('interleave', 'band')}")

        # Write as regular GeoTIFF
        with rasterio.open(output_path, 'w', **profile) as dst:
            for band_idx in range(1, src.count + 1):
                data = src.read(band_idx)
                dst.write(data, band_idx)

    print(f"\n✅ Successfully created regular GeoTIFF: {output_path}")


if __name__ == "__main__":
    import os

    # Input COG file
    input_cog = "local/dctest3_R1C2_cog.tif"

    # Output regular GeoTIFF
    output_regular = "local/dctest3_R1C2_regular.tif"

    if not os.path.exists(input_cog):
        print(f"ERROR: Input file not found: {input_cog}", file=sys.stderr)
        sys.exit(1)

    de_optimize_cog(input_cog, output_regular)

    # Display file sizes
    import os
    input_size = os.path.getsize(input_cog)
    output_size = os.path.getsize(output_regular)

    print(f"\nFile Size Comparison:")
    print(f"  COG (optimized):       {input_size:,} bytes ({input_size / 1024:.1f} KB)")
    print(f"  Regular (de-optimized): {output_size:,} bytes ({output_size / 1024:.1f} KB)")
    print(f"  Difference:            {output_size - input_size:,} bytes ({(output_size - input_size) / 1024:.1f} KB)")

    # Try to validate COG structure (will fail for regular GeoTIFF)
    print("\nValidating COG structure:")
    try:
        from rio_cogeo.cogeo import cog_validate
        is_valid, errors, warnings = cog_validate(output_regular)
        if is_valid:
            print(f"  ⚠️  UNEXPECTED: {output_regular} is still a valid COG!")
        else:
            print(f"  ✅ EXPECTED: {output_regular} is NOT a valid COG")
            if errors:
                print(f"  Errors: {errors}")
    except ImportError:
        print("  (rio-cogeo not available for validation - skipping)")
