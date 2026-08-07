"""
Export Global IDs from Dewrangle and save them into a database or CSV file.

Requires:
- organization_id
"""

import sys
from pathlib import Path

# Ensure project root is on path for src/ imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import logging
import os
import time

from src.db_utils import (
    get_db_config,
    connect_to_database,
    save_dewrangle_ids,
)
from src.dewrangle_client import fetch_globalid_report_df

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


# ======================================
# CLI
# ======================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Export Global IDs from Dewrangle and save them into a database or CSV file."
    )
    parser.add_argument(
        "--env",
        choices=["prod", "qa"],
        help="Environment to use (prod or qa). Determines default schema and organization_id if not set explicitly.",
    )
    parser.add_argument(
        "--db",
        required=False,
        choices=["d3b", "dcc"],
        help="Database warehouse type (d3b or dcc).",
    )
    parser.add_argument(
        "--organization-id",
        default=None,
        required=True,
        help="Dewrangle Organization ID. Overrides --env default if provided.",
    )
    parser.add_argument(
        "--study-id",
        default=None,
        help="Dewrangle Study ID. Overrides --env default if provided.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional output directory for the downloaded CSV",
    )
    parser.add_argument(
        "--download_csv_only",
        action="store_true",
        help="If set, only download the CSV and skip saving to the database.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="If set, print verbose logs."
    )

    args = parser.parse_args()

    if args.organization_id:
        org_message = f"🛠️ Using organization_id: {args.organization_id}"
    elif args.env == "prod":
        args.organization_id = (
            "T3JnYW5pemF0aW9uOmNsZHN4MzRrbjAwMTRnMGVzY3JndzUzYWQ="
        )
        org_message = "🚀 Using Kids First prod Dewrangle organization"
    elif args.env == "qa":
        args.organization_id = (
            "T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA="
        )
        org_message = "🧪 Using test-dewrangle-ids organization"
    else:
        parser.error(
            "Either --organization_id must be set or --env must be 'prod' or 'qa'."
        )

    if args.download_csv_only and not args.output_dir:
        parser.error(
            "If --download_csv_only is set, --output-dir must be provided."
        )

    args.org_message = org_message
    return args


# ======================================
# Main Flow
# ======================================
def main():
    args = parse_args()
    logger.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    logger.info(args.org_message)

    env_type = args.env.lower()
    database_type = args.db.lower()
    db_config = get_db_config(database_type)

    # --- Step 1: get global IDs from Dewrangle ---
    global_id_df = fetch_globalid_report_df(
        organization_id=args.organization_id, study_id=args.study_id
    )

    # -- Step 2: Save global IDs to database ---
    if not args.download_csv_only:
        try:
            conn = connect_to_database(
                db_host=db_config["db_host"],
                db_name=db_config["db_name"],
                db_user=db_config["db_user"],
                db_port=db_config["db_port"],
                db_password=db_config["db_password"],
            )
            dewrangle_ids_config = db_config[env_type]["dewrangle_ids"]

            save_dewrangle_ids(conn, dewrangle_ids_config, df=global_id_df)
        except Exception as e:
            logger.error(f"❌ Error saving global IDs to database: {e}")
            sys.exit(1)
        finally:
            conn.close()

    # -- Step 3: Optionally, save global IDs to CSV ---
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
        os.makedirs(output_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M")
        if args.study_id:
            output_file_path = (
                output_dir
                / f"dewrangle_global_ids_{args.organization_id}_{args.study_id}_{timestamp}.csv"
            )
        else:
            output_file_path = (
                output_dir
                / f"dewrangle_global_ids_{args.organization_id}_{timestamp}.csv"
            )
        global_id_df.to_csv(output_file_path, index=False)
        logger.info(f"✅ Global IDs exported to CSV: {output_file_path}")

    logger.info("✅ Global ID export completed successfully.")


if __name__ == "__main__":
    main()
