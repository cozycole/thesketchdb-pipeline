import argparse
import subprocess
import os
import sys
from diarize import diarize

class Transcribe:
    def __init__(self, verbose=False):
        self.verbose = verbose

    def transcribe(self, audio_path, output_path):
        diarize(
            audio_path,
            output_path,
        )

        if self.verbose:
            print(f"Transcribing video {audio_path}")
            print(f"Outputting to {output_path}")



if __name__ == "__main__":
    """
    python transcribe.py 
        -i ./videos/example_video.mp4
        -o "./processed_videos"
    """

    parser = argparse.ArgumentParser(
        description="Transcribe audio input with timestamps per line"
    )

    parser.add_argument(
        "-i", "--input",
        help="path to video/audio file",
        required=True
    )

    parser.add_argument(
        "-o", "--output_dir", 
        help="path to output directory", 
    )

    args = parser.parse_args()
    if not args.input:
        print("No input file supplied")
        sys.exit(1)

    t = Transcribe(verbose=True)
    t.transcribe(args.input, args.output_dir)
