"""
CBTN ID Minting Preparation
---------
This script prepares input data for Dewrangle ID minting by validating a manifest
and checking existing IDs in the Data Warehouse (DWH). It identifies which records
need new IDs ("to mint"), which already have valid IDs, and which are missing from
the database.
"""

import sys
from pathlib import Path

# Ensure project root is on path for src/ imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import OperationalError
import logging
from pprint import pformat
from src.env_config import config

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

cbtn_schema = db_config["cbtn_samples"]["schema"]
cbtn_specimen_table = db_config["cbtn_samples"]["specimen_table"]
cbtn_participant_table = db_config["cbtn_samples"]["participant_table"]

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

def save_if_not_empty(df, path, columns=None):
    if df is None or df.empty:
        return
    if columns:
        df = df[columns]
    df.to_csv(path, index=False)
    logger.info(f"✅ Saved file: {path}")

def find_missing(input_df, db_df, key_cols, output_name):
    input_keys = set(map(tuple, input_df[key_cols].dropna().astype(str).values))
    db_keys = set(map(tuple, db_df[key_cols].dropna().astype(str).values))
    missing = input_keys - db_keys
    if missing:
        missing_df = pd.DataFrame(list(missing), columns=key_cols)
        save_if_not_empty(missing_df, output_name)

def check_participants(conn, schema, table, df):
    case_ids_df = df[['case_id']].dropna().astype(str).drop_duplicates()

    if case_ids_df.empty:
        logger.warning("⚠️ No valid case_ids found in manifest")
        return pd.DataFrame(), pd.DataFrame()

    case_ids_df.columns = ["research_id"]
    case_ids = case_ids_df['research_id'].tolist()

    sql = f"""
        SELECT research_study_name, research_id, kids_first_participant_id
        FROM {schema}.{table}
        WHERE research_id = ANY(%s::text[])
    """

    db_df = pd.read_sql(sql, conn, params=(case_ids,))

    # Track missing
    find_missing(
        input_df=case_ids_df,
        db_df=db_df,
        key_cols=["research_id"],
        output_name="cbtn_participants_missing_in_dwh.csv"
    )

    # Split
    to_mint = db_df[
        db_df['kids_first_participant_id'].isna() |
        ~db_df['kids_first_participant_id'].str.lower().str.startswith('pt')
    ]

    existing = db_df[
        db_df['kids_first_participant_id'].notna() &
        db_df['kids_first_participant_id'].str.lower().str.startswith('pt')
    ]

    return to_mint, existing

def check_specimens(conn, schema, table, df):
    pairs_df = df[['sample_id', 'aliquot_id']].dropna().drop_duplicates().copy()

    if pairs_df.empty:
        logger.warning("⚠️ No valid specimen pairs found in manifest")
        return pd.DataFrame(), pd.DataFrame()

    # DWH aliquot_id is bigint, so manifest values must be numeric to match.
    # Non-numeric text aliquot_ids cannot exist in DWH.
    pairs_df['aliquot_id_numeric'] = pd.to_numeric(pairs_df['aliquot_id'], errors='coerce')

    invalid_mask = pairs_df['aliquot_id_numeric'].isna()
    invalid_pairs_df = pairs_df.loc[invalid_mask, ['sample_id', 'aliquot_id']].copy()

    if not invalid_pairs_df.empty:
        logger.warning(
            f"⚠️ {len(invalid_pairs_df)} manifest aliquot_id values are not numeric "
            "and cannot exist in DWH aliquot_id (bigint)"
        )
        save_if_not_empty(invalid_pairs_df, "cbtn_specimens_non_numeric_aliquot_id.csv")

    valid_pairs_df = pairs_df.loc[~invalid_mask, ['sample_id', 'aliquot_id', 'aliquot_id_numeric']].copy()

    if valid_pairs_df.empty:
        logger.warning("⚠️ No valid numeric specimen pairs found in manifest")
        return pd.DataFrame(), pd.DataFrame()

    sample_ids = valid_pairs_df['sample_id'].astype(str).tolist()
    aliquot_ids = valid_pairs_df['aliquot_id_numeric'].astype(int).tolist()

    sql = f"""
        SELECT research_study_name, sample_id, aliquot_id, kf_biospecimen_id
        FROM {schema}.{table}
        WHERE (sample_id, aliquot_id) IN (
            SELECT * FROM unnest(%s::text[], %s::bigint[]) AS t(sample_id, aliquot_id)
        )
    """

    db_df = pd.read_sql(
        sql,
        conn,
        params=(sample_ids, aliquot_ids)
    )

    # Track missing (both non-numeric and valid-but-not-found rows)
    find_missing(
        input_df=pairs_df[['sample_id', 'aliquot_id']],
        db_df=db_df,
        key_cols=["sample_id", "aliquot_id"],
        output_name="cbtn_specimens_missing_in_dwh.csv"
    )

    # Split
    to_mint = db_df[
        db_df['kf_biospecimen_id'].isna() |
        ~db_df['kf_biospecimen_id'].str.lower().str.startswith('bs')
    ]

    existing = db_df[
        db_df['kf_biospecimen_id'].notna() &
        db_df['kf_biospecimen_id'].str.lower().str.startswith('bs')
    ]

    return to_mint, existing

def build_rows(df, resource_type):
    if df.empty:
        return pd.DataFrame()

    if resource_type == "Patient":
        return pd.DataFrame({
            "fhirResourceType": "Patient",
            "descriptor": df['research_id'] + ";" + df['research_study_name'],
            "descriptorState": "ACTIVE",
            "research_study_name": df['research_study_name'],
            "research_id": df['research_id']
        })

    elif resource_type == "Specimen":
        return pd.DataFrame({
            "fhirResourceType": "Specimen",
            "descriptor": df['aliquot_id'] + ";" + df['research_study_name'],
            "descriptorState": "ACTIVE",
            "research_study_name": df['research_study_name'],
            "aliquot_id": df['aliquot_id']
        })

def normalize_existing(df, resource_type):
    if df is None or df.empty:
        return pd.DataFrame()

    if resource_type == "participant":
        return pd.DataFrame({
            "resource_type": "Patient",
            "research_study_name": df["research_study_name"],
            "case_id": df["research_id"],
            "sample_id": None,
            "aliquot_id": None,
            "kf_id": df["kids_first_participant_id"]
        })

    elif resource_type == "specimen":
        return pd.DataFrame({
            "resource_type": "Specimen",
            "research_study_name": df["research_study_name"],
            "case_id": None,
            "sample_id": df["sample_id"],
            "aliquot_id": df["aliquot_id"],
            "kf_id": df["kf_biospecimen_id"]
        })

def log_no_minting(to_mint_participant=None, to_mint_specimen=None):
    total = 0

    if to_mint_participant is not None:
        total += len(to_mint_participant)

    if to_mint_specimen is not None:
        total += len(to_mint_specimen)

    if total == 0:
        logger.info("ℹ️ No items need to be minted")
        return True

    return False

def log_existing_summary(resource, df):
    if df is None or df.empty:
        logger.info(f"⚠️ No existing {resource} records found in the prod_access.{resource}")

# ======================================
# MAIN
# ======================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, help="Path to CBTN(SD_BHJXBDQK) manifest CSV")
    parser.add_argument("--type", required=True, help="id minting type: participant, specimen or both", choices=["participant", "specimen", "both"])
    args = parser.parse_args()

    mint_type = args.type.lower()
    df = pd.read_csv(args.manifest)
    if mint_type == "participant":
        REQUIRED_FIELDS = ['case_id']
    elif mint_type == "specimen":
        REQUIRED_FIELDS = ['sample_id', 'aliquot_id']
    elif mint_type == "both":
        REQUIRED_FIELDS = ['case_id', 'sample_id', 'aliquot_id']
    else:
        raise ValueError(f"❌ Invalid type: {args.type}. Must be participant, specimen, or both.")

    validate_manifest(df, REQUIRED_FIELDS)
    conn = connect_to_database()

    if mint_type == "participant":
        to_mint, existing = check_participants(
            conn, cbtn_schema, cbtn_participant_table, df
        )
        
        mint_df = build_rows(to_mint, "Patient")
        save_if_not_empty(mint_df, "cbtn_participants_to_mint.csv")
        save_if_not_empty(existing, "cbtn_participants_minted_in_dwh.csv",
            ['research_study_name', 'research_id', 'kids_first_participant_id']
        )

        log_existing_summary("participant", existing)
        if not log_no_minting(to_mint_participant=to_mint):
            logger.info(f"🧾 Participants to mint: {len(to_mint)}")

    elif mint_type == "specimen":
        to_mint, existing = check_specimens(
            conn, cbtn_schema, cbtn_specimen_table, df
        )

        mint_df = build_rows(to_mint, "Specimen")
        save_if_not_empty(mint_df, "cbtn_specimens_to_mint.csv")
        save_if_not_empty(existing, "cbtn_specimens_minted_in_dwh.csv",
            ['research_study_name', 'sample_id', 'aliquot_id', 'kf_biospecimen_id']
        )

        log_existing_summary("specimen", existing)
        if not log_no_minting(to_mint_specimen=to_mint):
            logger.info(f"🧾 Specimens to mint: {len(to_mint)}")

    elif mint_type == "both":
        p_to_mint, p_existing = check_participants(
            conn, cbtn_schema, cbtn_participant_table, df
        )
        s_to_mint, s_existing = check_specimens(
            conn, cbtn_schema, cbtn_specimen_table, df
        )

        p_mint_df = build_rows(p_to_mint, "Patient")
        s_mint_df = build_rows(s_to_mint, "Specimen")

        combined = pd.concat([p_mint_df, s_mint_df])
        save_if_not_empty(combined, "cbtn_participants_specimens_to_mint.csv")

        p_existing_norm = normalize_existing(p_existing, "participant")
        s_existing_norm = normalize_existing(s_existing, "specimen")
        combined_existing = pd.concat([p_existing_norm, s_existing_norm], ignore_index=True)
        save_if_not_empty(combined_existing, "cbtn_participants_specimens_minted_in_dwh.csv")

        log_existing_summary("participant", p_existing)
        log_existing_summary("specimen", s_existing)
        if not log_no_minting(p_to_mint, s_to_mint):
            logger.info(f"🧾 Participants to mint: {len(p_to_mint)}")
            logger.info(f"🧾 Specimens to mint: {len(s_to_mint)}")


    logger.info(f"✅ Completed Process!")
    conn.close()

if __name__ == "__main__":
    main()