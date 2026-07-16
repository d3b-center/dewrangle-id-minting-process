"""
Mint new organization-level Dewrangle IDs from a manifest and save them into the database.

Required columns in manifest:
- fhirResourceType
- descriptor
- descriptorState

Optional columns (required when --save-dt-record is set):
- study_id
- file_name
- dt_id
"""

import sys
from pathlib import Path

# Ensure project root is on path for src/ imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

import pandas as pd

from src.dewrangle_client import (
    upload_org_file,
    create_org_global_ids,
    download_job_report,
)
from src.db_utils import (
    get_db_config,
    connect_to_database,
    check_db_records_exist,
    save_dewrangle_ids,
    save_data_transfer_mapping,
)
from psycopg2.errors import UndefinedTable
import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


# ======================================
# CLI
# ======================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Mint org-level global IDs from a manifest and persist to the warehouse."
    )
    parser.add_argument(
        "--env",
        choices=["prod", "qa"],
        help="Environment to use (prod or qa). Determines default schema and organization_id if not set explicitly."
    )
    parser.add_argument(
        "--db",
        required=True,
        choices=["d3b", "dcc"],
        help="Database warehouse type (d3b or dcc).",
    )
    parser.add_argument(
        "--organization_id",
        default=None,
        help="Dewrangle Organization ID. Overrides --env default if provided."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        help="Path to input manifest CSV file."
    )
    parser.add_argument(
        "--save-dt-record",
        action="store_true",
        help="If set, save data transfer mapping record to DWH."
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Optional output directory for downloaded CSV"
    )
    parser.add_argument(
        "--create-dewrangle-ids-table",
        action="store_true",
        help="""
            If set, create the Dewrangle IDs table in DWH. Note that this
            should only be done once, and the table should already exist for
            subsequent runs. This flag should be used with caution; creating the
            new empty table may result in accidentally duplicating descriptors
            if the table is created after some descriptors have already had
            global IDs minted.
            """
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="If set, print verbose logs."
    )

    args = parser.parse_args()

    # Resolve organization_id based on env if not explicitly provided
    if args.organization_id:
        org_message = f"🛠️ Using custom organization_id: {args.organization_id}"
    elif args.env == "prod":
        args.organization_id = "T3JnYW5pemF0aW9uOmNsZHN4MzRrbjAwMTRnMGVzY3JndzUzYWQ="
        org_message = "🚀 Using Kids First prod Dewrangle organization for ID minting"
    elif args.env == "qa":
        args.organization_id = "T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA="
        org_message = "🧪 Using test-dewrangle-ids organization for ID minting"
    else:
        parser.error("Either --organization_id must be set or --env must be 'prod' or 'qa'.")

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

    manifest_path = Path(args.manifest).resolve()

    # --- Step 1: Read and validate manifest ---
    manifest_df = pd.read_csv(manifest_path)
    required_columns = ["fhirResourceType", "descriptor", "descriptorState"]
    missing_columns = [col for col in required_columns if col not in manifest_df.columns]
    if missing_columns:
        raise ValueError(f"Manifest is missing required columns: {missing_columns}")

    if args.save_dt_record:
        plus_columns = ["study_id", "file_name", "dt_id"]
        missing = [col for col in plus_columns if col not in manifest_df.columns]
        if missing:
            raise ValueError(f"Manifest missing columns for saving DT records: {missing}")

    logger.info("✅ Manifest read successfully with %d rows.", manifest_df.shape[0])

    # --- Step 2: Connect to DB ---
    conn = connect_to_database(
        db_host=db_config["db_host"],
        db_name=db_config["db_name"],
        db_user=db_config["db_user"],
        db_port=db_config["db_port"],
        db_password=db_config["db_password"],
    )

    try:
        dewrangle_ids_config = db_config[env_type]["dewrangle_ids"]
        # --- Step 3: Check if descriptors already exist ---
        try:
            logger.debug("Checking for existing descriptors in %s.%s..." % (dewrangle_ids_config["schema"], dewrangle_ids_config["table"]))
            existing_rows = check_db_records_exist(
                conn,
                schema_name=dewrangle_ids_config["schema"],
                table_name=dewrangle_ids_config["table"],
                df=manifest_df,
                output_dir=args.output_dir,
            )
        except (UndefinedTable, pd.io.sql.DatabaseError) as e:
            if "relation" in str(e) and "does not exist" in str(e):
                if args.create_dewrangle_ids_table:
                    logger.warning("⚠️ Dewrangle IDs table does not exist.")
                    conn.rollback()  # Rollback the transaction to clear the error state
                    existing_rows = pd.DataFrame()  # No existing rows since table does not exist
                else:
                    logger.exception("❌ Dewrangle IDs table does not exist. Use --create-dewrangle-ids-table to create it, or ensure the table exists before running this script.", exc_info=True)
                    sys.exit(1)
            else:
                logger.exception("❌ An unexpected DatabaseError occurred", exc_info=True)
        except Exception as e:
            logger.exception("❌ Error checking for existing descriptors: %s", e)
            sys.exit(1)

        if not existing_rows.empty:
            logger.error("❌ Aborting to avoid duplicates. Please remove the duplicate descriptors and try again.")
            sys.exit(1)
        # --- Step 4: Upload file manifest ---
        file_id = upload_org_file(args.organization_id, manifest_path)

        # --- Step 5: Create org global IDs ---
        job_id = create_org_global_ids(
            organization_id=args.organization_id,
            file_id=file_id
        )

        # --- Step 6: Download job global IDs report ---
        filepath = download_job_report(
            organization_id=args.organization_id,
            job_id=job_id,
            output_dir=args.output_dir,
        )

        # --- Step 7: Save dewrangle IDs to warehouse ---
        logger.info("🗂️ Saving dewrangle IDs report to DB...")
        save_dewrangle_ids(conn, filepath, dewrangle_ids_config)

        # --- Step 8: Optionally save Data Transfer mapping ---
        if args.save_dt_record:
            logger.info("🗂️ Saving Data Transfer Records to DB...")
            data_transfer_mapping_config = db_config[env_type]["data_transfer_file_mapping"]
            save_data_transfer_mapping(conn, filepath, manifest_df, data_transfer_mapping_config)
    except Exception as e:
        logger.exception("❌ Error occurred: %s", e)
        sys.exit(1)
    finally:
        conn.close()

    logger.info("🎉 All completed!")


if __name__ == "__main__":
    main()
