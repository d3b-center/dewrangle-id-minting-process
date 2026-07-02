import sys
from pathlib import Path

# Ensure project root is on path for src/ imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import pandas as pd
import logging
from src.env_config import config
from src.db_utils import (
    get_db_config,
    connect_to_database,
    get_table_columns,
    check_db_records_exist,
    save_df_to_db,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


# ======================================
# Load Correct Config
# ======================================
def get_source_metadata_config(
    db_config: dict,
    env_type: str,
    source_type: str,
):
    """
    Return source metadata table configuration.
    """
    if source_type == "study":
        source_key = "source_study_metadata"
    elif source_type == "sample":
        source_key = "source_sample_metadata"
    else:
        raise ValueError(f"Unsupported source_type: {source_type}")
    
    return db_config[env_type][source_key]

# ======================================
# VALIDATION
# ======================================
def validate_manifest(df, REQUIRED_FIELDS):
    # Required fields
    missing = [col for col in REQUIRED_FIELDS if col not in df.columns]
    if missing:
        raise ValueError(f"❌ Input manifest missing required columns: {missing}")

    # Duplicate check (FAIL if exist)
    dup_df = df[df.duplicated(subset=REQUIRED_FIELDS, keep=False)]

    if not dup_df.empty:
        dup_keys = dup_df[REQUIRED_FIELDS].drop_duplicates()

        raise ValueError(
            "❌ Duplicate records found based on required fields:\n"
            f"{dup_keys.to_string(index=False)}"
        )

# ======================================
# MAIN
# ======================================
def main():
    parser = argparse.ArgumentParser(description="Insert manifest into data warehouse")
    parser.add_argument("--manifest", required=True, help="Path to manifest CSV")
    parser.add_argument(
        "--env",
        choices=["prod", "qa"],
        help="Environment to use (prod or qa)."
    )
    parser.add_argument(
        "--source_type",
        required=True,
        choices=["study", "sample"],
        help="Input source metadata type, study or sample.",
    )
    parser.add_argument(
        "--db",
        required=True,
        choices=["d3b", "dcc"],
        help="Database warehouse type (d3b or dcc). Determines which warehouse connection and source metadata tables are used.",
    )
    args = parser.parse_args()

    env_type = args.env.lower()
    source_type = args.source_type.lower()
    database_type = args.db.lower()

    # ======================================
    # ENV CONFIG
    # ======================================
    db_config = get_db_config(database_type)
    db_host = db_config["db_host"]
    db_name = db_config["db_name"]
    db_user = db_config["db_user"]
    db_port = db_config["db_port"]
    db_password = db_config["db_password"]

    source_config = get_source_metadata_config(
        db_config=db_config,
        env_type=env_type,
        source_type=source_type,
    )

    source_schema = source_config["schema"]
    source_table = source_config["table"]
    REQUIRED_FIELDS = source_config["primary_key_cols"]

    # Load CSV
    df = pd.read_csv(args.manifest)

    # Validate required fields + duplicate check
    validate_manifest(df, REQUIRED_FIELDS)

    # Connect to DB
    conn = connect_to_database(db_host, db_name, db_user, db_port, db_password)

    # Get DB table columns
    table_columns = get_table_columns(conn, source_schema, source_table)

    # Report unmatched columns (manifest - table)
    unmatched = [col for col in df.columns if col not in table_columns]

    if unmatched:
        logger.warning(
            f"⚠️ Columns in manifest but NOT in {source_schema}.{source_table}: "
            f"{unmatched}"
        )

    # Keep only matching columns
    df = df[[col for col in df.columns if col in table_columns]]

    # Insert data into the DWH
    save_df_to_db(conn, df, source_schema, source_table, REQUIRED_FIELDS)

    # Generate manifest for dewrangle ID minting
    rows = []
    if source_type == "study":
        study_names = set(df['study_name'].dropna())
        for name in study_names:
            rows.append({
                "fhirResourceType": "ResearchStudy",
                "descriptor": str(name),
                "descriptorState": "ACTIVE"
            })

    elif source_type == "sample":
        df_nonan = df.dropna(subset=['case_id', 'aliquot_id'])
        patient_ids = set(zip(df_nonan['study_id'], df_nonan['case_id']))
        specimen_ids = set(zip(df_nonan['study_id'], df_nonan['aliquot_id']))

        # Add Patient resources
        for study_id, pid in patient_ids:
            rows.append({
                "fhirResourceType": "Patient",
                "descriptor": f"{pid};{study_id}",
                "descriptorState": "ACTIVE"
            })
        # Add Specimen resources
        for study_id, sid in specimen_ids:
            rows.append({
                "fhirResourceType": "Specimen",
                "descriptor": f"{sid};{study_id}",
                "descriptorState": "ACTIVE"
            })
    else:
        raise ValueError(f"❌ Invalid type: {source_type}")
    
    output_df = pd.DataFrame(rows)

    # --- Check if descriptors already exist ---
    existing_rows = check_db_records_exist(
        conn,
        schema_name=db_config[env_type]["dewrangle_ids"]["schema"],
        table_name=db_config[env_type]["dewrangle_ids"]["table"],
        df=output_df,
    )
    if existing_rows is not None and not existing_rows.empty:
        existing_rows.to_csv(f"{source_type}_metadata_already_minted.csv", index=False)
        logger.warning(
            f"⚠️ Found {len(existing_rows)} descriptors already registered. "
            f"See {source_type}_metadata_already_minted.csv"
        )
        mint_df = output_df[~output_df["descriptor"].isin(existing_rows["descriptor"])]
    else:
        mint_df = output_df.copy()
    
    if not mint_df.empty:
        if database_type == "d3b":
            mint_df.to_csv(f"{source_type}_metadata_for_id_minting.csv", index=False)
            logger.info(f"✅ Generated {source_type}_metadata_for_id_minting.csv for dewrangle ID minting.")
        elif database_type == "dcc":
            logger.info(
                f"✅ Successfully loaded the {source_type} metadata into the DCC data warehouse")
        
    else:
        logger.info(f"✅ No new descriptors to mint IDs.")
    
    logger.info(f"🎉 All completed!")

    conn.close()


if __name__ == "__main__":
    main()