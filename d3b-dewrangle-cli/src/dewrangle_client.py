"""
Dewrangle API client: GraphQL and REST helpers for ID minting operations.
"""

import os
import time
import asyncio
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
EXECUTION_TIMEOUT = int(dewrangle_config["client"]["execution_timeout"])

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


def exec_graphql_query(gql_query, variables=None, retries=2, backoff=2):
    """
    Execute a GraphQL query or mutation using a cached gql Client.
    Automatically creates the client if it doesn't exist.
    Retries on transient server disconnects.

    Args:
        gql_query: gql(...) object or query string
        variables: Optional variables dict
        retries: Number of retry attempts (default 2)
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

GET_JOB = gql("""
query GetJob($id: ID!) {
  node(id: $id) {
    ... on Job {
      id
      completedAt
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
query MyQuery($organization_id: ID!, $first: Int, $after: String) {
  node(id: $organization_id) {
    ... on Organization {
      id
      studies(first: $first, after: $after) {
        edges {
          node {
            id
            name
            globalId
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
""")

GET_ORG_GLOBAL_IDENTIFIERS_BY_ID = gql("""
query MyQuery($organization_id: ID!, $filter: GlobalIdentifierFilter!) {
  node(id: $organization_id) {
    ... on Organization {
      id
      globalIdentifiers(filter: $filter) {
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

        # Wait and retry
        if waited >= max_wait:
            raise TimeoutError(
                f"Response was empty after waiting {max_wait}s."
            )
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
    try:
        resp = send_request(
            "get",
            url,
            headers=headers,
            wait_for_content=True,
            poll_interval=5,
            max_wait=30
        )
    except TimeoutError as e:
        raise TimeoutError(
            f"🚫 The Dewrangle job global-identifiers report is empty after waiting 30s.\n"
            f"   Report URL: {url}\n"
            f"   This usually means the job completed but no identifiers were created or updated.\n"
            f"   Please verify your manifest contents and check the job in the Dewrangle UI."
        ) from e

    df = pd.read_csv(StringIO(resp.text))
    df.to_csv(filepath, index=False)
    print(f"📥 Downloaded job global IDs report: {filepath}")
    return filepath


def fetch_org_report_df(
    organization_id: str,
) -> pd.DataFrame:
    """
    Download the Dewrangle organization global-identifiers report via REST
    and return it as a DataFrame (without saving the full report to disk).
    """
    base_url = dewrangle_config["base_url"].rstrip("/")
    endpoint_template = dewrangle_config["endpoints"]["org_rest"]["identifiers_report"]
    endpoint = endpoint_template.format(org_id=organization_id)
    url = f"{base_url}/{endpoint}"

    print(f"🌐 Dewrangle organization global-identifiers report URL: {url}")

    headers = {"x-api-key": DEWRANGLE_TOKEN, "content-type": CSV_CONTENT_TYPE}
    try:
        resp = send_request(
            "get",
            url,
            headers=headers,
            wait_for_content=True,
            poll_interval=5,
            max_wait=60
        )
    except TimeoutError as e:
        raise TimeoutError(
            f"🚫 The Dewrangle organization global-identifiers report is empty after waiting 60s.\n"
            f"   Report URL: {url}\n"
            f"   Please verify the organization has identifiers and try again."
        ) from e

    df = pd.read_csv(StringIO(resp.text))
    return df


def _normalize_descriptor_state(event: Optional[str]) -> Optional[str]:
    """
    Map Dewrangle GraphQL descriptor event values back to the
    descriptorState values used in manifests and REST reports.
    """
    mapping = {
        "ACTIVATED": "ACTIVE",
        "DEACTIVATED": "INACTIVE",
    }
    return mapping.get(event, event)


def _parse_global_identifier_edges(gi_edges: List[dict]) -> List[dict]:
    """Flatten a list of GlobalIdentifier edges into descriptor rows."""
    rows = []
    for gi_edge in gi_edges:
        gi_node = gi_edge.get("node", {})
        gi_global_id = gi_node.get("globalId")
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
                "descriptorState": _normalize_descriptor_state(desc_node.get("event")),
                "globalIdCreatedAt": gi_ref.get("createdAt"),
                "globalIdCreatedBy": gi_ref_created_by.get("email"),
                "descriptorCreatedAt": desc_node.get("createdAt"),
                "descriptorCreatedBy": desc_created_by.get("email"),
            })
    return rows


async def _fetch_global_identifier_batch_async(
    session,
    organization_id: str,
    batch: List[str],
) -> List[dict]:
    """
    Async helper to query a single batch of globalIds.
    Returns the raw GlobalIdentifier edges.
    """
    variables = {
        "organization_id": organization_id,
        "filter": {"globalId": batch},
    }
    resp = await session.execute(
        GET_ORG_GLOBAL_IDENTIFIERS_BY_ID, variable_values=variables
    )
    node_data = resp.get("node", {})
    global_ids_conn = node_data.get("globalIdentifiers", {})
    return global_ids_conn.get("edges", [])


async def _download_filtered_org_global_identifiers_async(
    organization_id: str,
    target_ids: List[str],
    batch_size: int,
    max_workers: int,
) -> List[dict]:
    """
    Query global identifiers in batches with limited concurrency.
    Returns flattened descriptor rows.
    """
    batches = [
        target_ids[i * batch_size:(i + 1) * batch_size]
        for i in range((len(target_ids) + batch_size - 1) // batch_size)
    ]

    print(
        f"🔍 Querying {len(target_ids)} globalIds in {len(batches)} batches "
        f"of up to {batch_size}, with {max_workers} parallel workers..."
    )

    client = _init_graphql_client()
    semaphore = asyncio.Semaphore(max_workers)
    rows = []

    async with client as session:
        async def fetch_limited(batch):
            async with semaphore:
                print(f"🚀 Querying batch of {len(batch)} globalIds...")
                gi_edges = await _fetch_global_identifier_batch_async(
                    session, organization_id, batch
                )
                print(f"✅ Completed batch of {len(batch)} globalIds.")
                return gi_edges

        results = await asyncio.gather(*[fetch_limited(batch) for batch in batches])
        for gi_edges in results:
            rows.extend(_parse_global_identifier_edges(gi_edges))

    return rows


def download_filtered_org_global_identifiers(
    organization_id: str,
    global_id: Union[str, List[str]],
    output_dir: Optional[str] = None,
    batch_size: int = 30,
    max_workers: int = 5,
) -> str:
    """
    Query specific global identifiers for an organization using the
    GlobalIdentifierFilter, and flatten the nested response into a CSV.

    Args:
        organization_id: Dewrangle organization ID
        global_id: A single globalId or a list of globalIds to look up
        output_dir: Optional directory to save the CSV
        batch_size: Number of globalIds to query per GraphQL request (default 30)
        max_workers: Number of parallel GraphQL requests (default 5)

    Returns:
        Path to the saved CSV file
    """
    if isinstance(global_id, str):
        target_ids = [global_id]
    else:
        target_ids = list(global_id)

    rows = asyncio.run(
        _download_filtered_org_global_identifiers_async(
            organization_id, target_ids, batch_size, max_workers
        )
    )

    columns = [
        "globalId",
        "studyGlobalId",
        "studyName",
        "fhirResourceType",
        "descriptor",
        "descriptorState",
        "globalIdCreatedAt",
        "globalIdCreatedBy",
        "descriptorCreatedAt",
        "descriptorCreatedBy",
    ]
    df = pd.DataFrame(rows, columns=columns)

    # Keep only the latest descriptorState per (globalId, descriptor),
    # matching the behavior of the REST organization report.
    if not df.empty:
        df["_descriptorCreatedAt_dt"] = pd.to_datetime(
            df["descriptorCreatedAt"], errors="coerce"
        )
        df = df.sort_values(
            by=["globalId", "descriptor", "_descriptorCreatedAt_dt"],
            ascending=[True, True, False],
            na_position="last",
        )
        df = df.drop_duplicates(subset=["globalId", "descriptor"], keep="first")
        df = df.drop(columns=["_descriptorCreatedAt_dt"])
        df = df.reset_index(drop=True)

    output_dir = output_dir or ROOT_DATA_DIR
    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M")

    if len(target_ids) == 1:
        filename = f"dewrangle-global-id-{target_ids[0]}-{timestamp}.csv"
    else:
        filename = f"dewrangle-global-ids-{len(target_ids)}-filtered-{timestamp}.csv"

    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    print(f"📥 Filtered global identifiers report saved at: {filepath}")
    return filepath


def wait_for_job(
    job_id: str,
    poll_interval: int = 5,
    max_wait: int = 300,
) -> None:
    """
    Poll a Dewrangle job until it completes or times out.

    Args:
        job_id: Dewrangle job ID
        poll_interval: seconds between polls
        max_wait: maximum total seconds to wait
    """
    waited = 0
    while waited < max_wait:
        resp = exec_graphql_query(GET_JOB, {"id": job_id})
        job = resp.get("node", {})
        completed_at = job.get("completedAt")

        if completed_at:
            print(f"✅ Job completed at {completed_at}")
            return

        print(f"⏳ Job not complete. Waiting {poll_interval}s...")
        time.sleep(poll_interval)
        waited += poll_interval

    raise TimeoutError(
        f"Job {job_id} did not complete within {max_wait}s. "
        "Please check the job status in Dewrangle and try again."
    )


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

    # Wait for the upsert job to finish before downloading the report
    wait_for_job(job_id)
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
    raise_on_empty_report: bool = True,
) -> Optional[str]:
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
        raise_on_empty_report: If False, return None when the job report is empty
                               instead of raising TimeoutError.

    Returns:
        Path to the downloaded report CSV, or None if the report was empty and
        raise_on_empty_report is False.
    """
    file_id = upload_org_file(organization_id, manifest_path)
    job_id = create_org_global_ids(organization_id, file_id)
    try:
        report_path = download_job_report(job_id, organization_id, output_dir=output_dir)
    except TimeoutError as e:
        if raise_on_empty_report:
            raise
        print(
            "⚠️ Dewrangle job report is empty; skipping job report download. "
            "Will fall back to downloading the organization global identifiers report."
        )
        return None
    return report_path


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
        max_wait=180
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
    page_size: int = 100,
    max_pages: int = 100,
) -> Optional[dict]:
    """
    Check if a study with the given name already exists in Dewrangle.
    Paginates through studies until the study is found or all pages are exhausted.

    Args:
        organization_id: Org ID
        study_name: Name of the study to look up
        page_size: Number of studies per GraphQL page
        max_pages: Maximum pages to fetch before giving up

    Returns:
        Study dict with keys: id, name, globalId if found, else None.
    """
    after = None
    for page in range(1, max_pages + 1):
        variables = {
            "organization_id": organization_id,
            "first": page_size,
        }
        if after:
            variables["after"] = after

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
        page_info = studies_conn.get("pageInfo", {})

        for edge in edges:
            study = edge.get("node")
            if study and study.get("name") == study_name:
                print(f"🔍 Found existing study '{study_name}' in Dewrangle (globalId: {study['globalId']}) on page {page}")
                return study

        if not page_info.get("hasNextPage"):
            break

        after = page_info.get("endCursor")

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
