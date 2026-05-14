ollam_sh = r"""#!/bin/bash
#
# Script Name: ollama.slurm
# Description: Starts Ollama using a PyTorch container image from NGC.

#SBATCH --container-image=/cm/shared/enroot/images/pytorch-24.11-py3.sqsh
#SBATCH --container-mounts="/network/rit/dgx/{{DGX_FOLDER_NAME}}:/mnt/dgx_lab/,/network/rit/lab/aiworkshop_lab/:/mnt/lab/"
#SBATCH --container-writable
#SBATCH --no-container-mount-home
#SBATCH --reservation=workshop
#SBATCH --job-name="{{JOB_NAME}}"
#SBATCH --output=%j.out
#SBATCH --time=48:00:00
#SBATCH --gpus=1

# Assign Ports
export OLLAMA_HTTP_PORT=$((RANDOM % 1000 + 8000))

# Build URLs
OLLAMA_HTTP_URL="http://${SLURMD_NODENAME}.its.albany.edu:${OLLAMA_HTTP_PORT}"

# Setup Demo Folder
DEMO_DIR="/mnt/dgx_lab/demo_openclaw"
mkdir -p ${DEMO_DIR}/ollama/models
mkdir -p ${DEMO_DIR}/logs

# Set Ollama Environment Variables
export OLLAMA_BASE_URL="http://localhost:${OLLAMA_HTTP_PORT}"
export OLLAMA_HOST=0.0.0.0:${OLLAMA_HTTP_PORT}
export OLLAMA_MODELS=${DEMO_DIR}/ollama/models

echo -e "\nThe Ollama Demo is starting..."

# Function to Check if Ollama is Already Installed
check_ollama() {
    if [ -f "${DEMO_DIR}/ollama/bin/ollama" ]; then
        return 0
    fi
    return 1
}

# Download & Install Ollama (If Needed)
echo -e "\nChecking for Ollama installation..."
if ! check_ollama; then
    echo -e "\nNot found: downloading Ollama...\n"

    # Download Ollama
    curl -L https://ollama.com/download/ollama-linux-amd64.tar.zst -o ${DEMO_DIR}/ollama/ollama-linux-amd64.tar.zst

    # Clone and Build zstd
    echo -e "\nCloning and building zstd...\n"
    git clone https://github.com/facebook/zstd.git /tmp/zstd
    make -C /tmp/zstd -s

    # Decompress Ollama
    echo -e "\nDecompressing and extracting Ollama...\n"
    /tmp/zstd/zstd -d ${DEMO_DIR}/ollama/ollama-linux-amd64.tar.zst -o ${DEMO_DIR}/ollama/ollama-linux-amd64.tar
    tar -xf ${DEMO_DIR}/ollama/ollama-linux-amd64.tar -C ${DEMO_DIR}/ollama
    echo -e "\n🔵 Ollama downloaded and extracted to ${DEMO_DIR}/ollama."
else
    echo -e "\n⚪ Ollama already installed at ${DEMO_DIR}/ollama."
fi

# Start Ollama
echo -e "\nStarting Ollama server..."
nohup ${DEMO_DIR}/ollama/bin/ollama serve > ${DEMO_DIR}/logs/ollama.log 2>&1 &
echo -e "\n🟢 Ollama server started on ${OLLAMA_HTTP_URL}."

# Wait for Ollama server to be ready
sleep 10

# Download Qwen3 32B (If Needed)
echo -e "\nChecking for Qwen3 32B model..."
if ! ${DEMO_DIR}/ollama/bin/ollama show qwen3:32b &>/dev/null; then
    echo -e "\nNot found: downloading Qwen3 32B model (~20GB, this may take a while)..."
    ${DEMO_DIR}/ollama/bin/ollama pull qwen3:32b
    echo -e "\n🔵 Qwen3 32B model downloaded."
else
    echo -e "\n⚪ Qwen3 32B model already available."
fi

# Download Llama3.2 3B (If Needed)
echo -e "\nChecking for Llama3.2 3B model..."
if ! ${DEMO_DIR}/ollama/bin/ollama show llama3.2:3b &>/dev/null; then
    echo -e "\nNot found: downloading Llama3.2 3B model (~2GB, this may take a while)..."
    ${DEMO_DIR}/ollama/bin/ollama pull llama3.2:3b
    echo -e "\n🔵 Llama3.2 3B model downloaded."
else
    echo -e "\n⚪ Llama3.2 3B model already available."
fi

# Print Important Information
echo -e "\n================================================================================\n"
echo -e "SLURM Job ID ${SLURM_JOB_ID} running on ${SLURMD_NODENAME}\n"
echo -e "Ollama API is available at: ${OLLAMA_HTTP_URL}"
echo -e "\nAvailable Models:"
echo -e "  - Qwen3 32B    (qwen3:32b)"
echo -e "  - Llama3.2 3B  (llama3.2:3b)"
echo -e "\n================================================================================\n"

tail -f ${DEMO_DIR}/logs/ollama.log"""