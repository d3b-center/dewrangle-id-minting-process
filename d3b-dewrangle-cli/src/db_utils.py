"""
Database utilities for warehouse connections and operations.
"""

import os
import time
from typing import List, Optional

import pandas as pd
import psycopg2
from psycopg2 import OperationalError
from psycopg2.extras import execute_values
from pprint import pformat

from src.env_config import config


# ======================================
# Database Config
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


# ======================================
# Connection
# ======================================
def connect_to_database(db_host, db_name, db_user, db_port, db_password):
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
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
        )
        print(f"✅ Successfully connected to database!")
        return conn

    except OperationalError as e:
        raise RuntimeError(
            "❌ Failed to connect to database:\n"
            f"{str(e)}\nConfig: {pformat(display)}"
        )


# ======================================
# Existence Checks
# ======================================
def check_db_records_exist(
    conn,
    schema_name: str,
    table_name: str,
    df: pd.DataFrame,
    output_dir: Optional[str] = None,
) -> pd.DataFrame:
    """
    Check if records exist in the database by descriptor and return matching rows.

    Args:
        conn: Active database connection
        schema_name: target schema
        table_name: target table
        df: DataFrame containing descriptors to check
        output_dir: Optional directory to save the output file

    Returns:
        DataFrame of matching database rows. Empty if no matches.
    """
    descriptors_to_check = list(set(df["descriptor"].dropna()))
    if not descriptors_to_check:
        return pd.DataFrame()

    placeholders = ", ".join(["%s"] * len(descriptors_to_check))
    query = f"""
        SELECT *
        FROM {schema_name}.{table_name}
        WHERE descriptor IN ({placeholders})
    """
    df_existing_rows = pd.read_sql(
        query, conn, params=tuple(descriptors_to_check)
    )

    if not df_existing_rows.empty:
        if output_dir:
            timestamp = time.strftime("%Y%m%d-%H%M")
            filename = f"existing-db-records-{timestamp}.csv"
            os.makedirs(output_dir, exist_ok=True)
            output_file = os.path.join(output_dir, filename)

            df_existing_rows.to_csv(output_file, index=False)
            print(
                f"⚠️ Some records already exist in the database. Matching rows saved to: '{output_file}'."
            )
        return df_existing_rows
    else:
        return pd.DataFrame()


def check_study_exists(
    conn,
    schema_name: str,
    table_name: str,
    study_name: str,
) -> bool:
    """
    Check if a study name already exists in the dewrangle IDs table.

    Args:
        conn: Active database connection
        schema_name: target schema
        table_name: target table
        study_name: Study name to look up

    Returns:
        True if the study name exists, False otherwise.
    """
    query = f"""
        SELECT 1
        FROM {schema_name}.{table_name}
        WHERE "studyName" = %s
        LIMIT 1
    """
    df = pd.read_sql(query, conn, params=(study_name,))
    return not df.empty


def get_table_columns(conn, schema_name: str, table_name: str) -> List[str]:
    """
    Return a list of column names for the given table.

    Args:
        conn: Active database connection
        schema_name: target schema
        table_name: target table

    Returns:
        List of column names.
    """
    query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """
    df = pd.read_sql(query, conn, params=(schema_name, table_name))
    return df["column_name"].tolist()


def delete_db_records_by_global_ids(
    conn,
    schema_name: str,
    table_name: str,
    global_ids: List[str],
) -> int:
    """
    Delete all records from the table where globalId matches any value in the list.

    Args:
        conn: Active database connection
        schema_name: target schema
        table_name: target table
        global_ids: List of globalId values to delete

    Returns:
        Number of rows deleted.
    """
    if not global_ids:
        return 0

    placeholders = ", ".join(["%s"] * len(global_ids))
    query = f"""
        DELETE FROM {schema_name}.{table_name}
        WHERE "globalId" IN ({placeholders})
    """
    cur = conn.cursor()
    try:
        cur.execute(query, tuple(global_ids))
        conn.commit()
        deleted = cur.rowcount
        print(
            f"🗑️  Deleted {deleted} existing record(s) from {schema_name}.{table_name}"
        )
        return deleted
    finally:
        cur.close()


# ======================================
# Write Operations
# ======================================
def _table_exists(conn, schema_name: str, table_name: str) -> bool:
    """Check if a table exists in the given schema."""
    query = """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        LIMIT 1
    """
    cur = conn.cursor()
    try:
        cur.execute(query, (schema_name, table_name))
        return cur.fetchone() is not None
    finally:
        cur.close()


def _get_pg_type(dtype) -> str:
    """Always use TEXT for created columns to keep table schema simple."""
    return "TEXT"


def save_df_to_db(
    conn,
    df: pd.DataFrame,
    schema_name: str,
    table_name: str,
    primary_key_cols: Optional[List[str]] = None,
    on_conflict: str = "nothing",
) -> None:
    """
    Save DataFrame into PostgreSQL database using psycopg2 execute_values.
    If the target table does not exist, it will be created automatically
    with inferred column types and the specified primary key.

    Args:
        conn: Active database connection
        df: DataFrame to save
        schema_name: target schema
        table_name: target table
        primary_key_cols: list of columns for PRIMARY KEY and ON CONFLICT
        on_conflict: "nothing" (default) or "update" — action when a conflict occurs
    """
    cols = list(df.columns)
    cols_quoted = [f'"{c}"' for c in cols]
    pk_cols_quoted = (
        [f'"{c}"' for c in primary_key_cols] if primary_key_cols else []
    )

    # Create table if it doesn't exist
    if not _table_exists(conn, schema_name, table_name):
        print(
            f"🔨 Table {schema_name}.{table_name} does not exist. Creating..."
        )
        col_defs = []
        for c in cols:
            pg_type = _get_pg_type(df[c].dtype)
            col_defs.append(f'"{c}" {pg_type}')

        if pk_cols_quoted:
            pk_clause = f", PRIMARY KEY ({', '.join(pk_cols_quoted)})"
        else:
            pk_clause = ""

        create_sql = f"""
            CREATE TABLE {schema_name}.{table_name} (
                {', '.join(col_defs)}{pk_clause}
            );
        """
        cur = conn.cursor()
        try:
            cur.execute(create_sql)
            conn.commit()
            print(f"✅ Created table {schema_name}.{table_name}")
        finally:
            cur.close()

    cur = conn.cursor()

    if pk_cols_quoted:
        if on_conflict == "update":
            # Build UPDATE SET for all non-PK columns
            update_cols = [c for c in cols if c not in (primary_key_cols or [])]
            if update_cols:
                set_clause = ", ".join(
                    [f'"{c}" = EXCLUDED."{c}"' for c in update_cols]
                )
                conflict_action = f"DO UPDATE SET {set_clause}"
            else:
                conflict_action = "DO NOTHING"
        else:
            conflict_action = "DO NOTHING"

        insert_sql = f"""
            INSERT INTO {schema_name}.{table_name} ({','.join(cols_quoted)})
            VALUES %s
            ON CONFLICT ({', '.join(pk_cols_quoted)}) {conflict_action};
        """
    else:
        insert_sql = f"""
            INSERT INTO {schema_name}.{table_name} ({','.join(cols_quoted)})
            VALUES %s;
        """

    try:
        # Convert NaN → None so PostgreSQL inserts NULLs, not "nan" strings
        df_clean = df.astype(object).where(pd.notnull(df), None)
        execute_values(
            cur, insert_sql, df_clean.to_records(index=False).tolist()
        )
        conn.commit()
        if cur.rowcount == 0:
            print(f"⚠️ No new rows inserted (all duplicates).")
        else:
            action = "Upsert" if on_conflict == "update" else "Insert"
            print(f"✅ {action} completed for {schema_name}.{table_name}")
    finally:
        cur.close()


def save_dewrangle_ids(
    conn,
    dewrangle_ids_config,
    filepath: str = None,
    df: pd.DataFrame = None,
    on_conflict: str = "nothing",
):
    """
    Save generated Dewrangle IDs into warehouse table.

    Args:
        on_conflict: "nothing" (default) to skip duplicates, or "update" to overwrite.
    """

    if df is None:
        if filepath is None:
            raise ValueError("Either 'filepath' or 'df' must be provided.")
        else:
            df = pd.read_csv(filepath, keep_default_na=False)

    if df.empty or df.shape[0] == 0:
        print("✅ Nothing new to update in db. Aborting")
        return

    schema_name = dewrangle_ids_config["schema"]
    table_name = dewrangle_ids_config["table"]
    primary_key_cols = dewrangle_ids_config["primary_key_cols"]

    save_df_to_db(
        conn,
        df,
        schema_name,
        table_name,
        primary_key_cols,
        on_conflict=on_conflict,
    )


def save_data_transfer_mapping(
    conn,
    filepath: str,
    manifest_df: pd.DataFrame,
    data_transfer_mapping_config,
):
    """
    Save mapping between Dewrangle global IDs and Data Transfer files.
    """
    df = pd.read_csv(filepath, keep_default_na=False)
    if df.empty or df.shape[0] == 0:
        print("✅ Nothing new to update in db. Aborting")
        return

    df = df.fillna("")
    schema_name = data_transfer_mapping_config["schema"]
    table_name = data_transfer_mapping_config["table"]
    primary_key_cols = data_transfer_mapping_config["primary_key_cols"]

    df = df.rename(columns={"globalId": "global_id"})

    merged_df = df.merge(
        manifest_df,
        on=["fhirResourceType", "descriptor", "descriptorState"],
        how="inner",
    )
    merged_df = merged_df[["study_id", "file_name", "dt_id", "global_id"]]
    save_df_to_db(conn, merged_df, schema_name, table_name, primary_key_cols)
