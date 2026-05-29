"""
Dewrangle API client: GraphQL and REST helpers for ID minting operations.
"""

import os
import time
import logging
from pathlib import Path
from typing import List, Optional, Union
from io import StringIO

import pandas as pd
import requests
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
from pprint import pformat

from src.env_config import config

# ======================================
# Setup
# ======================================
logger = logging.getLogger(__name__)

TIMEOUT_INFINITY = -1
CSV_CONTENT_TYPE = "text/csv"

dewrangle_config = config["dewrangle"]
DEWRANGLE_TOKEN = dewrangle_config["dev_token"]
EXECUTION_TIMEOUT = dewrangle_config["client"]["execution_timeout"]

# Validate required config is present
_missing = []
if not DEWRANGLE_TOKEN:
    _missing.append("DEWRANGLE_TOKEN")
if not dewrangle_config.get("base_url"):
    _missing.append("DEWRANGLE_BASE_URL")
if _missing:
    raise RuntimeError(
        f"❌ Missing required environment variable(s): {', '.join(_missing)}. "
        "Please set them before running this script."
    )

ROOT_DATA_DIR = os.getcwd()

_graphql_client = None


# ======================================
# GraphQL Helpers
# ======================================
def _init_graphql_client():
    """Create and return a fresh gql Client."""
    base_url = dewrangle_config["base_url"].rstrip("/")
    endpoint = dewrangle_config["endpoints"]["graphql"]
    url = f"{base_url}/{endpoint}"
    headers = {"x-api-key": DEWRANGLE_TOKEN}

    logger.info(f"🛠️ Initializing GraphQL client → {url}")

    transport = AIOHTTPTransport(url=url, headers=headers)
    return Client(
        transport=transport,
        fetch_schema_from_transport=False,
        execute_timeout=EXECUTION_TIMEOUT,
    )


def exec_graphql_query(gql_query, variables=None, retries=3, backoff=2):
    """
    Execute a GraphQL query or mutation using a cached gql Client.
    Automatically creates the client if it doesn't exist.
    Retries on transient server disconnects.

    Args:
        gql_query: gql(...) object or query string
        variables: Optional variables dict
        retries: Number of retry attempts (default 3)
        backoff: Seconds to wait between retries (multiplied by attempt number)

    Returns:
        Response dict from GraphQL API
    """
    global _graphql_client

    if _graphql_client is None:
        _graphql_client = _init_graphql_client()

    last_exception = None
    for attempt in range(1, retries + 1):
        try:
            return _graphql_client.execute(gql_query, variable_values=variables)
        except Exception as e:
            last_exception = e
            error_name = type(e).__name__
            is_transient = error_name in (
                "ServerDisconnectedError",
                "ClientConnectorError",
                "TimeoutError",
                " asyncio.TimeoutError",
            ) or "ServerDisconnectedError" in str(e)

            if not is_transient or attempt == retries:
                raise

            wait = backoff * attempt
            print(f"⚠️ GraphQL error ({error_name}) on attempt {attempt}/{retries}. Retrying in {wait}s...")
            time.sleep(wait)

            # Recreate client on disconnect to ensure a fresh connection
            _graphql_client = _init_graphql_client()

    raise last_exception


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

CREATE_KF_STUDY = gql("""
mutation MyMutation($input: StudyCreateInput!) {
  studyCreate(input: $input) {
    study {
      globalId
      name
      id
    }
  }
}
""")

GET_ORGANIZATION_STUDIES = gql("""
query MyQuery($organization_id: ID!) {
  node(id: $organization_id) {
    ... on Organization {
      id
      studies {
        edges {
          node {
            id
            name
            globalId
          }
        }
      }
    }
  }
}
""")

GET_ORG_GLOBAL_IDENTIFIERS = gql("""
query MyQuery($organization_id: ID!) {
  node(id: $organization_id) {
    ... on Organization {
      id
      globalIdentifiers {
        edges {
          node {
            globalId
            fhirResourceType
            descriptors {
              edges {
                node {
                  descriptor
                  event
                  createdAt
                  createdByUser {
                    email
                  }
                  globalIdentifier {
                    createdAt
                    createdByUser {
                      email
                    }
                  }
                }
              }
            }
            study {
              globalId
              name
            }
          }
        }
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
    prev_size = 0

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

        # Check if content size stabilized
        current_size = len(resp.text)
        if current_size == prev_size:
            return resp
        prev_size = current_size

        # Wait and retry
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

    print(f"🌐 Dewrangle job global-identifiers report URL: {url}")

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
        wait_for_content=True,
        poll_interval=5,
        max_wait=60
    )

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

    print(f"🌐 Dewrangle organization global-identifiers report URL: {url}")

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
        wait_for_content=True,
        poll_interval=5,
        max_wait=60
    )

    df = pd.read_csv(StringIO(resp.text))
    df.to_csv(filepath, index=False)
    print(f"📥 Organization global IDs report saved at: {filepath}")
    return filepath


def create_org_global_ids(
    organization_id: str,
    file_id: str,
) -> str:
    """
    Create org-level global IDs.

    Args:
        organization_id: Org ID (e.g., "org_12345")
        file_id: Uploaded organization file ID

    Returns:
        Job ID string
    """
    variables = {
        "input": {
            "organizationId": organization_id,
            "organizationFileIds": [{"id": file_id}],
            "skipUnavailableDescriptors": False,
        }
    }

    resp = exec_graphql_query(CREATE_ORG_GLOBAL_IDS, variables)
    result = resp["globalIdentifierUpsert"]

    if result.get("errors"):
        raise RuntimeError(result["errors"])

    job_id = result["job"]["id"]
    print(f"🚀 Job submitted: {job_id}")

    # Brief wait for job completion
    job = result["job"]
    while not job.get("completedAt"):
        print("Waiting for job to complete...")
        time.sleep(5)
        break

    print(f"✅ Job completed at: {job.get('completedAt')}")
    return job_id


def upload_org_file(org_id, csv_path: Path) -> str:
    """
    Upload a CSV file to Dewrangle for a given organization.

    Args:
        org_id: Dewrangle organization ID
        csv_path: Path object to CSV file

    Returns:
        Uploaded file ID string
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

    try:
        resp_json = resp.json()
    except Exception:
        print("⚠️ Response is not valid JSON")
        raise ValueError("Upload response is not JSON, cannot get file ID")

    try:
        file_id = resp_json["organizationFiles"][0]["id"]
        print(f"🆔 Uploaded file ID: {file_id}")
    except (KeyError, IndexError) as e:
        raise ValueError("Could not extract file ID from response") from e

    print(f"✅ Uploaded file '{filename}' to organization successfully!")
    return file_id


def update_org_global_ids(
    organization_id: str,
    manifest_path: Path,
    output_dir: Optional[str] = None,
) -> str:
    """
    Update (upsert) Dewrangle global IDs from a manifest.

    Process:
      1. Upload the manifest to the organization
      2. Trigger globalIdentifierUpsert (creates or updates IDs)
      3. Download the updated job report

    Args:
        organization_id: Dewrangle organization ID
        manifest_path: Path to the manifest CSV (must contain fhirResourceType,
                       descriptor, descriptorState)
        output_dir: Optional directory to save the report

    Returns:
        Path to the downloaded report CSV
    """
    file_id = upload_org_file(organization_id, manifest_path)
    job_id = create_org_global_ids(organization_id, file_id)
    report_path = download_job_report(organization_id, job_id, output_dir=output_dir)
    return report_path


def download_org_global_identifiers(
    organization_id: str,
    global_id: Optional[Union[str, List[str]]] = None,
    output_dir: Optional[str] = None
) -> str:
    """
    Query global identifiers for an organization and flatten the nested
    response into a CSV with columns: globalId, fhirResourceType, descriptor, event.

    Args:
        organization_id: Dewrangle organization ID
        global_id: If provided, filter results to matching globalId(s).
                     Accepts a single string, a list of strings, or None for all.
        output_dir: Optional directory to save the CSV

    Returns:
        Path to the saved CSV file
    """
    # Normalize global_id to a set for efficient lookup
    if global_id is None:
        target_ids = None
    elif isinstance(global_id, str):
        target_ids = {global_id}
    else:
        target_ids = set(global_id)

    variables = {"organization_id": organization_id}
    resp = exec_graphql_query(GET_ORG_GLOBAL_IDENTIFIERS, variables)

    node_data = resp.get("node", {})
    global_ids_conn = node_data.get("globalIdentifiers", {})
    gi_edges = global_ids_conn.get("edges", [])

    rows = []
    for gi_edge in gi_edges:
        gi_node = gi_edge.get("node", {})
        gi_global_id = gi_node.get("globalId")

        # Filter by globalId(s) if requested
        if target_ids is not None and gi_global_id not in target_ids:
            continue

        fhir_type = gi_node.get("fhirResourceType")
        study = gi_node.get("study") or {}
        descriptors_conn = gi_node.get("descriptors", {})
        desc_edges = descriptors_conn.get("edges", [])

        for desc_edge in desc_edges:
            desc_node = desc_edge.get("node", {})
            desc_created_by = desc_node.get("createdByUser") or {}
            gi_ref = desc_node.get("globalIdentifier") or {}
            gi_ref_created_by = gi_ref.get("createdByUser") or {}

            rows.append({
                "globalId": gi_global_id,
                "studyGlobalId": study.get("globalId"),
                "studyName": study.get("name"),
                "fhirResourceType": fhir_type,
                "descriptor": desc_node.get("descriptor"),
                "descriptorState": desc_node.get("event"),
                "globalIdCreatedAt": gi_ref.get("createdAt"),
                "globalIdCreatedBy": gi_ref_created_by.get("email"),
                "descriptorCreatedAt": desc_node.get("createdAt"),
                "descriptorCreatedBy": desc_created_by.get("email"),
            })

    df = pd.DataFrame(rows)

    output_dir = output_dir or ROOT_DATA_DIR
    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M")

    if target_ids is not None and len(target_ids) == 1:
        filename = f"dewrangle-global-id-{next(iter(target_ids))}-{timestamp}.csv"
    elif target_ids is not None:
        filename = f"dewrangle-global-ids-{len(target_ids)}-filtered-{timestamp}.csv"
    else:
        filename = f"dewrangle-org-global-identifiers-{timestamp}.csv"

    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    
    return filepath


def download_created_study_report(
    study_result: dict,
    output_dir: Optional[str] = None
) -> str:
    """
    Download Dewrangle ID report for a newly created study.
    Injects studyGlobalId and studyName columns into the report.
    Returns path to saved CSV.
    """
    study_node_id = study_result["id"]
    study_name = study_result["name"]
    study_global_id = study_result["globalId"]

    base_url = dewrangle_config["base_url"].rstrip("/")
    endpoint_template = dewrangle_config["endpoints"]["study_rest"]["identifiers_report"]
    endpoint = endpoint_template.format(study_node_id=study_node_id)
    url = f"{base_url}/{endpoint}"

    output_dir = output_dir or ROOT_DATA_DIR
    os.makedirs(output_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M")
    filename = f"dewrangle-study-globalids-{timestamp}.csv"
    filepath = os.path.join(output_dir, filename)

    headers = {"x-api-key": DEWRANGLE_TOKEN, "content-type": CSV_CONTENT_TYPE}
    resp = send_request(
        "get",
        url,
        headers=headers,
        wait_for_content=True,
        poll_interval=5,
        max_wait=60
    )

    all_df = pd.read_csv(StringIO(resp.text))
    df = all_df[all_df['globalId'] == study_global_id]
    global_idx = df.columns.get_loc("globalId") + 1
    df.insert(global_idx, "studyGlobalId", study_global_id)
    df.insert(global_idx + 1, "studyName", study_name)
    df.to_csv(filepath, index=False)
    print(f"📥 Study global IDs report saved at: {filepath}")
    return filepath


def find_study_by_name(
    organization_id: str,
    study_name: str,
) -> Optional[dict]:
    """
    Check if a study with the given name already exists in Dewrangle.

    Args:
        organization_id: Org ID
        study_name: Name of the study to look up

    Returns:
        Study dict with keys: id, name, globalId if found, else None.
    """
    variables = {
        "organization_id": organization_id,
    }

    try:
        resp = exec_graphql_query(GET_ORGANIZATION_STUDIES, variables)
    except Exception as e:
        logger.warning(f"⚠️ Failed to query Dewrangle for existing studies: {e}")
        return None

    node_data = resp.get("node")
    if not node_data:
        return None

    studies_conn = node_data.get("studies", {})
    edges = studies_conn.get("edges", [])

    for edge in edges:
        study = edge.get("node")
        if study and study.get("name") == study_name:
            print(f"🔍 Found existing study '{study_name}' in Dewrangle (globalId: {study['globalId']})")
            return study

    return None


def create_kf_study(
    organization_id: str,
    study_name: str,
) -> dict:
    """
    Create a new study in Dewrangle under the given organization.

    Args:
        organization_id: Org ID
        study_name: Name of the study to create

    Returns:
        Study result dict with keys: id, name, globalId
    """
    variables = {
        "input": {
            "name": study_name,
            "organizationId": organization_id
        }
    }

    resp = exec_graphql_query(CREATE_KF_STUDY, variables)
    result = resp["studyCreate"]["study"]
    print(f"✅ Created study '{result['name']}' with globalId {result['globalId']}")
    return result
