# Dewrangle ID Minting Process

This repository supports the end-to-end **Dewrangle ID minting process** for studies, samples, and files, including metadata saved into the Data Warehouse (DWH) and generation of Dewrangle global identifiers.

## Overview
![Data Flow](docs/dewrangle-id-minting-process.jpg)

## Pre-setup
Before running the workflow, ensure your D3b Data Warehouse credentials are configured in the `env_setting` file, then run:
```bash
# Load environment configuration
source env_setting
```
## CBTN Sample ID Minting Process
This process is designed specifically for CBTN data. It assumes that participant and specimen metadata already exist in the Data Warehouse tables:
- `prod_access.participants`
- `prod_access.specimen`
  
### Step 1: Prepare Input Manifest
Create a manifest using the CBTN sample & participants template: [`manifests/cbtn_sample_participants.csv`](manifests/cbtn_sample_participants.csv)

**Required fields:**

- **Participant ID minting:** case_id
- **Specimen ID minting:** sample_id, aliquot_id
- **Both participant + specimen:** case_id, sample_id, aliquot_id
  
### Step 2: Validate Inputs and Prepare ID Minting Manifest
```bash
python  prepare_cbtn_samples_id_mint.py \
	--manifest manifests/cbtn_sample_participants.csv \
	--type both
```
**Functionality**
- Check whether participant and specimen records already exist in the DWH, and
- Check whether records already have minted IDs in the DWH
- If not:
  - Generate manifests (if applicable):
    - `cbtn_participants_specimens_to_mint.csv` (ready for ID minting)
    - `cbtn_participants_specimens_minted_in_dwh.csv` (alreay minted samples)
    - `cbtn_participants_missing_in_dwh.csv` (case_id not found in the dwh)
    - `cbtn_specimens_missing_in_dwh.csv`  (sample_id, aliquot_id not found in the dwh)

### Step 3: Run Sample ID Minting
Use either:
- The output manifest from Step 2, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - Participant: `descriptor = case_id || ';' || study_id`
  - Specimen: `descriptor = aliquot_id || ';' || study_id`

```bash
python org_globalids_mint.py \
--env qa \
--manifest cbtn_participants_specimens_to_mint.csv
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

---

## Non-CBTN Project Intake process
This process is used for all non-CBTN projects (i.e., other d3b studies that are not part of CBTN, Kids Frist projects). It supports study, sample, and file intake where metadata may need to be newly ingested into the Data Warehouse before ID minting.

### 1. Study Intake Process

#### 1.1 Save Study Metadata into the DWH

##### Step 1: Prepare input manifest
Create a manifest useing the study manifest template: [`manifests/study_manifest_template.csv`](manifests/study_manifest_template.csv)

**Required fields:**
- study_name
- program

##### Step 2: Save study metadata into the DWH
```bash
# save study manifest
python source_metadata_transfer.py \
--env qa \
--type study \
--manifest test_data/test_study_manifest.csv
```

**Functionality**
- Check whether study records already have minted IDs in the DWH
- If not:
  - Save study metadata into the DWH:
    - (test)  `huangx_dev_schema_dgd_workflow.src_study_manifests`
    - (prod)  `src_d3b_file_mgmt_manifests.src_study_manifests`
  - Generate a study manifest for ID minting:
    - `study_metadata_for_id_minting.csv`

Example Logs:
```
2026-05-03 03:59:26 | INFO | ✅ Insert 2 rows into huangx_dev_schema_dgd_workflow.src_study_manifests
2026-05-03 03:59:26 | INFO | ✅ Generated study_metadata_for_id_minting.csv for dewrangle ID minting.
```

#### 1.2 Dewrangle Study ID Minting Process
##### Step 1: Prepare ID minting manifest
Use either:
- The output manifest from Step 1.1, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - `fhirResourceType = 'ResearchStudy'`

##### Step 2: Run Study ID Minting
```bash
# study id minting
python org_globalids_mint.py \
--env qa \
--manifest study_metadata_for_id_minting.csv
```

**Output**:
- Dewrangle study IDs are generated
- Dewrangle report is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`

Example Logs:
```
🧪 Using test-dewrangle-ids organization for ID minting
✅ Manifest read successfully with 2 rows.
...
...
...
📥 Downloaded job global IDs report: /home/ubuntu/work/github/dewrangle-id-minting-process/data/dewrangle-job-globalids-20260503-0420.csv
🗂️ Saving dewrangle IDs report to DB...
✅ Insert completed for huangx_dev_schema_dgd_workflow.dewrangle_ids
🎉 All completed!
```
### 2. Sample Intake Process

#### 2.1 Save Sample Metadata into DWH

##### Step 1: Prepare input manifest

Create a manifest using the sample template: [`manifests/sample_manifest_template.csv`](manifests/sample_manifest_template.csv)

Required fields:
`Required_fields = ["study_id", "case_id", "sample_id", "aliquot_id"]`

- `case_id` will be used for participant id minting
- `aliquot_id` will be used for biospecimen id minting


##### Step 2: Save sample metadata into the DWH
```bash
# save sample manifest
python source_metadata_transfer.py \
--env qa \
--type sample \
--manifest test_data/test_sample_manifest.csv
```

**Functionality**
- Check whether sample records already have minted IDs in the DWH
- If not:
  - Save sample metadata into the DWH:
    - (test)  `huangx_dev_schema_dgd_workflow.src_sample_manifests`
    - (prod)  `src_d3b_file_mgmt_manifests.src_sample_manifests`
  - Generate a sample manifest for ID minting:
    - `sample_metadata_for_id_minting.csv`
      - `descriptor = case_id || ';' || study_id`
      - `descriptor = aliquot_id || ';' || study_id`

Example Logs:
```
2026-05-03 04:33:05 | INFO | ✅ Insert 5 rows into huangx_dev_schema_dgd_workflow.src_sample_manifests
2026-05-03 04:33:05 | INFO | ✅ Generated sample_metadata_for_id_minting.csv for dewrangle ID minting.
```

#### 2.2 Dewrangle Sample ID Minting Process

##### Step 1: Prepare ID minting manifest

Use either:
- Output from step 2.1, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - **Paticipant ID minting:** 
    - `fhirResourceType = 'Patient'`
    - `descriptor = case_id || ';' || study_id`
  - **Biospecimen ID minting: **
    - `ffhirResourceType = 'Specimen'`
    - `descriptor = aliquot_id || ';' || study_id`

**⚠️ Note:** Include `study_id` in the descriptor to ensure the correct study can always be identified, especially when the same `case_id` or `aliquot_id` appears across different studies.

##### Step 2: Run ID minting

```bash
# sample id minting
python org_globalids_mint.py \
--env qa \
--manifest sample_metadata_for_id_minting.csv
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
...
...
...
📥 Downloaded job global IDs report: /home/ubuntu/work/github/dewrangle-id-minting-process/data/dewrangle-job-globalids-20260503-0526.csv
🗂️ Saving dewrangle IDs report to DB...
✅ Insert completed for huangx_dev_schema_dgd_workflow.dewrangle_ids
🎉 All completed!
```

### 3. Source File Intake Process

#### 3.1 Run DFF Data Transfer Pipeline
- Refer to the [d3b-data-transfer-pipeline](https://github.com/d3b-center/d3b-data-transfer-pipeline) repository for detailed instructions.

Output:
- File metadata is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.src_file_manifests`
  - (prod)  `src_d3b_file_mgmt_manifests.{src_file_manifests_xxx}`


#### 3.2 Dewrangle Source File ID Minting Process

##### Step 1: Prepare input manifest
- Create a manifest useing the source file manifest template: [`manifests/dewrangle_id_minting_source_files.csv`](`manifests/dewrangle_id_minting_source_files.csv)
  - Required fields:
    - `study_id`
    - `file_name`
    - `dt_id`
    - `fhirResourceType`
    - `descriptor`
    - `descriptorState`

##### Step 2: Run file ID minting

```bash
# source file id minting
python org_globalids_mint.py \
--env qa \
--save-dt-record \
--manifest test_data/source_file_metadata_for_id_minting.csv
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
...
...
...
📥 Downloaded job global IDs report: /home/ubuntu/work/github/dewrangle-id-minting-process/data/dewrangle-job-globalids-20260503-0601.csv
🗂️ Saving dewrangle IDs report to DB...
✅ Insert completed for huangx_dev_schema_dgd_workflow.dewrangle_ids
🗂️ Saving Data Transfer Records to DB...
✅ Insert completed for huangx_dev_schema_dgd_workflow.data_transfer_file_mapping
🎉 All completed!
```
### 4. Harmonized File Intake Process

##### Step 1: Prepare input manifest
- Create a manifest useing the harmonized file manifest template: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - `fhirResourceType = 'DoucmentReference'`

##### Step 2: Run ID minting

```bash
# harmonized file id minting
python org_globalids_mint.py \
--env qa \
--manifest harmonized_file_id_minting.csv
```

Output:
- Dewrangle file IDs are generated
- Dewrangle report is saved into DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`
