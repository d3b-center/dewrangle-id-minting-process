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
python save_source_metadata.py --type study --manifest study_manifest.csv
```

Output:
- Study metadata is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.src_study_manifests`
  - (prod)  `src_d3b_file_mgmt_manifests.src_study_manifests`
- A study manifest for ID minting is generated:
  - `study_metadata_for_id_minting.csv`

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
python org_globalids_mint.py --manifest study_id_minting.csv
```

Output:
- Dewrangle study IDs are generated
- Dewrangle report is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`

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
python save_source_metadata.py --type sample --manifest sample_manifest.csv
```

Output:
- Study metadata is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.src_sample_manifests`
  - (prod)  `src_d3b_file_mgmt_manifests.src_sample_manifests`
- A study manifest for ID minting is generated:
  - `sample_metadata_for_id_minting.csv`

### 2.2 Dewrangle Sample ID Minting Process

#### Step 1: Prepare ID minting manifest

Use either:
- Output from step 2.1, or
- A manually prepared manifest based on: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - Paticipant ID minting: `fhirResourceType = 'Patient'`
  - Biospecimen ID minting: `ffhirResourceType = 'Specimen'`

#### Step 2: Run ID minting

```bash
# load env config
source env_setting

# sample id minting
python org_globalids_mint.py --manifest sample_id_minting.csv
```

Output:
- Dewrangle sample IDs are generated
- Dewrangle report is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`

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
python org_globalids_mint.py --manifest source_file_id_minting.csv --save-dt-record
```

Output:
- Dewrangle file IDs are generated
- Dewrangle report is saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`
- Source data transfer mapping records are saved into the DWH
  - (test)  `huangx_dev_schema_dgd_workflow.data_transfer_file_mapping`
  - (prod)  `src_dewrangle_identifiers.data_transfer_file_mapping`

## 4. Harmonized File Intake Process

#### Step 1: Prepare input manifest
- Create a manifest useing the harmonized file manifest template: [`manifests/dewrangle_id_minting_manifest.csv`](manifests/dewrangle_id_minting_manifest.csv)
  - `fhirResourceType = 'DoucmentReference'`

#### Step 2: Run ID minting

```bash
# load env config
source env_setting

# harmonized file id minting
python org_globalids_mint.py --manifest harmonized_file_id_minting.csv
```

Output:
- Dewrangle file IDs are generated
- Dewrangle report is saved into DWH
  - (test)  `huangx_dev_schema_dgd_workflow.dewrangle_ids`
  - (prod)  `src_dewrangle_identifiers.dewrangle_ids`
