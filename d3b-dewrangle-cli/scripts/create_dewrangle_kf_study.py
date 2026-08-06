"""
Create a new Kids First study in Dewrangle and save its global-descriptors report to the database.

This script is specifically for Kids First / INCLUDE studies where a real study entity
must be created in Dewrangle. For D3b-managed projects,
study ID minting is handled via org_globalids_mint.py without creating a real study.

Workflow:
  1. Check if the study name already exists in Dewrangle.
  2. If it exists in Dewrangle but not in the DB, download the report and persist it.
  3. If it does not exist in Dewrangle, create the study, download the report,
     inject studyGlobalId and studyName, and persist to the database.
"""

import sys
from pathlib import Path

# Ensure project root is on path for src/ imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

from src.dewrangle_client import (
    create_kf_study,
    download_created_study_report,
    find_study_by_name,
)
from src.db_utils import (
    get_db_config,
    connect_to_database,
    check_study_exists,
    save_dewrangle_ids,
)


# ======================================
# CLI
# ======================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a Dewrangle study and save its report to the warehouse."
    )
    parser.add_argument(
        "--env",
        choices=["prod", "qa"],
        help="Environment to use (prod or qa). Determines default schema and organization_id if not set explicitly.",
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
        help="Dewrangle Organization ID. Overrides --env default if provided.",
    )
    parser.add_argument(
        "--study-name",
        required=True,
        help="Name of the study to create in Dewrangle.",
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Optional output directory for downloaded CSV",
    )

    args = parser.parse_args()

    # Resolve organization_id based on env if not explicitly provided
    if args.organization_id:
        org_message = f"🛠️ Using custom organization_id: {args.organization_id}"
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

    args.org_message = org_message
    return args


# ======================================
# Main Flow
# ======================================
def main():
    args = parse_args()
    print(args.org_message)

    env_type = args.env.lower()
    database_type = args.db.lower()
    db_config = get_db_config(database_type)

    # Connect to DB
    conn = connect_to_database(
        db_host=db_config["db_host"],
        db_name=db_config["db_name"],
        db_user=db_config["db_user"],
        db_port=db_config["db_port"],
        db_password=db_config["db_password"],
    )

    try:
        dewrangle_ids_config = db_config[env_type]["dewrangle_ids"]
        schema_name = dewrangle_ids_config["schema"]
        table_name = dewrangle_ids_config["table"]

        # Step 1: Check if study already exists in Dewrangle
        study_result = find_study_by_name(args.organization_id, args.study_name)

        if study_result:
            # Step 2: Check if study already exists in DB
            if check_study_exists(
                conn, schema_name, table_name, args.study_name
            ):
                print(
                    f"✅ Study '{args.study_name}' also exists in the database."
                )
                return

            print(
                f"📥 Study '{args.study_name}' found in Dewrangle but not in DB. Downloading report..."
            )
        else:
            # Step 3: Create study in Dewrangle
            print(
                f"🔨 Study '{args.study_name}' not found in Dewrangle. Creating..."
            )
            study_result = create_kf_study(
                args.organization_id, args.study_name
            )

        # # Step 4: Download and augment report
        study_report = download_created_study_report(
            study_result, output_dir=args.output_dir
        )

        # Step 5: Save to database
        print("🗂️ Saving study report to DB...")
        save_dewrangle_ids(conn, dewrangle_ids_config, study_report)

        print("🎉 Done!")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
