"""
Mint new organization-level Dewrangle IDs and save them into the database.

Required columns in manifest:
- fhirResourceType
- descriptor
- descriptorState

"""

import os
import sys
import time
import argparse
from pathlib import Path
import logging
from pprint import pformat
from typing import List, Optional
import pandas as pd
import requests
import psycopg2
from psycopg2 import OperationalError
from psycopg2.extras import execute_values
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
from io import StringIO

from env_config import config

# ======================================
# Setup
# ======================================
logger = logging.getLogger(__name__)

# Constants
TIMEOUT_INFINITY = -1
CSV_CONTENT_TYPE = "text/csv"

dewrangle_config = config["dewrangle"]
DEWRANGLE_TOKEN = dewrangle_config["dev_token"]
EXECUTION_TIMEOUT = dewrangle_config["client"]["execution_timeout"]

ROOT_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(ROOT_DATA_DIR, exist_ok=True)

graphql_client = None


# ======================================
# GraphQL Helpers
# ======================================
def exec_graphql_query(gql_query, variables=None):
    """
    Execute a GraphQL query or mutation using a cached gql Client.
    Automatically creates the client if it doesn't exist.

    Args:
        gql_query: gql(...) object or query string
        variables: Optional variables dict

    Returns:
        Response dict from GraphQL API
    """
    global graphql_client

    if graphql_client is None:
        base_url = dewrangle_config["base_url"].rstrip("/")
        endpoint = dewrangle_config["endpoints"]["graphql"]
        url = f"{base_url}/{endpoint}"
        headers = {"x-api-key": DEWRANGLE_TOKEN}

        logger.info(f"🛠️ Initializing GraphQL client → {url}")

        transport = AIOHTTPTransport(url=url, headers=headers)
        graphql_client = Client(
            transport=transport,
            fetch_schema_from_transport=False,
            execute_timeout=EXECUTION_TIMEOUT,
        )

    # Execute query
    return graphql_client.execute(gql_query, variable_values=variables)

# -------------------------------
# GraphQL mutation to create org global IDs
# -------------------------------
CREATE_ORG_GLOBAL_IDS = gql("""
mutation GlobalIdentifierUpsert($input: GlobalIdentifierUpsertInput!) {
  globalIdentifierUpsert(input: $input) {
    job {
      id
      operation
      completedAt
    }
    errors {
      ... on MutationError {
        message
        field
      }
    }
  }
}
""")

# ======================================
# HTTP Utility
# ======================================
def send_request(
    method: str,
    *args,
    #ignore_status_codes: list[str] = None,
    ignore_status_codes: Optional[List[str]] = None,
    timeout=TIMEOUT_INFINITY,
    wait_for_content: bool = False,
    poll_interval: int = 5,
    max_wait: int = 60,
    **kwargs,
) -> requests.Response:
    """
    Send HTTP request with optional polling until content is non-empty.
    
    Args:
        wait_for_content: if True, poll until response.text is non-empty
        poll_interval: seconds between polls
        max_wait: max total wait time in seconds
    """
    if isinstance(ignore_status_codes, str):
        ignore_status_codes = [ignore_status_codes]

    if not timeout:
        kwargs["timeout"] = (6.05, 120)
    elif timeout == TIMEOUT_INFINITY:
        kwargs["timeout"] = None

    requests_op = getattr(requests, method.lower())
    status_code = 0

    waited = 0
    while True:
        try:
            resp = requests_op(*args, **kwargs)
            status_code = resp.status_code
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if ignore_status_codes and (status_code in ignore_status_codes):
                pass
            else:
                body = "No request body found"
                try:
                    body = pformat(resp.json())
                except Exception:
                    body = resp.text
                raise requests.exceptions.HTTPError(
                    f"❌ Problem sending {method} request\n"
                    f"{str(e)}\nargs: {args}\nkwargs: {pformat(kwargs)}\n{body}"
                ) from e

        # If polling not required or content exists, return response
        if not wait_for_content or resp.text.strip():
            return resp
        
        # Else, check the size and wait if the content is still increasing
        if resp.text.strip():
            current_size = len(resp.text)
            if current_size == prev_size:
                break
            prev_size = current_size

        # Else wait and retry
        if waited >= max_wait:
            raise TimeoutError(f"❌ Response empty after waiting {max_wait}s")
        print(f"⏳ Response empty. Waiting {poll_interval}s...")
        time.sleep(poll_interval)
        waited += poll_interval

# ======================================
# Dewrangle Helpers
# ======================================
def download_job_report(
    job_id: str,
    organization_id: str,
    output_dir: Optional[str] = None
) -> str:
    """
    Download Dewrangle ID report for a specific job.
    Returns path to saved CSV.
    """

    base_url = dewrangle_config["base_url"].rstrip("/")
    endpoint_template = dewrangle_config["endpoints"]["job_rest"]["identifiers_report"]
    endpoint = endpoint_template.format(org_id=organization_id, job_id=job_id)
    url = f"{base_url}/{endpoint}"

    print(f"🌐 Dewrangle job global-identifiers report URL: ", url)

    output_dir = output_dir or ROOT_DATA_DIR
    os.makedirs(output_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M")
    filename = f"dewrangle-job-globalids-{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)

    headers = {"x-api-key": DEWRANGLE_TOKEN, "content-type": CSV_CONTENT_TYPE}
    resp = send_request(
        "get",
        url,
        headers=headers,
        wait_for_content=True,  # poll until CSV has data
        poll_interval=5,
        max_wait=60
    )

    # --- Read CSV into DataFrame ---
    df = pd.read_csv(StringIO(resp.text))
    df.to_csv(filepath, index=False)
    print(f"📥 Downloaded job global IDs report: {filepath}")
    return filepath

def download_org_report(
    organization_id: str,
    output_dir: Optional[str] = None
) -> str:
    """
    Download Dewrangle ID report for an organization.
    Returns path to saved CSV.
    """

    base_url = dewrangle_config["base_url"].rstrip("/")
    endpoint_template = dewrangle_config["endpoints"]["org_rest"]["identifiers_report"]
    endpoint = endpoint_template.format(org_id=organization_id)
    url = f"{base_url}/{endpoint}"

    print(f"🌐 Dewrangle organization global-identifiers report URL: ", url)

    output_dir = output_dir or ROOT_DATA_DIR
    os.makedirs(output_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M")
    filename = f"dewrangle-org-globalids-{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)

    headers = {"x-api-key": DEWRANGLE_TOKEN, "content-type": CSV_CONTENT_TYPE}
    resp = send_request(
        "get",
        url,
        headers=headers,
        wait_for_content=True,  # poll until CSV has data
        poll_interval=5,
        max_wait=60
    )
    
    # --- Read CSV into DataFrame ---
    df = pd.read_csv(StringIO(resp.text))
    df.to_csv(filepath, index=False)
    print(f"📥 Organization global IDs report saved at: {filepath}")
    return filepath

def create_org_global_ids(
    organization_id: str,
    file_id: str,
) -> str:
    """
    Create org-level global IDs and download the CSV report.

    Args:
        organization_id: Org ID (e.g., "org_12345")
        output_dir: Optional local directory to store CSV

    Returns:
        Path to downloaded CSV file
    """
    variables = {
        "input": {
            "organizationId": organization_id,
            "organizationFileIds": [
                {"id": file_id}
            ],
            "skipUnavailableDescriptors": False,
        }
    }

    resp = exec_graphql_query(CREATE_ORG_GLOBAL_IDS, variables)
    result = resp["globalIdentifierUpsert"]

    if result.get("errors"):
        raise RuntimeError(result["errors"])
    
    job = resp["globalIdentifierUpsert"]["job"]
    job_id = result["job"]["id"]
    print(f"🚀 Job submitted: {job_id}")

    # Polling
    while not job.get("completedAt"):
        print("Waiting for job to complete...")
        time.sleep(5)
        break

    print(f"✅ Job completed at: {job.get('completedAt')}")
    return job_id

def upload_org_file(org_id, csv_path: Path):
    """
    Upload a CSV file to Dewrangle for a given organization.

    Args:
        org_id: Dewrangle organization ID
        csv_path: Path object to CSV file

    Returns:
        JSON response from the upload API
    """
    base_url = dewrangle_config["base_url"].rstrip("/")
    filename = csv_path.name
    url = f"{base_url}/api/rest/organizations/{org_id}/files/{filename}"

    headers = {
        "x-api-key": DEWRANGLE_TOKEN,
        "Content-Type": "text/csv",
    }

    print(f"🔗 Upload URL: {url}")

    with csv_path.open("rb") as f:
        resp = requests.post(url, headers=headers, data=f)

    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        print(f"❌ Upload failed with status code {resp.status_code}")
        print("Response text:", resp.text[:500])
        raise e
    
    # Parse JSON
    try:
        resp_json = resp.json()
    except Exception:
        print("⚠️ Response is not valid JSON")
        resp_json = resp.text
        print(resp_json)
        raise ValueError("Upload response is not JSON, cannot get file ID")

    # Extract file ID
    try:
        file_id = resp_json["organizationFiles"][0]["id"]
        print(f"🆔 Uploaded file ID: {file_id}")
    except (KeyError, IndexError) as e:
        raise ValueError("Could not extract file ID from response") from e

    print(f"✅ Uploaded file '{filename}' to organization successfully!")

    return file_id

# ======================================
# Database Helpers
# ======================================
def connect_to_database(db_host, db_name, db_user, db_password):
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

def check_db_records_exist(
    conn,  # Accept the existing connection
    schema_name: str,
    table_name: str,
    df: pd.DataFrame,
    output_dir: Optional[str] = None
) -> list:
    """
    Check if records exist in the database and return the matching full rows.

    Args:
        schema_name: target schema
        table_name: target table
        df: DataFrame to check for existence
        output_dir: Optional directory to save the output file

    Returns:
        List of matching database rows as dictionaries. If no matching rows, returns an empty list.
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

    # If matching records exist, return them as dictionaries
    if not df_existing_rows.empty:

        timestamp = time.strftime("%Y%m%d-%H%M")
        filename = f"existing-db-records-{timestamp}.csv"
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, filename)

        df_existing_rows.to_csv(output_file, index=False)
        
        print(f"⚠️ Some records already exist in the database. Matching rows saved to: '{output_file}'.")
        return df_existing_rows
    else:
        return pd.DataFrame()
    
def save_df_to_db(
    conn,  # Accept the existing connection
    df: pd.DataFrame,
    schema_name: str,
    table_name: str,
    primary_key_cols: Optional[List[str]] = None,
) -> None:
    """
    Save DataFrame into PostgreSQL database using psycopg2.

    Args:
        df: DataFrame to save
        schema_name: target schema
        table_name: target table
        primary_key_cols: list of columns for ON CONFLICT
    """

    cur = conn.cursor()

    # Quote all column names to preserve case
    cols = list(df.columns)

    cols_quoted = [f'"{c}"' for c in cols]
    pk_cols_quoted = [f'"{c}"' for c in primary_key_cols]

    insert_sql = f"""
        INSERT INTO {schema_name}.{table_name} ({','.join(cols_quoted)})
        VALUES %s
        ON CONFLICT ({', '.join(pk_cols_quoted)}) DO NOTHING;
    """
    try:
        execute_values(cur, insert_sql, df.to_records(index=False).tolist())
        conn.commit()
        if cur.rowcount == 0:
            print(f"⚠️ No new rows inserted (all duplicates).")
        else:
            print(f"✅ Insert completed for {schema_name}.{table_name}")

    finally:
        cur.close()

def save_dewrangle_ids(
    conn,  # Accept connection as argument
    filepath: str,
    dewrangle_ids_config,
):
    """
    Save generated Dewrangle IDs into warehouse table.
    """
    # Read dewrangle file and re-format for D3b warehouse table
    df = pd.read_csv(filepath, keep_default_na=False)

    if df.empty or df.shape[0] == 0:
        print(f"✅ Nothing new to update in db. Aborting")
        return

    schema_name = dewrangle_ids_config["schema"]
    table_name = dewrangle_ids_config["table"]
    primary_key_cols = dewrangle_ids_config["primary_key_cols"]

    # Update the dewrangle identifiers table
    save_df_to_db(conn, df, schema_name, table_name, primary_key_cols)

def save_data_transfer_manpping(
    conn,  # Accept connection as argument
    filepath: str,
    manifest_df: pd.DataFrame,
    data_transfer_manpping_config,
):
    """
    Save mapping between Dewrangle global IDs and Data Transfer files.
    """
    # Read dewrangle file and re-format for D3b warehouse table
    df = pd.read_csv(filepath, keep_default_na=False)
    if df.empty or df.shape[0] == 0:
        print(f"✅ Nothing new to update in db. Aborting")
        return
    df = df.fillna('')
    schema_name = data_transfer_manpping_config["schema"]
    table_name = data_transfer_manpping_config["table"]
    primary_key_cols = data_transfer_manpping_config["primary_key_cols"]

    # Update the dewrangle identifiers table
    df = df.rename(columns={"globalId": "global_id"})

    merged_df = df.merge(
        manifest_df,
        on=["fhirResourceType", "descriptor", "descriptorState"],
        how="inner"
    )
    merged_df = merged_df[["study_id","file_name", "dt_id", "global_id"]]
    save_df_to_db(conn, merged_df, schema_name, table_name, primary_key_cols)


# ======================================
# CLI + Main
# ======================================
def parse_args():
    parser = argparse.ArgumentParser(description="Create and download org-level global IDs from Dewrangle.")
    parser.add_argument(
        "--env",
        choices=["prod", "qa"],
        help="Environment to use (prod or qa). Determines default schema and organization_id if not set explicitly."
    )
    parser.add_argument(
        "--organization_id",
        default=None,
        help="Dewrangle Organization ID. Overrides --env default if provided."
    )
    parser.add_argument("--manifest", required=True, help="Path to input manifest CSV file")
    parser.add_argument("--save-dt-record", action="store_true", help="If set, save data transfer mapping record to DWH")
    parser.add_argument("--output_dir", default=None, help="Optional output directory for downloaded CSV")
    
    args = parser.parse_args()

    # Set organization_id based on env if not explicitly provided
    if args.organization_id:
        org_message = f"🛠️ Using custom organization_id for ID minting: {args.organization_id}"
    elif args.env == "prod":
        args.organization_id = "T3JnYW5pemF0aW9uOmNsZHN4MzRrbjAwMTRnMGVzY3JndzUzYWQ=" # Dewrangle Kids First organization ID for the ID minting
        org_message = "🚀 Using Kids First prod Dewrangle organization for ID minting"
        db_config = config["db"]["d3b_warehouse"]["prod"]  # Use prod DB config for prod env
    elif args.env == "qa":
        args.organization_id = "T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA=" # Dewrangle test-dewrangle-ids organization ID for the ID minting
        org_message = "🧪 Using test-dewrangle-ids organization for ID minting"
        db_config = config["db"]["d3b_warehouse"]["qa"]  # Use qa DB config for qa env
    else:
        parser.error("Either --organization_id must be set or --env must be 'prod' or 'qa'.")
    args.db_config = db_config
    args.org_message = org_message
    return args


def main():
    args = parse_args()
    print(args.org_message)
    manifest_path = Path(args.manifest).resolve()

    # --- Step 1: Read and validate manifest ---
    manifest_df = pd.read_csv(manifest_path)
    required_columns = ["fhirResourceType", "descriptor", "descriptorState"]
    missing_columns = [col for col in required_columns if col not in manifest_df.columns]
    if missing_columns:
        raise ValueError(f"Manifest is missing required columns: {missing_columns}")
    
    print(f"✅ Manifest read successfully with {manifest_df.shape[0]} rows.")

    # --- Step 2: Connect to the database once
    conn = connect_to_database(
        db_host=args.db_config["db_host"],
        db_name=args.db_config["db_name"],
        db_user=args.db_config["db_user"],
        db_password=args.db_config["db_password"]
    )

    # --- Step 3: check if descriptors already exist ---
    existing_rows = check_db_records_exist(
        conn,  # Pass the connection
        schema_name=args.db_config["dewrangle_ids"]["schema"],
        table_name=args.db_config["dewrangle_ids"]["table"],
        df=manifest_df,
        output_dir=args.output_dir
    )

    if not existing_rows.empty:
        print("❌ Aborting to avoid duplicates. Please remove the duplicate descriptors and try again.")
        sys.exit()  # Exit the script
    
    # --- Step 4: Upload file manifest ---
    file_id = upload_org_file(
        args.organization_id,
        manifest_path
    )
    
    # Step 5: Create org global IDs
    job_id = create_org_global_ids(
        organization_id=args.organization_id,
        file_id=file_id
    )

    # Step 6: download job global IDs reports
    filepath = download_job_report(
        organization_id=args.organization_id,
        job_id=job_id,
        output_dir = args.output_dir
    )

    # Step 7: Save to dewrangle ids to warehouse
    print(f"🗂️ Saving dewrangle IDs report to DB...")
    dewrangle_ids_config = args.db_config["dewrangle_ids"]
    save_dewrangle_ids(conn, filepath, dewrangle_ids_config)

     # Step 7: Optionally save Data Transfer mapping
    if args.save_dt_record:
        plus_columns = ["study_id", "file_name", "dt_id"]
        missing = [col for col in plus_columns if col not in manifest_df.columns]
        if missing:
            raise ValueError(f"Manifest missing columns for saving DT records: {missing}")
        
        print(f"🗂️ Saving Data Transfer Records to DB...")
        data_transfer_manpping_config = args.db_config["data_transfer_file_mapping"]
        save_data_transfer_manpping(conn, filepath, manifest_df, data_transfer_manpping_config)
    
    # Close the connection once all tasks are completed
    conn.close()

    print(f"🎉 All completed!")

if __name__ == "__main__":
    main()