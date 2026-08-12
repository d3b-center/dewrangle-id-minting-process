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
        "--null_handling",
        choices=[
            "error",
            "skip",
            "coerce_to_string",
            "leave_as_null",
        ],
        default="coerce_to_string",
        help="How to handle null values when saving to the database. "
        "'error' will raise an error, 'skip' will skip rows with null values, "
        "'leave_as_null' will leave null values as null,"
        "and 'coerce_to_string' will convert nulls to the string 'null'.",
    )
    parser.add_argument(
        "--null_string",
        default="not in dewrangle",
        help="The string to use for null values when --null_handling is set to 'coerce_to_string'.",
    )
    parser.add_argument(
        "--skip_non_study_global_ids",
        action="store_true",
        help="If set, skip rows where the Global ID does not belong to a study",
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

    if args.null_handling == "error":
        logger.info(
            "Null handling: error (will raise an error if nulls are found)"
        )
    elif args.null_handling == "skip":
        logger.info(
            "Null handling: skip (will skip rows with null descriptors)"
        )
    elif args.null_handling == "coerce_to_string":
        logger.info(
            "Null handling: coerce_to_string (will convert nulls to '%s')"
            % args.null_string
        )
    elif args.null_handling == "leave_as_null":
        logger.info(
            "Null handling: leave_as_null (will leave null values as null)"
        )

    if args.skip_non_study_global_ids:
        logger.info(
            "Skipping non-study global IDs: enabled (rows with non-study global IDs will not be loaded into the database)"
        )

    env_type = args.env.lower()
    database_type = args.db.lower()
    db_config = get_db_config(database_type)

    # --- Step 1: get global IDs from Dewrangle ---
    global_id_df = fetch_globalid_report_df(
        organization_id=args.organization_id, study_id=args.study_id
    )

    # --- Step 2: Optionally filter out non-study global IDs ---

    if args.skip_non_study_global_ids:
        non_study_count = global_id_df[
            global_id_df["studyGlobalId"].isnull()
        ].shape[0]
        if non_study_count > 0:
            logger.warning(
                f"Skipping {non_study_count} rows with non-study global IDs."
            )
            global_id_df = global_id_df.dropna(subset=["studyGlobalId"])

    # --- Step 3: Handle null values based on user preference ---
    if args.null_handling == "error":
        if global_id_df["descriptor"].isnull().any():
            logger.error(
                "Null values found. Exiting due to --null-handling=error."
            )
            sys.exit(1)
    elif args.null_handling == "skip":
        null_row_count = global_id_df.isnull().any(axis=1).sum()
        if null_row_count > 0:
            logger.warning(
                f"Skipping {null_row_count} rows with null values in any column."
            )
            global_id_df = global_id_df.dropna(subset=["descriptor"])
    elif args.null_handling == "coerce_to_string":
        null_row_count = global_id_df.isnull().any(axis=1).sum()
        if null_row_count > 0:
            logger.warning(
                f"Coercing {null_row_count} rows with null values to string '{args.null_string}'."
            )
            global_id_df = global_id_df.fillna(args.null_string)

    # -- Step 4: Save global IDs to database ---
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

    # -- Step 5: Optionally, save global IDs to CSV ---
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
