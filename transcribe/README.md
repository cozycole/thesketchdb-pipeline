## Installation

Ensure the cloud toolkit is installed to make use of nvidia gpu: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

Run Dockerfile.cpu if no nvidia gpu is available.

Dockerfile is meant to be run as a worker which checks a redis cache for a "transcribe" job that supplies a video url and a destination (in the shared volume).


```bash
pip install torch==2.7.1 torchaudio==2.7.1

pip install -r requirements.txt -c constraints.txt

```
