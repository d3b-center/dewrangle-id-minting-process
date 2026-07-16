"""
d3b-dewrangle CLI
=================
A unified command-line interface for Dewrangle ID minting workflows.

Subcommands:
  source-intake     Ingest study or sample metadata into the DWH
  global-id-mint    Mint org-level global IDs from a manifest
  global-id-check   Query a specific global ID and download its record
  global-id-update  Update specific global ID records from a manifest
  study-create      Create a Kids First study in Dewrangle
  cbtn-prepare      Validate CBTN data and prepare a minting manifest

Usage examples:
  d3b-dewrangle source-intake --env qa --db d3b --source_type sample --manifest sample.csv
  d3b-dewrangle global-id-mint --env qa --db d3b --manifest manifest.csv --save-dt-record
  d3b-dewrangle global-id-check --env qa --id sd-xxxxxx
  d3b-dewrangle global-id-update --env qa --db d3b --manifest update.csv
  d3b-dewrangle study-create --env qa --db dcc --study-name "My Study"
  d3b-dewrangle cbtn-prepare --manifest cbtn.csv --type both

For full documentation, see README.md.
"""

import sys
import subprocess
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_script(name: str, args: List[str]) -> None:
    """Run a script from the project root with the given CLI args."""
    cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / name), *args]
    print(f"\n▶️  {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"❌ Command failed: {name}")


def add_common_args(parser):
    """Add arguments shared by most subcommands."""
    parser.add_argument("--env", choices=["prod", "qa"], required=True, help="Environment")
    parser.add_argument("--db", choices=["d3b", "dcc"], required=True, help="Database type")
    parser.add_argument("--organization-id", default=None, help="Override Dewrangle organization ID")
    parser.add_argument("--output-dir", default=None, help="Directory for downloaded reports")


def build_common_args(args) -> List[str]:
    """Build shared CLI arguments for underlying scripts."""
    out = ["--env", args.env, "--db", args.db]
    if args.organization_id:
        out.extend(["--organization_id", args.organization_id])
    if args.output_dir:
        out.extend(["--output_dir", args.output_dir])
    return out


# ---------------------------------------------------------------------------
# source-intake
# ---------------------------------------------------------------------------
def cmd_source_intake(args):
    """source-intake → source_metadata_intake.py"""
    run_script(
        "source_metadata_intake.py",
        [*build_common_args(args), "--source_type", args.type, "--manifest", args.manifest],
    )


# ---------------------------------------------------------------------------
# global-id-mint
# ---------------------------------------------------------------------------
def cmd_global_id_mint(args):
    """global-id-mint → org_globalids_mint.py"""
    script_args = [*build_common_args(args), "--manifest", args.manifest]
    if args.save_dt_record:
        script_args.append("--save-dt-record")
    if args.create_dewrangle_ids_table:
        script_args.append("--create-dewrangle-ids-table")
    if args.verbose:
        script_args.append("--verbose")
    run_script("org_globalids_mint.py", script_args)


# ---------------------------------------------------------------------------
# global-id-check
# ---------------------------------------------------------------------------
def cmd_global_id_check(args):
    """global-id-check → global_id_check.py"""
    script_args = ["--id", args.id]
    if args.env:
        script_args.extend(["--env", args.env])
    if args.organization_id:
        script_args.extend(["--organization-id", args.organization_id])
    if args.output_dir:
        script_args.extend(["--output-dir", args.output_dir])
    run_script("global_id_check.py", script_args)


# ---------------------------------------------------------------------------
# global-id-update
# ---------------------------------------------------------------------------
def cmd_global_id_update(args):
    """global-id-update → global_id_update.py"""
    script_args = [*build_common_args(args), "--manifest", args.manifest]
    run_script("global_id_update.py", script_args)


# ---------------------------------------------------------------------------
# study-create
# ---------------------------------------------------------------------------
def cmd_study_create(args):
    """study-create → create_dewrangle_kf_study.py"""
    run_script(
        "create_dewrangle_kf_study.py",
        [*build_common_args(args), "--study-name", args.study_name],
    )


# ---------------------------------------------------------------------------
# cbtn-prepare
# ---------------------------------------------------------------------------
def cmd_cbtn_prepare(args):
    """cbtn-prepare → prepare_cbtn_sample_id_mint.py"""
    run_script(
        "prepare_cbtn_sample_id_mint.py",
        ["--manifest", args.manifest, "--type", args.type],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        prog="d3b-dewrangle",
        description="Unified CLI for Dewrangle ID minting workflows.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- source-intake ---
    p_source = subparsers.add_parser(
        "source-intake",
        help="Ingest study or sample metadata into the DWH",
        description="Ingest source metadata and generate a manifest ready for ID minting.",
    )
    add_common_args(p_source)
    p_source.add_argument(
        "--type",
        choices=["study", "sample"],
        required=True,
        help="Metadata type to ingest",
    )
    p_source.add_argument(
        "--manifest",
        required=True,
        help="Path to the source metadata manifest CSV",
    )

    # --- global-id-mint ---
    p_mint = subparsers.add_parser(
        "global-id-mint",
        help="Mint org-level global IDs from a manifest",
        description="Upload a manifest to Dewrangle, trigger ID minting, and save results to the DWH.",
    )
    add_common_args(p_mint)
    p_mint.add_argument(
        "--manifest",
        required=True,
        help="Path to the ID minting manifest CSV",
    )
    p_mint.add_argument(
        "--save-dt-record",
        action="store_true",
        help="Save data transfer mapping record to the DWH (source files only)",
    )
    p_mint.add_argument(
        "--create-dewrangle-ids-table",
        action="store_true",
        help="""
            If set, create the Dewrangle IDs table in the DWH. Note that this
            should only be done once, and the table should already exist for
            subsequent runs. This flag should be used with caution; creating the
            new empty table may result in accidentally duplicating descriptors
            if the table is created after some descriptors have already had
            global IDs minted.
            """
    )
    p_mint.add_argument(
        "--verbose",
        action="store_true",
        help="If set, print verbose logs."
    )

    # --- global-id-check ---
    p_check = subparsers.add_parser(
        "global-id-check",
        help="Query a specific global ID and download its record",
        description="Query Dewrangle for a specific globalId and save its details to a CSV.",
    )
    p_check.add_argument("--env", choices=["prod", "qa"], help="Environment")
    p_check.add_argument("--organization-id", default=None, help="Override Dewrangle organization ID")
    p_check.add_argument("--output-dir", default=None, help="Directory for downloaded reports")
    p_check.add_argument(
        "--id",
        required=True,
        help="The globalId to look up (e.g. sd-xxxxxx)",
    )

    # --- global-id-update ---
    p_gi_update = subparsers.add_parser(
        "global-id-update",
        help="Update specific global ID records from a manifest",
        description="Upload a manifest containing globalId + updated fields, trigger upsert, and persist to the DWH.",
    )
    add_common_args(p_gi_update)
    p_gi_update.add_argument(
        "--manifest",
        required=True,
        help="Path to the global ID update manifest CSV (must include globalId, fhirResourceType, descriptor, descriptorState)",
    )
    # No --save-dt-record for global-id-update

    # --- study-create ---
    p_study = subparsers.add_parser(
        "study-create",
        help="Create a Kids First study in Dewrangle",
        description="Create (or sync) a study in Dewrangle and persist its report to the DWH.",
    )
    add_common_args(p_study)
    p_study.add_argument(
        "--study-name",
        required=True,
        help="Name of the study to create in Dewrangle",
    )

    # --- cbtn-prepare ---
    p_cbtn = subparsers.add_parser(
        "cbtn-prepare",
        help="Validate CBTN data and prepare a minting manifest",
        description="Validate CBTN participants/specimens against the DWH and generate manifests for ID minting.",
    )
    p_cbtn.add_argument(
        "--manifest",
        required=True,
        help="Path to the CBTN sample / participants manifest CSV",
    )
    p_cbtn.add_argument(
        "--type",
        choices=["both", "participant", "specimen"],
        required=True,
        help="Which records to validate and prepare",
    )

    args = parser.parse_args()

    dispatch = {
        "source-intake": cmd_source_intake,
        "global-id-mint": cmd_global_id_mint,
        "global-id-check": cmd_global_id_check,
        "global-id-update": cmd_global_id_update,
        "study-create": cmd_study_create,
        "cbtn-prepare": cmd_cbtn_prepare,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
