import os
import shlex
import subprocess


def transcode_for_ai_pipeline(
    input_path: str,
    output_path: str | None = None,
    ffmpeg_bin: str = "ffmpeg",
    overwrite: bool = False,
    crf: int = 23,
    preset: str = "slow",
    audio_bitrate: str = "128k",
) -> str:
    """
    Transcode a local video into a pipeline-safe MP4:
    - H.264 High profile
    - yuv420p
    - bt709 tags
    - AAC-LC, 48kHz, stereo
    - scale down to max 720p if larger
    - preserve aspect ratio
    - optimize for smaller storage with CRF

    Returns the output path.
    """

    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    if output_path is None:
        root, _ = os.path.splitext(input_path)
        output_path = f"{root}_pipeline.mp4"

    if os.path.exists(output_path) and not overwrite:
        raise FileExistsError(f"Output file already exists: {output_path}")

    # Scale rule:
    # - if height > 720, resize to height 720 preserving aspect ratio
    # - otherwise keep original size
    # - force even width/height for x264 compatibility
    vf = (
        "scale="
        "'if(gt(ih,720),trunc(iw*720/ih/2)*2,trunc(iw/2)*2)':"
        "'if(gt(ih,720),720,trunc(ih/2)*2)',"
        "format=yuv420p"
    )

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-y" if overwrite else "-n",
        "-i", input_path,

        # Video
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-vf", vf,

        # bt709 tagging
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",

        # Audio
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-ar", "48000",
        "-ac", "2",

        # MP4 friendliness
        "-movflags", "+faststart",

        # Drop odd extra streams by default
        "-map", "0:v:0",
        "-map", "0:a:0?",

        output_path,
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg transcode failed\n"
            f"Command: {' '.join(shlex.quote(x) for x in cmd)}\n\n"
            f"stderr:\n{result.stderr}"
        )

    return output_path
