#!/bin/bash
#SBATCH --job-name=probe
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --gpus=1
#SBATCH --time=00:20:00
#SBATCH --mem=32G
#SBATCH --dependency=afterok:1
#SBATCH --kill-on-invalid-dep=yes
#SBATCH --output=/work/study/jobs/main/probe_%j.out
#SBATCH --error=/work/study/jobs/main/probe_%j.err

# Job command
singularity exec --nv --bind /work,/work/study/jobs/main /images/mdclaw.sif mdclaw --job-dir /work/study/jobs/main --node-id min_001 run_minimization --platform CUDA
