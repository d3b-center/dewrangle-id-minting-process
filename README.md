# Dewrangle ID Minting Process

This repository supports the end-to-end **Dewrangle ID minting process** for studies, samples, and files, including metadata saved into the Data Warehouse (DWH) and generation of Dewrangle global identifiers.

## Overview
![Data Flow](docs/dewrangle-id-minting-process.jpg)

## 1. Study Intake Process

### 1.1 Save Study Metadata into the DWH

#### Step 1: Prepare input manifest
Create a manifest useing the study manifest template: [`manifests/study_manifest_template.csv`](manifests/study_manifest_template.csv)

**Required fields:**
- study_name
- program

#### Step 2: Save study metadata into the DWH
```bash
# load env config
source env_setting

# save study manifest
python save_source_metadata.py --type study test_data/test_study_manifest.csv
```

Output:
- Study metadata is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.src_study_manifests`
  - (prod)  `src_d3b_file_mgmt_manifests.src_study_manifests`
- A study manifest for ID minting is generated:
  - `study_metadata_for_id_minting.csv`

Example Logs:
```
2026-05-03 03:59:26 | INFO | ✅ Insert 2 rows into huangx_dev_schema_dgd_workflow.src_study_manifests

2026-05-03 03:59:26 | INFO | ✅ Generated study_metadata_for_id_minting.csv for dewrangle ID minting.
```

### 1.2 Dewrangle Study ID Minting Process
#### Step 1: Prepare ID minting manifest
Use either:
- The output manifest from Step 1.1, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - `fhirResourceType = 'ResearchStudy'`

#### Step 2: Run Study ID Minting
```bash
# load env config
source env_setting

# study id minting
python org_globalids_mint.py --env qa --manifest study_metadata_for_id_minting.csv
```

| Argument | Description |
|----------|-------------|
| `--env` | Environment for ID minting. Determines which Dewrangle organization ID is used if `--organization_id` is not set. Options: <br>• `prod` → Uses the KF production Dewrangle organization for minting IDs. <br>• `qa` → Uses the test Dewrangle organization for testing purposes. |
| `--manifest` | Path to the input manifest CSV file. |
| `--organization_id` | *(Optional)* Explicit Dewrangle organization ID to use. Overrides the `--env` default if provided. |

**Output**:
- Dewrangle study IDs are generated
- Dewrangle report is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`

Example Logs:
```
🧪 Using test-dewrangle-ids organization for ID minting
✅ Manifest read successfully with 2 rows.
🔗 Upload URL: https://dewrangle.com/api/rest/organizations/T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA=/files/study_metadata_for_id_minting.csv
🆔 Uploaded file ID: T3JnYW5pemF0aW9uRmlsZTowMTlkZWMxMC04YThlLTc1NWItYTU2MS0wOTQxNGQyMzE0MTU=
✅ Uploaded file 'study_metadata_for_id_minting.csv' to organization successfully!
🚀 Job submitted: Sm9iOmNtb3A5aTJ2ZTAwMGtsaDAxaXU1azAxZXg=
Waiting for job to complete...
✅ Job completed at: None
🌐 Dewrangle job global-identifiers report URL:  https://dewrangle.com//api/rest/organizations/T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA=/global-identifiers?job=Sm9iOmNtb3A5aTJ2ZTAwMGtsaDAxaXU1azAxZXg=
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
📥 Downloaded job global IDs report: /home/ubuntu/work/github/dewrangle-id-minting-process/data/dewrangle-job-globalids-20260503-0420.csv
🗂️ Saving dewrangle IDs report to DB...
✅ Insert completed for huangx_dev_schema_dgd_workflow.dewrangle_ids
🎉 All completed!
```
## 2. Sample Intake Process

### 2.1 Save Sample Metadata into DWH

#### Step 1: Prepare input manifest

Create a manifest using the sample template: [`manifests/sample_manifest_template.csv`](manifests/sample_manifest_template.csv)

Required fields:
`Required_fields = ["study_id", "case_id", "sample_id", "aliquot_id"]`

- `case_id` will be used for participant id minting
- `aliquot_id` will be used for biospecimen id minting


#### Step 2: Save sample metadata into the DWH
```bash
# load env config
source env_setting

# save sample manifest
python save_source_metadata.py --type sample --manifest test_data/test_sample_manifest.csv
```

Output:
- Study metadata is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.src_sample_manifests`
  - (prod)  `src_d3b_file_mgmt_manifests.src_sample_manifests`
- A study manifest for ID minting is generated:
  - `sample_metadata_for_id_minting.csv`
    - `descriptor = case_id || ';' || study_id`
    - `descriptor = aliquot_id || ';' || study_id`

Example Logs:
```
2026-05-03 04:33:05 | INFO | ✅ Insert 5 rows into huangx_dev_schema_dgd_workflow.src_sample_manifests

2026-05-03 04:33:05 | INFO | ✅ Generated sample_metadata_for_id_minting.csv for dewrangle ID minting.
```

### 2.2 Dewrangle Sample ID Minting Process

#### Step 1: Prepare ID minting manifest

Use either:
- Output from step 2.1, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - Paticipant ID minting: 
    - `fhirResourceType = 'Patient'`
    - `descriptor = case_id || ';' || study_id`
  - Biospecimen ID minting: 
    - `ffhirResourceType = 'Specimen'`
    - `descriptor = aliquot_id || ';' || study_id`

#### Step 2: Run ID minting

```bash
# load env config
source env_setting

# sample id minting
python org_globalids_mint.py --env qa --manifest sample_metadata_for_id_minting.csv
```

Output:
- Dewrangle sample IDs are generated
- Dewrangle report is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`

Example Logs:
```
🧪 Using test-dewrangle-ids organization for ID minting
✅ Manifest read successfully with 9 rows.
🔗 Upload URL: https://dewrangle.com/api/rest/organizations/T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA=/files/sample_metadata_for_id_minting.csv
🆔 Uploaded file ID: T3JnYW5pemF0aW9uRmlsZTowMTlkZWM0ZC0xOTUwLTc1MGUtOGVjNC1lYzM3NzY1NzFjMWE=
✅ Uploaded file 'sample_metadata_for_id_minting.csv' to organization successfully!
🚀 Job submitted: Sm9iOmNtb3BidjUzeTAwMG1saDAxa2xybnN0MDE=
Waiting for job to complete...
✅ Job completed at: None
🌐 Dewrangle job global-identifiers report URL:  https://dewrangle.com//api/rest/organizations/T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA=/global-identifiers?job=Sm9iOmNtb3BidjUzeTAwMG1saDAxa2xybnN0MDE=
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
📥 Downloaded job global IDs report: /home/ubuntu/work/github/dewrangle-id-minting-process/data/dewrangle-job-globalids-20260503-0526.csv
🗂️ Saving dewrangle IDs report to DB...
✅ Insert completed for huangx_dev_schema_dgd_workflow.dewrangle_ids
🎉 All completed!
```

## 3. Source File Intake Process

### 3.1 Run DFF Data Transfer Pipeline
- Refer to the [d3b-data-transfer-pipeline](https://github.com/d3b-center/d3b-data-transfer-pipeline) repository for detailed instructions.

Output:
- File metadata is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.src_file_manifests`
  - (prod)  `src_d3b_file_mgmt_manifests.{src_file_manifests_xxx}`


### 3.2 Dewrangle Source File ID Minting Process

#### Step 1: Prepare input manifest
- Create a manifest useing the source file manifest template: [`manifests/dewrangle_id_minting_source_files.csv`](`manifests/dewrangle_id_minting_source_files.csv)
  - Required fields:
    - `study_id`
    - `file_name`
    - `dt_id`
    - `fhirResourceType`
    - `descriptor`
    - `descriptorState`

#### Step 2: Run file ID minting

```bash
# load env config
source env_setting

# source file id minting
python org_globalids_mint.py --env qa --save-dt-record --manifest test_data/source_file_metadata_for_id_minting.csv 
```

| Argument | Description |
|----------|-------------|
| `--save-dt-record` | Only required for source file ID minting, saves the data transfer mapping record to the DWH. |

Output:
- Dewrangle file IDs are generated
- Dewrangle report is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`
- Source data transfer mapping records are saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.data_transfer_file_mapping`
  - (prod)  `src_dewrangle_identifiers.data_transfer_file_mapping`

Example Logs:
```
🧪 Using test-dewrangle-ids organization for ID minting
✅ Manifest read successfully with 6 rows.
🔗 Upload URL: https://dewrangle.com/api/rest/organizations/T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA=/files/source_file_metadata_for_id_minting.csv
🆔 Uploaded file ID: T3JnYW5pemF0aW9uRmlsZTowMTlkZWM2Yy1mMmJlLTc3NWEtOWZlYS1kNzRmMjBkZDhkMzk=
✅ Uploaded file 'source_file_metadata_for_id_minting.csv' to organization successfully!
🚀 Job submitted: Sm9iOmNtb3BkM3ZuejAwMG9saDAxc3NlbzduYmI=
Waiting for job to complete...
✅ Job completed at: None
🌐 Dewrangle job global-identifiers report URL:  https://dewrangle.com//api/rest/organizations/T3JnYW5pemF0aW9uOmNta2x6ejhleDAwMWxqejAxNHQyOWl1ZXA=/global-identifiers?job=Sm9iOmNtb3BkM3ZuejAwMG9saDAxc3NlbzduYmI=
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
⏳ Response empty. Waiting 5s...
📥 Downloaded job global IDs report: /home/ubuntu/work/github/dewrangle-id-minting-process/data/dewrangle-job-globalids-20260503-0601.csv
🗂️ Saving dewrangle IDs report to DB...
✅ Insert completed for huangx_dev_schema_dgd_workflow.dewrangle_ids
🗂️ Saving Data Transfer Records to DB...
✅ Insert completed for huangx_dev_schema_dgd_workflow.data_transfer_file_mapping
🎉 All completed!
```
## 4. Harmonized File Intake Process

#### Step 1: Prepare input manifest
- Create a manifest useing the harmonized file manifest template: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - `fhirResourceType = 'DoucmentReference'`

#### Step 2: Run ID minting

```bash
# load env config
source env_setting

# harmonized file id minting
python org_globalids_mint.py --env qa --manifest harmonized_file_id_minting.csv
```

Output:
- Dewrangle file IDs are generated
- Dewrangle report is saved into DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`
