# Dewrangle ID Minting Process

This repository supports the end-to-end **Dewrangle ID minting process** study, sample, and file intake workflows for:
- **CBTN project**
- **D3b non-CBTN projects**
- **Kids First and INCLUDE projects**

The workflows support:
- Source metadata intake into the Data Warehouse (DWH)
- Dewrangle global ID minting
- Source file registration
- Harmonized file registration

| Project Type | Description |
|---|---|
| CBTN Projects | CBTN project where participant and specimen metadata already exists in the D3b DWH `prod_access` schema. These workflows primarily focus on Dewrangle ID minting. |
| D3b non-CBTN Projects | Other D3b-managed projects that require study and sample metadata ingestion into the D3b DWH before Dewrangle ID minting. |
| Kids First & INCLUDE Projects | Clinical/sample metadata are maintained in the DCC DWH. Depending on whether metadata already exists in the DCC DWH, workflows may include metadata intake and/or Dewrangle ID minting. |
| All Projects | Shared workflows for source file intake and harmonized file intake across all project types. |

## Overview
![Data Flow](docs/dewrangle-id-minting-process.jpg)



## Pre-setup
Before running any workflow:
- Configure all required database credentials and Dewrangle credentials in the `env_setting` file.
- Load the environment variables.
  ```bash
  # Load environment configuration
  source env_setting
  ```

## 1. CBTN Sample ID Minting Process
This process is designed specifically for CBTN data. It assumes that participant and specimen metadata already exist in the D3b DWH:
- `prod_access.participants`
- `prod_access.specimen`
  
### Step 1: Prepare Input Manifest
Create a manifest using the CBTN sample & participants template: [`manifests/cbtn_sample_participants.csv`](manifests/cbtn_sample_participants.csv)

**Required fields:**
| Minting Type | Required Fields |
|---|---|
| Participant ID Minting | `case_id` |
| Specimen ID Minting | `sample_id`, `aliquot_id` |
| Both | `case_id`, `sample_id`, `aliquot_id` |
  
### Step 2: Validate Inputs and Prepare ID Minting Manifest
```bash
python  prepare_cbtn_samples_id_mint.py \
	--manifest manifests/cbtn_sample_participants.csv \
	--type both
```
**Functionality**
- Validate whether participant and specimen records already exist in the D3b DWH
- Check whether records already have minted IDs in the D3b DWH
- If not:
  - Generate manifests (if applicable):
    - `cbtn_participants_specimens_to_mint.csv` (ready for ID minting)
    - `cbtn_participants_specimens_minted_in_dwh.csv` (alreay minted samples)
    - `cbtn_participants_missing_in_dwh.csv` (case_id not found in the D3b dwh)
    - `cbtn_specimens_missing_in_dwh.csv`  (sample_id, aliquot_id not found in the D3b dwh)

### Step 3: Run Sample ID Minting
Use either:
- The output manifest from Step 2, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - Participant: `descriptor = case_id || ';' || study_id`
  - Specimen: `descriptor = aliquot_id || ';' || study_id`

```bash
python org_globalids_mint.py \
--env qa \
--db_type d3b \
--manifest cbtn_participants_specimens_to_mint.csv
```

| Argument | Description |
|----------|-------------|
| `--env` | Environment for ID minting. Determines which Dewrangle organization ID is used if `--organization_id` is not set. Options: <br>• `prod` → Uses the KF production Dewrangle organization for minting IDs. <br>• `qa` → Uses the test Dewrangle organization for testing purposes. |
| `--db_type` | Database warehouse type (d3b or dcc). Ddetermines which warehouse connection and source metadata tables are used. |
| `--manifest` | Path to the input manifest CSV file. |
| `--organization_id` | *(Optional)* Explicit Dewrangle organization ID to use. Overrides the `--env` default if provided. |

**Output**:
- Dewrangle study IDs are generated
- Dewrangle report is saved into the D3b DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`

---

## 2. D3b Non-CBTN Projects Intake Process
This workflow supports non-CBTN D3b-managed projects.
The workflow includes:
  - Study Intake
  - Sample Intake
  - Dewrangle ID Minting

### 2.1 Study Intake Process

##### Step 1: Prepare Input Study Manifest
Create a manifest useing the study manifest template: [`manifests/study_manifest_template.csv`](manifests/study_manifest_template.csv)

**Required fields:**
- study_name
- program

##### Step 2: Ingest Study Metadata into the D3b DWH
```bash
# save study manifest
python source_metadata_intake.py \
--env qa \
--db_type d3b \
--source_type study \
--manifest test_data/test_study_manifest.csv
```

**Functionality**
- Check whether study records already have minted IDs in the D3b DWH
- If not:
  - Save study metadata into the D3b DWH:
    - (test)  `huangx_dev_schema_dgd_workflow.src_study_manifests`
    - (prod)  `src_d3b_file_mgmt_manifests.src_study_manifests`
  - Generate a study manifest for ID minting:
    - `study_metadata_for_id_minting.csv`

Example Logs:
```
2026-05-03 03:59:26 | INFO | ✅ Insert 2 rows into huangx_dev_schema_dgd_workflow.src_study_manifests
2026-05-03 03:59:26 | INFO | ✅ Generated study_metadata_for_id_minting.csv for dewrangle ID minting.
```

##### Step 3: Run Study ID Minting
Prepare study ID minting manifest, use either:
- The output manifest from step 2, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - `fhirResourceType = 'ResearchStudy'`

**Run**:
```bash
# study id minting
python org_globalids_mint.py \
--env qa \
--db_type d3b \
--manifest study_metadata_for_id_minting.csv
```

**Output**:
- Dewrangle study IDs are generated
- Dewrangle report is saved into the D3b DWH
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
### 2.2 Sample Intake Process

##### Step 1: Prepare Input Sample Manifest

Create a manifest using the sample template: [`manifests/sample_manifest_template.csv`](manifests/sample_manifest_template.csv)

Required fields:
`Required_fields = ["study_id", "case_id", "sample_id", "aliquot_id"]`

- `case_id` will be used for participant id minting
- `aliquot_id` will be used for biospecimen id minting


##### Step 2: Ingest Sample Metadata into the D3b DWH
```bash
# save sample manifest
python source_metadata_intake.py \
--env qa \
--db_type d3b \
--source_type sample \
--manifest test_data/test_sample_manifest.csv
```

**Functionality**
- Check whether sample records already have minted IDs in the D3b DWH
- If not:
  - Save sample metadata into the D3b DWH:
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
##### Step 3: Run Sample ID Minting
Prepare sample ID minting manifest, use either:
- Output from step 2, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - **Paticipant ID minting:** 
    - `fhirResourceType = 'Patient'`
    - `descriptor = case_id || ';' || study_id`
  - **Biospecimen ID minting: **
    - `ffhirResourceType = 'Specimen'`
    - `descriptor = aliquot_id || ';' || study_id`

**⚠️ Note:** Include `study_id` in the descriptor to ensure the correct study can always be identified, especially when the same `case_id` or `aliquot_id` appears across different studies.

**Run**:

```bash
# sample id minting
python org_globalids_mint.py \
--env qa \
--db_type d3b \
--manifest sample_metadata_for_id_minting.csv
```

Output:
- Dewrangle sample IDs are generated
- Dewrangle report is saved into the D3b DWH
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

## 3. Kids First and INCLUDE Project Intake Process
This workflow supports Kids First and INCLUDE projects using the DCC DWH.
The workflow depends on whether participant/specimen metadata already exists in the DCC DWH.

### 3.1 Study Intake Process

##### Step 1: Prepare Input Study Manifest
Create a manifest useing the study manifest template: [`manifests/study_manifest_template.csv`](manifests/study_manifest_template.csv)

**Required fields:**
- study_name
- program

##### Step 2: Ingest Study Metadata into the DCC DWH
```bash
# save study manifest
python source_metadata_intake.py \
--env qa \
--db_type dcc \
--source_type study \
--manifest test_data/test_study_manifest.csv
```

**Functionality**
- Check whether study records already have minted IDs in the DCC DWH
- If not:
  - Save study metadata into the DCC DWH:
  - Generate a study manifest for ID minting:
    - `study_metadata_for_id_minting.csv`


##### Step 3: Run Study ID Minting
Prepare sample ID minting manifest, use either:
- Output from step 2, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - `fhirResourceType = 'ResearchStudy'`

**Run**
```bash
# study id minting
python org_globalids_mint.py \
--env qa \
--db_type dcc \
--manifest study_metadata_for_id_minting.csv
```

**Output**:
- Dewrangle study IDs are generated
- Dewrangle report is saved into the DCC DWH
  
### 3.2 Sample Intake Process

#### Scenario A — Sample Metadata Already Exists in the DCC DWH
- Skip sample metadata ingestion step
- Proceed directly to `Step 3: Run Sample ID minting`

#### Scenario B — Sample Metadata Does NOT Exist in the DCC DWH
- Perform sample metadata ingestion into the DCC DWH
- Then proceed to the Dewrangle Sample ID Minting Process

##### Step 1: Prepare Input Sample Manifest
Create a manifest using the sample template: [`manifests/sample_manifest_template.csv`](manifests/sample_manifest_template.csv)

Required fields:
`Required_fields = ["study_id", "case_id", "sample_id", "aliquot_id"]`


##### Step 2: Ingest Sample Metadata into the DCC DWH
```bash
# save sample manifest
python source_metadata_intake.py \
--env qa \
--db_type d3b \
--source_type sample \
--manifest test_data/test_sample_manifest.csv
```

**Functionality**
- Check whether sample records already have minted IDs in the D3b DWH
- If not:
  - Save sample metadata into the D3b DWH:
    - (test)  `huangx_dev_schema_dgd_workflow.src_sample_manifests`
    - (prod)  `src_d3b_file_mgmt_manifests.src_sample_manifests`
  - Generate a sample manifest for ID minting:
    - `sample_metadata_for_id_minting.csv`
      - `descriptor = case_id || ';' || study_id`
      - `descriptor = aliquot_id || ';' || study_id`


##### Step 3: Run Sample ID minting
Prepare sample ID minting manifest, use either:
- Output from step 2, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - **Paticipant ID minting:** 
    - `fhirResourceType = 'Patient'`
    - `descriptor = case_id || ';' || study_id`
  - **Biospecimen ID minting: **
    - `ffhirResourceType = 'Specimen'`
    - `descriptor = aliquot_id || ';' || study_id`

**⚠️ Note:** Include `study_id` in the descriptor to ensure the correct study can always be identified, especially when the same `case_id` or `aliquot_id` appears across different studies.

**Run**

```bash
# sample id minting
python org_globalids_mint.py \
--env qa \
--db_type dcc \
--manifest sample_metadata_for_id_minting.csv
```

Output:
- Dewrangle sample IDs are generated
- Dewrangle report is saved into the DCC DWH


## 4. File Intake Process (All Projects)
All file metadata is ingested and stored in the **D3b Data Warehouse (DWH)**, regardless of project type (CBTN, D3b non-CBTN, or Kids First & INCLUDE).

### 4.1 Source File Intake Process

#### Step 1: Run DFF Data Transfer Pipeline
- Refer to the [d3b-data-transfer-pipeline](https://github.com/d3b-center/d3b-data-transfer-pipeline) repository for detailed instructions.

Output:
- File metadata is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.src_file_manifests`
  - (prod)  `src_d3b_file_mgmt_manifests.{src_file_manifests_xxx}`


#### Step 2: Dewrangle Source File ID Minting
Create a manifest useing the source file manifest template: [`manifests/dewrangle_id_minting_source_files.csv`](`manifests/dewrangle_id_minting_source_files.csv)
- Required fields:
  - `study_id`
  - `file_name`
  - `dt_id`
  - `fhirResourceType`
  - `descriptor`
  - `descriptorState`

**Run**
```bash
# source file id minting
python org_globalids_mint.py \
--env qa \
--db_type d3b \
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
### 4.2 Harmonized File Intake Process

##### Step 1: Prepare harmonized data input manifest
- Create a manifest useing the harmonized file manifest template: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - `fhirResourceType = 'DoucmentReference'`

##### Step 2: Run ID minting

```bash
# harmonized file id minting
python org_globalids_mint.py \
--env qa \
--db_type d3b \
--manifest harmonized_file_id_minting.csv
```

Output:
- Dewrangle file IDs are generated
- Dewrangle report is saved into DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`
