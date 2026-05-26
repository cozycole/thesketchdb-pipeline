FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04
WORKDIR /app

# Copy only requirements for cache
COPY requirements.txt .

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    cmake \
    git \
    libgl1-mesa-glx \
    libglib2.0-0 \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# Copy app code last
COPY . .

ARG MODEL_PATH
RUN curl -L $MODEL_PATH -o model.pth

ENV LD_LIBRARY_PATH=/usr/local/lib/python3.10/dist-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH

CMD ["celery", "-A", "worker.app", "worker", "--loglevel=info"]
