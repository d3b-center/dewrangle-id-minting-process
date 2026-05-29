"""
Check (query) a specific Dewrangle global ID and download its record as a CSV.

Requires:
- globalId   (the human-readable global ID to look up)
- organization_id (or --env to use the default)

Output CSV columns:
- globalId
- fhirResourceType
- descriptor
- event
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from src.dewrangle_client import download_org_global_identifiers


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check a specific Dewrangle global ID and download its record."
    )
    parser.add_argument(
        "--env",
        choices=["prod", "qa"],
        help="Environment (prod or qa). Determines default organization_id if not set explicitly."
    )
    parser.add_argument(
        "--organization-id",
        default=None,
        help="Dewrangle Organization ID. Overrides --env default if provided."
    )
    parser.add_argument(
        "--id",
        required=True,
        help="The globalId to look up (e.g. sd-xxxxxx)."
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional output directory for the downloaded CSV"
    )

    args = parser.parse_args()

    if args.organization_id:
        org_message = f"🛠️ Using custom organization_id: {args.organization_id}"
    elif args.env == "prod":
        args.organization_id = "T3JnYW5pemF0aW9uOmNsZHN4MzRrbjAwMTRnMGVzY3JndzUzYWQ="
        org_message = "🚀 Using Kids First prod Dewrangle organization"
    elif args.env == "qa":
        args.organization_id = "T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA="
        org_message = "🧪 Using test-dewrangle-ids organization"
    else:
        parser.error("Either --organization-id must be set or --env must be 'prod' or 'qa'.")

    args.org_message = org_message
    return args


def main():
    args = parse_args()
    print(args.org_message)
    print(f"🔍 Looking up globalId: {args.id}")

    filepath = download_org_global_identifiers(
        organization_id=args.organization_id,
        global_id=args.id,
        output_dir=args.output_dir,
    )

    print(f"✅ Report saved: {filepath}")


if __name__ == "__main__":
    main()
