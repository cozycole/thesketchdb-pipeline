import os
from celery import Celery
from transcribe import Transcribe
import logging
import tempfile
import requests

broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")

logging.info(f"REDIS URL: {broker_url}")

app = Celery(
    "transcribe_worker", 
    broker=broker_url, 
    backend=broker_url
)

def download_to_local(url):
    local_fd, local_path = tempfile.mkstemp(suffix=".mp4")
    os.close(local_fd)
    logging.info(f"Downloading {url} to {local_path}")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return local_path

@app.task(name="transcribe")
def run_transcribe(input_path, output_dir):
    my_str = f"Got the task! Here's the video: {input_path}, outputting to {output_dir}"
    logging.info(my_str)

    if input_path.startswith("http"):
        local_path = download_to_local(input_path)
    else:
        local_path = input_path

    logging.info(f"local path: {local_path}")

    tc = Transcribe(verbose=True)
    tc.transcribe(local_path, output_dir)
