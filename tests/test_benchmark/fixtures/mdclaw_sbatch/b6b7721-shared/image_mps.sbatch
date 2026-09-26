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

# NVIDIA MPS: 2 OpenMM process(es) share the 1 GPU(s) of this job
MDCLAW_MPS_ROOT="${TMPDIR:-/tmp}/mdclaw-mps-${SLURM_JOB_ID:-$$}"
export CUDA_MPS_PIPE_DIRECTORY="${MDCLAW_MPS_ROOT}/pipe"
export CUDA_MPS_LOG_DIRECTORY="/work/study/jobs/main/probe_${SLURM_JOB_ID:-$$}.mps"
export CUDA_MPS_ACTIVE_THREAD_PERCENTAGE=100
mkdir -p "$CUDA_MPS_PIPE_DIRECTORY" "$CUDA_MPS_LOG_DIRECTORY"
if ! command -v nvidia-cuda-mps-control >/dev/null 2>&1; then
  echo "[mdclaw mps] nvidia-cuda-mps-control not found on $(hostname); cannot start MPS" >&2
  exit 1
fi
mdclaw_mps_stop() {
  echo quit | nvidia-cuda-mps-control >/dev/null 2>&1 || true
  rm -rf "$MDCLAW_MPS_ROOT"
}
mdclaw_mps_terminate() {
  echo "[mdclaw mps] SIGTERM received; forwarding to tasks" >&2
  kill -TERM "${MDCLAW_MPS_PIDS[@]}" 2>/dev/null
  wait
  mdclaw_mps_stop
  exit 143
}
trap mdclaw_mps_stop EXIT
trap mdclaw_mps_terminate TERM
if ! nvidia-cuda-mps-control -d; then
  echo "[mdclaw mps] failed to start the MPS control daemon on $(hostname)" >&2
  exit 1
fi
echo "[mdclaw mps] daemon started on $(hostname): tasks=2 gpus=1 active_thread_percentage=$CUDA_MPS_ACTIVE_THREAD_PERCENTAGE CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"
IFS=',' read -r -a MDCLAW_MPS_DEVICES <<< "${CUDA_VISIBLE_DEVICES:-}"
MDCLAW_MPS_PIDS=()
MDCLAW_MPS_NODES=()

# Container runtime: the submitting shell's PATH is not necessarily this node's.
if ! command -v singularity >/dev/null 2>&1; then
    [ -r /etc/profile ] && . /etc/profile >/dev/null 2>&1 || true
    [ -r "${MDCLAW_MODULE_INIT:-/etc/profile.d/modules.sh}" ] && . "${MDCLAW_MODULE_INIT:-/etc/profile.d/modules.sh}" >/dev/null 2>&1 || true
fi

# Tasks: one background process per DAG node, round-robin over the visible GPUs
# slot 0: /work/study/jobs/main min_001
(
  if [ ${#MDCLAW_MPS_DEVICES[@]} -gt 0 ]; then
    export CUDA_VISIBLE_DEVICES="${MDCLAW_MPS_DEVICES[$((0 % ${#MDCLAW_MPS_DEVICES[@]}))]}"
  fi
  singularity exec --nv --bind /work,/work/study/jobs/main,$CUDA_MPS_PIPE_DIRECTORY /images/mdclaw.sif mdclaw --job-dir /work/study/jobs/main --node-id min_001 run_minimization --platform CUDA
) > "/work/study/jobs/main/probe_${SLURM_JOB_ID:-$$}.task0.out" 2> "/work/study/jobs/main/probe_${SLURM_JOB_ID:-$$}.task0.err" &
MDCLAW_MPS_PIDS[0]=$!
MDCLAW_MPS_NODES[0]='job_dir=/work/study/jobs/main node_id=min_001'
echo "[mdclaw mps] slot 0 started pid=${MDCLAW_MPS_PIDS[0]}: ${MDCLAW_MPS_NODES[0]}"
# slot 1: /work/study/jobs/main min_002
(
  if [ ${#MDCLAW_MPS_DEVICES[@]} -gt 0 ]; then
    export CUDA_VISIBLE_DEVICES="${MDCLAW_MPS_DEVICES[$((1 % ${#MDCLAW_MPS_DEVICES[@]}))]}"
  fi
  singularity exec --nv --bind /work,/work/study/jobs/main,$CUDA_MPS_PIPE_DIRECTORY /images/mdclaw.sif mdclaw --job-dir /work/study/jobs/main --node-id min_002 run_minimization --platform CUDA
) > "/work/study/jobs/main/probe_${SLURM_JOB_ID:-$$}.task1.out" 2> "/work/study/jobs/main/probe_${SLURM_JOB_ID:-$$}.task1.err" &
MDCLAW_MPS_PIDS[1]=$!
MDCLAW_MPS_NODES[1]='job_dir=/work/study/jobs/main node_id=min_002'
echo "[mdclaw mps] slot 1 started pid=${MDCLAW_MPS_PIDS[1]}: ${MDCLAW_MPS_NODES[1]}"

# Wait for every slot; any failure fails the job
MDCLAW_MPS_STATUS=0
for slot in "${!MDCLAW_MPS_PIDS[@]}"; do
  if wait "${MDCLAW_MPS_PIDS[$slot]}"; then
    echo "[mdclaw mps] slot $slot finished: ${MDCLAW_MPS_NODES[$slot]}"
  else
    rc=$?
    echo "[mdclaw mps] slot $slot FAILED (exit $rc): ${MDCLAW_MPS_NODES[$slot]}" >&2
    MDCLAW_MPS_STATUS=1
  fi
done
echo "[mdclaw mps] all slots finished; status=$MDCLAW_MPS_STATUS"
exit $MDCLAW_MPS_STATUS
