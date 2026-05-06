import argparse
import sys
import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import OperationalError
import logging
from pprint import pformat
from env_config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)

# ======================================
# ENV CONFIG
# ======================================
db_config = config["db"]["d3b_warehouse"]
db_host = db_config["db_host"]
db_name = db_config["db_name"]
db_user = db_config["db_user"]
db_password = db_config["db_password"]

study_source_schema = db_config["source_study_metadata"]["schema"]
study_source_table = db_config["source_study_metadata"]["table"]
study_required_fields = db_config["source_study_metadata"]["primary_key_cols"]

sample_source_schema = db_config["source_sample_metadata"]["schema"]
sample_source_table = db_config["source_sample_metadata"]["table"]
sample_required_fields = db_config["source_sample_metadata"]["primary_key_cols"]

# ======================================
# Database Helpers
# ======================================
def connect_to_database():
    db_config = {
        "host": db_host,
        "dbname": db_name,
        "user": db_user,
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
    parser.add_argument("--type", required=True, help="manifest type: study or sample", choices=["study", "sample"])

    args = parser.parse_args()
    type = args.type.lower()
    if type == "study":
        REQUIRED_FIELDS = study_required_fields
        source_schema = study_source_schema
        source_table = study_source_table
    else:
        REQUIRED_FIELDS = sample_required_fields
        source_schema = sample_source_schema
        source_table = sample_source_table

    # Load CSV
    df = pd.read_csv(args.manifest)

    # Validate required fields + duplicate check
    validate_manifest(df, REQUIRED_FIELDS)

    # Connect to DB
    conn = connect_to_database()

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
    if type == "study":
        study_names = set(df['study_name'].dropna())
        for name in study_names:
            rows.append({
                "fhirResourceType": "ResearchStudy",
                "descriptor": str(name),
                "descriptorState": "ACTIVE"
            })

    elif type == "sample":
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
        raise ValueError(f"❌ Invalid type: {type}")
    
    # Create DataFrame
    output_df = pd.DataFrame(rows)
    output_df.to_csv(f"{type}_metadata_for_id_minting.csv", index=False)
    logger.info(f"✅ Generated {type}_metadata_for_id_minting.csv for dewrangle ID minting.")

    conn.close()


if __name__ == "__main__":
    main()