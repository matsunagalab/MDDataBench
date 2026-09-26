#!/bin/bash
#SBATCH --job-name=probe
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gpus=1
#SBATCH --time=00:20:00
#SBATCH --mem=32G
#SBATCH --array=0-1
#SBATCH --output=/work/study/jobs/main/probe_%j.out
#SBATCH --error=/work/study/jobs/main/probe_%j.err

# Container runtime: the submitting shell's PATH is not necessarily this node's.
if ! command -v /usr/bin/singularity >/dev/null 2>&1; then
    [ -r /etc/profile ] && . /etc/profile >/dev/null 2>&1 || true
    [ -r "${MDCLAW_MODULE_INIT:-/etc/profile.d/modules.sh}" ] && . "${MDCLAW_MODULE_INIT:-/etc/profile.d/modules.sh}" >/dev/null 2>&1 || true
fi

# Array dispatch: one DAG node per SLURM_ARRAY_TASK_ID
case "$SLURM_ARRAY_TASK_ID" in
  0)
    printf '%s %s %s\n' "[array_task=${SLURM_ARRAY_TASK_ID}]" job_dir=/work/study/jobs/main node_id=min_001
    /usr/bin/singularity exec --nv --bind /work,/work/study/jobs/main /images/mdclaw.sif mdclaw --job-dir /work/study/jobs/main --node-id min_001 run_minimization --platform CUDA
    ;;
  1)
    printf '%s %s %s\n' "[array_task=${SLURM_ARRAY_TASK_ID}]" job_dir=/work/study/jobs/main node_id=min_002
    /usr/bin/singularity exec --nv --bind /work,/work/study/jobs/main /images/mdclaw.sif mdclaw --job-dir /work/study/jobs/main --node-id min_002 run_minimization --platform CUDA
    ;;
  *)
    echo "Unknown SLURM_ARRAY_TASK_ID: $SLURM_ARRAY_TASK_ID" >&2
    exit 1
    ;;
esac
