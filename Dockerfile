FROM nvidia/cuda:11.3.1-cudnn8-devel-ubuntu20.04

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.8 python3.8-dev python3.8-distutils python3-pip \
    git wget curl ca-certificates \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    libxi6 libxinerama1 libxcursor1 libxrandr2 \
    libegl1 libgles2 libglvnd0 libglx0 \
    libosmesa6 libosmesa6-dev \
    ffmpeg \
    vulkan-tools \
    && rm -rf /var/lib/apt/lists/*

# Use python3.8 as default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.8 1
RUN python -m pip install --no-cache-dir --upgrade pip==23.3.2

# PyTorch 1.10.0 cu113 (versão exata exigida pelo IsaacGym Preview 4)
RUN pip install --no-cache-dir \
    torch==1.10.0+cu113 torchvision==0.11.1+cu113 torchaudio==0.10.0+cu113 \
    --extra-index-url https://download.pytorch.org/whl/cu113

# Pinned tooling exigido
RUN pip install --no-cache-dir "setuptools==59.5.0" "wheel" "numpy<1.24"

# Install IsaacGym from local tarball
WORKDIR /opt
COPY IsaacGym_Preview_4_Package.tar.gz /opt/
RUN tar -xzf IsaacGym_Preview_4_Package.tar.gz && rm IsaacGym_Preview_4_Package.tar.gz
RUN cd /opt/isaacgym/python && pip install --no-cache-dir -e .

# rsl_rl (editable)
WORKDIR /workspace
COPY rsl_rl /workspace/rsl_rl
RUN cd /workspace/rsl_rl && pip install --no-cache-dir -e .

# legged_gym (editable)
COPY legged_gym /workspace/legged_gym
RUN cd /workspace/legged_gym && pip install --no-cache-dir -e .

# Requirements gerais
COPY requirements.txt /workspace/
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# LD_LIBRARY_PATH para libpython encontrar libs do IsaacGym
ENV LD_LIBRARY_PATH=/opt/isaacgym/python/isaacgym/_bindings/linux-x86_64:${LD_LIBRARY_PATH}

# Cria diretórios padrão de trabalho
RUN mkdir -p /workspace/logs /workspace/data

WORKDIR /workspace/legged_gym/legged_gym/scripts

# Default command: shell interativo
CMD ["bash"]
