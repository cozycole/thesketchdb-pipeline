FROM nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04

RUN apt-get update && apt-get install -y \
    python3.10 \
    python3.10-venv \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.10 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

WORKDIR /app

COPY requirements.prod.txt .
COPY constraints.txt .

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    ffmpeg \
    git \
    libgl1-mesa-glx \
    libglib2.0-0 \
    wget \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir 'numpy<2' typing_extensions
RUN pip install --no-cache-dir torch==2.6.0 torchaudio==2.6.0
RUN pip install --no-cache-dir -c constraints.txt -r requirements.prod.txt

# Set cache directory environment variable
ENV NEMO_CACHE_DIR=/root/.cache/torch/NeMo

# Download NeMo model during build - this handles version-specific paths automatically
RUN python -c "from nemo.collections.asr.models import EncDecDiarLabelModel; \
    EncDecDiarLabelModel.from_pretrained('diar_msdd_telephonic')" || \
    echo "Model download during build failed, will retry at runtime"
RUN python -c "from nemo.collections.asr.models import EncDecClassificationModel; \
    EncDecClassificationModel.from_pretrained('vad_multilingual_marblenet')" || \
    echo "Model download during build failed, will retry at runtime"

COPY . .

ENV LD_LIBRARY_PATH=/usr/local/lib/python3.10/dist-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH

CMD ["celery", "-A", "worker.app", "worker", "--loglevel=info"]
