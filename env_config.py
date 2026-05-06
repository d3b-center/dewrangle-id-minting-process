import os

config = {
    "dewrangle": {
        "dev_token": os.environ.get("DEWRANGLE_TOKEN"),
        "base_url": os.environ.get("DEWRANGLE_BASE_URL"),
        "pagination": {"max_page_size": 10},
        "client": {"execution_timeout": 30},  # seconds
        "endpoints": {
            "graphql": "/api/graphql",
            "job_rest": {
                "identifiers_report": "/api/rest/organizations/{org_id}/global-identifiers?job={job_id}",
            },
            "org_rest":{
                 "identifiers_report": "/api/rest/organizations/{org_id}/global-identifiers",
            }
        },
    },
    "db": {
        "d3b_warehouse": {
            "db_host": os.environ.get("D3B_WAREHOUSE_HOST", "localhost"),
            "db_port": os.environ.get("D3B_WAREHOUSE_PORT", "5432"),
            "db_name": os.environ.get("D3B_WAREHOUSE_DB_NAME", "postgres"),
            "db_user": os.environ.get("D3B_WAREHOUSE_DB_USER", "postgres"),
            "db_password": os.environ.get(
                "D3B_WAREHOUSE_DB_USER_PW", "postgres"
            ),
            "dewrangle_ids": {
                "schema": os.environ.get("D3B_WAREHOUSE_DEWRANGLE_IDS_SCHEMA"),
                "table": os.environ.get("D3B_WAREHOUSE_DEWRANGLE_IDS_TABLE"),
                "primary_key_cols": ["globalId", "studyGlobalId", "descriptor", "descriptorState"],
            },
            "data_transfer_file_mapping": {
                "schema": os.environ.get("D3B_WAREHOUSE_DATA_TRANSFER_RECORD_SCHEMA"),
                "table": os.environ.get("D3B_WAREHOUSE_DATA_TRANSFER_RECORD_TABLE"),
                "primary_key_cols": ["global_id"],
            },
            "source_study_metadata": {
                "schema": os.environ.get("D3B_WAREHOUSE_STUDY_SOURCE_SCHEMA"),
                "table": os.environ.get("D3B_WAREHOUSE_STUDY_SOURCE_TABLE"),
                "primary_key_cols": ["study_name", "program"],
            },
            "source_sample_metadata": {
                "schema": os.environ.get("D3B_WAREHOUSE_SAMPLE_SOURCE_SCHEMA"),
                "table": os.environ.get("D3B_WAREHOUSE_SAMPLE_SOURCE_TABLE"),
                "primary_key_cols": ["study_id", "case_id", "sample_id", "aliquot_id"],
            },
            "cbtn_samples": {
                "schema": "prod_access",
                "specimen_table": "specimen",
                "participant_table": "participants",
            },
        },
    },
}