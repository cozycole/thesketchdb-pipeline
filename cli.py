import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

def load_config():
    config_path = Path("config.json")
    if config_path.exists():
        return json.loads(config_path.read_text())
    
    raise ImportError("No config defined. Refer to config-example.json")

def get_cudnn_path(venv_python):
    """Find the cuDNN library path in a venv"""
    venv_python = Path(venv_python)
    venv_root = venv_python.parent.parent
    
    # Try common locations
    possible_paths = [
        venv_root / "lib/python3.10/site-packages/nvidia/cudnn/lib",
        venv_root / "lib/python3.11/site-packages/nvidia/cudnn/lib",
        venv_root / "lib/python3.12/site-packages/nvidia/cudnn/lib",
    ]
    
    for path in possible_paths:
        if path.exists():
            return str(path)
    return ""

def process_video(config, video_path, output_path):
    screenshot_dir = os.path.join(output_path, "screenshots")
    os.makedirs(screenshot_dir ,exist_ok=True)

    subprocess.run(
        [
            config["screenshot"]["python"], 
            config["screenshot"]["script"], 
            "--model", config["model"],
            "--input", video_path,
            "--output", screenshot_dir
        ], check=True)

    print("Screenshots complete")


    env = os.environ.copy()
    
    env["LD_LIBRARY_PATH"] = get_cudnn_path(config["transcription"]["python"])
    if not env["LD_LIBRARY_PATH"]:
        raise RuntimeError("Undefined LD_LIBRARY_PATH, unable to find cudnn libs")

    subprocess.run(
        [
            config["transcription"]["python"], 
            config["transcription"]["script"], 
            "--input", video_path,
            "--output", output_path,
        ],
        env=env,
        check=True)

    print("Transcription complete")


def main():
    config = load_config()

    parser = argparse.ArgumentParser(
        description="Download YouTube video for diarization processing"
    )
    parser.add_argument(
        "-i", "--input",
        help="path to video file"
    )
    parser.add_argument(
        "-l", "--link", 
        help="link to video" 
    )

    parser.add_argument(
        "-o", "--output", 
        help="path to output files", 
    )

    args = parser.parse_args()
    if not (args.link or args.input):
        print("Youtube link or input path must be supplied")
        sys.exit(1)
    
    output_path = args.output
    if not args.output:
        output_path = "."
    else:
        os.makedirs(output_path, exist_ok=True)

    process_video(config, args.input, output_path)

if __name__ == "__main__":
    main()
