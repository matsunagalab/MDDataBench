#!/bin/bash
#SBATCH --job-name=probe
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gpus=1
#SBATCH --time=00:20:00
#SBATCH --mem=32G
#SBATCH --output=/work/study/jobs/main/probe_%j.out
#SBATCH --error=/work/study/jobs/main/probe_%j.err

# Container runtime: the submitting shell's PATH is not necessarily this node's.
if ! command -v singularity >/dev/null 2>&1; then
    [ -r /etc/profile ] && . /etc/profile >/dev/null 2>&1 || true
    [ -r "${MDCLAW_MODULE_INIT:-/etc/profile.d/modules.sh}" ] && . "${MDCLAW_MODULE_INIT:-/etc/profile.d/modules.sh}" >/dev/null 2>&1 || true
fi

# Job command
singularity exec --nv --bind /frozen/src,/work,/work/study/jobs/main --env PYTHONPATH=/frozen/src /images/mdclaw.sif mdclaw --job-dir /work/study/jobs/main --node-id min_001 run_minimization --platform CUDA
