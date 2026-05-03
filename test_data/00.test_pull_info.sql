with file_mapping as (
    select 
        dtfm.study_id,
        sfm.sample_id,
        sfm.aliquot_id,
        sfm.experiment_strategy,
        dtfm.global_id,
        dgid.descriptor as file_s3_path
    from huangx_dev_schema_dgd_workflow.src_file_manifests as sfm
    left join huangx_dev_schema_dgd_workflow.data_transfer_file_mapping as dtfm
        on (sfm.file_name = dtfm.file_name and sfm.dt_id = dtfm.dt_id)
    left join huangx_dev_schema_dgd_workflow.dewrangle_ids as dgid
        on dgid."globalId" = dtfm.global_id
)

select distinct
    ssm.study_id,
	ptdgid."globalId" as participant_global_id,
    sdgid."globalId" as biospecimen_global_id,
	fm.global_id as file_global_id,
    ssm.case_id,
    ssm.sample_id,
    ssm.aliquot_id,
    ssm.analyte_type,
    ssm.tissue_type,
    fm.experiment_strategy,
    fm.file_s3_path
from huangx_dev_schema_dgd_workflow.src_sample_manifests as ssm
left join huangx_dev_schema_dgd_workflow.dewrangle_ids as ptdgid
    on ptdgid.descriptor = ssm.case_id || ';' || ssm.study_id
left join huangx_dev_schema_dgd_workflow.dewrangle_ids as sdgid
    on sdgid.descriptor = ssm.aliquot_id || ';' || ssm.study_id
left join file_mapping as fm
    on fm.study_id = ssm.study_id and fm.aliquot_id = ssm.aliquot_id
where ssm.study_id != 'sd-mbgzrdziz4' -- filter out the previously existing study record