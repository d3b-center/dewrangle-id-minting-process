import argparse
import time
import sys
import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import OperationalError
import logging
from typing import List, Optional
from pprint import pformat
from env_config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


# ======================================
# Load Correct Config
# ======================================
def get_db_config(database_type: str):
    """
    Return warehouse config based on project type.
    """
    if database_type == "d3b":
        return config["db"]["d3b_warehouse"]
    if database_type == "dcc":
        return config["db"]["dcc_warehouse"]
    raise ValueError(f"Unsupported database_type: {database_type}")
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
# Database Helpers
# ======================================
def connect_to_database(db_host, db_name, db_user, db_port,db_password):
    db_config = {
        "host": db_host,
        "dbname": db_name,
        "user": db_user,
        "port": db_port,
        "password": db_password,
    }

    # Mask password for display
    display = {
        k: ("*" * len(v) if k == "password" and v else v)
        for k, v in db_config.items()
    }

    if not all(db_config.values()):
        raise ValueError(
            "❌ Not enough inputs to connect to database!\n"
            f"{pformat(display)}"
        )

    try:
        conn = psycopg2.connect(**db_config)
        return conn

    except OperationalError as e:
        raise RuntimeError(
            "❌ Failed to connect to database:\n"
            f"{str(e)}\nConfig: {pformat(display)}"
        )

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
# TABLE METADATA
# ======================================
def get_table_columns(conn, schema_name, table_name):
    sql = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (schema_name, table_name))
        return [row[0] for row in cur.fetchall()]


def check_db_records_exist(
    conn,  # Accept the existing connection
    schema_name: str,
    table_name: str,
    df: pd.DataFrame,
) -> list:
    """
    Check if already registered in the Dewrangle.
    """
    # Extract descriptors from DataFrame to compare
    descriptors_to_check = list(set(df["descriptor"].dropna()))
    if not descriptors_to_check:
        return pd.DataFrame()  # Return empty DataFrame if no descriptors

    descriptors_to_check_string = ", ".join([f"'{descriptor}'" for descriptor in descriptors_to_check])
    query = f"""
        select *
        from {schema_name}.{table_name}
        where descriptor in ({descriptors_to_check_string})
    """
    df_existing_rows = pd.read_sql(query, conn)

    # If matching records exist, return them
    if not df_existing_rows.empty:
        return df_existing_rows
    else:
        return pd.DataFrame()
    
# ======================================
# SAVE TO DB
# ======================================
def save_df_to_db(conn, df, schema_name, table_name, primary_key_cols):
    if df.empty:
        logger.warning(f"⚠️ No valid columns to insert.")
        return

    cur = conn.cursor()

    cols = list(df.columns)
    cols_quoted = [f'"{c}"' for c in cols]
    pk_cols_quoted = [f'"{c}"' for c in primary_key_cols]

    df = df.astype(object).where(pd.notnull(df), None)
    values = df.to_numpy().tolist()

    insert_sql = f"""
        INSERT INTO {schema_name}.{table_name} ({','.join(cols_quoted)})
        VALUES %s
        ON CONFLICT ({', '.join(pk_cols_quoted)}) DO NOTHING;
    """
    try:
        execute_values(cur, insert_sql, values, page_size=1000)
        conn.commit()
        if cur.rowcount == 0:
            logger.warning(f"⚠️ No new rows inserted (all duplicates).")
        else:
            logger.info(f"✅ Insert {cur.rowcount} rows into {schema_name}.{table_name}\n")
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Insert failed: {e}")
        raise

    finally:
        cur.close()

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
        "--db_type",
        required=True,
        choices=["d3b", "dcc"],
        help="Database warehouse type (d3b or dcc). Ddetermines which warehouse connection and source metadata tables are used.",
    )
    args = parser.parse_args()

    env_type = args.env.lower()
    source_type = args.source_type.lower()
    database_type = args.db_type.lower()

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
    conn = connect_to_database(db_host, db_name, db_user,db_port, db_password)

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
        mint_df.to_csv(f"{source_type}_metadata_for_id_minting.csv", index=False)
        logger.info(f"✅ Generated {source_type}_metadata_for_id_minting.csv for dewrangle ID minting.")
    else:
        logger.info(f"✅ No new descriptors to mint IDs.")
    
    logger.info(f"🎉 All completed!")

    conn.close()


if __name__ == "__main__":
    main()