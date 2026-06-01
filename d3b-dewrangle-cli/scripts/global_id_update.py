"""
Update (upsert) specific Dewrangle global ID records from a manifest.

Required columns in manifest:
- globalId
- fhirResourceType
- descriptor
- descriptorState

Optional columns (to bring the ID into a specific study):
- studyGlobalId
- studyName

Workflow:
  1. Upload the manifest and trigger globalIdentifierUpsert in Dewrangle.
  2. Download the full organization global identifiers.
  3. Filter for the globalIds present in the manifest.
  4. Delete existing DB records for those globalIds.
  5. Insert the downloaded records into the DB.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

import pandas as pd

from src.dewrangle_client import (
    update_org_global_ids,
    download_org_global_identifiers,
)
from src.db_utils import (
    get_db_config,
    connect_to_database,
    get_table_columns,
    delete_db_records_by_global_ids,
    save_df_to_db,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Update specific Dewrangle global ID records from a manifest."
    )
    parser.add_argument(
        "--env",
        choices=["prod", "qa"],
        required=True,
        help="Environment (prod or qa). Determines default organization_id if not set explicitly."
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
        help="Path to the global ID update manifest CSV."
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Optional output directory for downloaded CSV"
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
        parser.error("Either --organization_id must be set or --env must be 'prod' or 'qa'.")

    args.org_message = org_message
    return args


def main():
    args = parse_args()
    
    env_type = args.env.lower()
    database_type = args.db.lower()
    db_config = get_db_config(database_type)

    manifest_path = Path(args.manifest).resolve()

    # Read and validate manifest
    manifest_df = pd.read_csv(manifest_path)
    required_columns = ["globalId", "fhirResourceType", "descriptor", "descriptorState"]
    missing_columns = [col for col in required_columns if col not in manifest_df.columns]
    if missing_columns:
        raise ValueError(f"Manifest is missing required columns: {missing_columns}")

    print(f"✅ Manifest read successfully with {manifest_df.shape[0]} rows.")

    # Extract list of globalIds to sync later
    target_global_ids = list(manifest_df["globalId"].dropna().astype(str).unique())

    # Connect to DB
    conn = connect_to_database(
        db_host=db_config["db_host"],
        db_name=db_config["db_name"],
        db_user=db_config["db_user"],
        db_port=db_config["db_port"],
        db_password=db_config["db_password"],
    )

    try:
        # Step 1: Upload manifest and trigger upsert in Dewrangle
        print("🔄 Updating Dewrangle global IDs...")
        update_org_global_ids(
            organization_id=args.organization_id,
            manifest_path=manifest_path,
            output_dir=args.output_dir,
        )

        # Step 2: Download filtered org global identifiers
        print("📥 Downloading filtered organization global identifiers...")
        full_report_path = download_org_global_identifiers(
            organization_id=args.organization_id,
            global_id=target_global_ids,
            output_dir=args.output_dir,
        )

        filtered_df = pd.read_csv(full_report_path, keep_default_na=False)

        if filtered_df.empty:
            print("⚠️ No matching records found in the downloaded report. Nothing to update in DB.")
            return

        print(f"🎯 Filtered {len(filtered_df)} records matching the manifest globalIds.")

        # Step 3: Replace records in DB
        dewrangle_ids_config = db_config[env_type]["dewrangle_ids"]
        schema_name = dewrangle_ids_config["schema"]
        table_name = dewrangle_ids_config["table"]
        primary_key_cols = dewrangle_ids_config["primary_key_cols"]

        # 4a. Delete existing records for the target globalIds
        delete_db_records_by_global_ids(conn, schema_name, table_name, target_global_ids)

        # 4b. Align DataFrame columns to the existing table schema
        table_cols = get_table_columns(conn, schema_name, table_name)
        if table_cols:
            # Keep only columns that exist in the table; add missing ones as empty strings
            aligned_df = pd.DataFrame()
            for col in table_cols:
                if col in filtered_df.columns:
                    aligned_df[col] = filtered_df[col]
                else:
                    aligned_df[col] = ""
            filtered_df = aligned_df

        # 4c. Insert the downloaded records
        print("🗂️ Inserting updated records into DB...")
        save_df_to_db(
            conn,
            filtered_df,
            schema_name,
            table_name,
            primary_key_cols,
            on_conflict="nothing",
        )

    finally:
        conn.close()

    print("🎉 Global ID update completed!")


if __name__ == "__main__":
    main()
