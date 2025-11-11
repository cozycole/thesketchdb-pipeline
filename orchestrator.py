import os
import logging
from pathlib import Path
from celery import Celery
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
S3_KEY = os.getenv("S3_KEY")
S3_SECRET = os.getenv("S3_SECRET")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "https://nyc3.digitaloceanspaces.com")
SHARED_VOLUME = os.getenv("SHARED_VOLUME", "/shared")

app = Celery("orchestrator", broker=REDIS_URL, backend=REDIS_URL)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)

s3_client = boto3.client(
    "s3",
    region_name=S3_REGION,
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_KEY,
    aws_secret_access_key=S3_SECRET,
)


def download_video_from_s3(s3_key, local_path):
    """Download video from S3 bucket to local path."""
    try:
        logger.info(f"Downloading {s3_key} from S3 bucket {S3_BUCKET}")
        s3_client.download_file(S3_BUCKET, s3_key, local_path)
        logger.info(f"Successfully downloaded to {local_path}")
        return True
    except ClientError as e:
        logger.error(f"Failed to download video: {e}")
        return False


def upload_file_to_s3(local_path, s3_key):
    """Upload file to S3 bucket."""
    try:
        logger.info(f"Uploading {local_path} to s3://{S3_BUCKET}/{s3_key}")
        s3_client.upload_file(local_path, S3_BUCKET, s3_key)
        logger.info(f"Successfully uploaded to {s3_key}")
        return True
    except ClientError as e:
        logger.error(f"Failed to upload file: {e}")
        return False


def parse_srt_file(srt_path):
    """Parse SRT file and return list of subtitle entries."""
    subtitles = []
    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        entries = content.strip().split("\n\n")
        for entry in entries:
            lines = entry.strip().split("\n")
            if len(lines) >= 3:
                index = lines[0]
                timestamp = lines[1]
                text = " ".join(lines[2:])

                # Parse timestamps
                times = timestamp.split(" --> ")
                if len(times) == 2:
                    start_time = times[0].strip()
                    end_time = times[1].strip()

                    subtitles.append({
                        "index": index,
                        "start_time": start_time,
                        "end_time": end_time,
                        "text": text
                    })

        logger.info(f"Parsed {len(subtitles)} subtitle entries from {srt_path}")
        return subtitles
    except Exception as e:
        logger.error(f"Failed to parse SRT file: {e}")
        return []


def save_subtitles_to_db(subtitles, video_id):
    """Save subtitle entries to database (placeholder for now)."""
    # TODO: Implement database connection and saving
    logger.info(f"Would save {len(subtitles)} subtitles for video {video_id} to database")
    for sub in subtitles:
        logger.debug(f"Subtitle: {sub['start_time']} -> {sub['end_time']}: {sub['text'][:50]}...")


def process_video(video_s3_key, output_path):
    """
    Main orchestration task that coordinates video processing.

    Args:
        video_s3_key: S3 key of the video to process (e.g., "videos/sample.mp4")
    """
    try:

        screenshots_dir = output_path / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        # Download video
        local_video_path = str(output_path / Path(video_s3_key).name)
        logger.info(f"Starting video processing for {video_s3_key}")

        if not download_video_from_s3(video_s3_key, local_video_path):
            raise Exception("Failed to download video from S3")

        # Enqueue screenshot job and wait for completion
        logger.info("Enqueueing screenshot job")
        screenshot_task = app.send_task(
            "screenshot",
            args=[local_video_path, str(screenshots_dir)],
            queue="screenshot"
        )

        # # Wait for screenshot job to complete
        logger.info(f"Waiting for screenshot job {screenshot_task.id} to complete")
        screenshot_result = screenshot_task.get(timeout=600)  # 10 minute timeout
        logger.info(f"Screenshot job completed: {screenshot_result}")
        #
        # # # Upload screenshots to S3
        screenshot_files = list(screenshots_dir.glob("*.jpg")) + list(screenshots_dir.glob("*.png"))
        logger.info(f"Found {len(screenshot_files)} screenshots to upload")

        # for screenshot_file in screenshot_files:
        #     s3_key = f"detected_faces/{video_id}/{screenshot_file.name}"
        #     upload_file_to_s3(str(screenshot_file), s3_key)

        # Enqueue transcribe job and wait for completion
        logger.info("Enqueueing transcribe job")
        transcribe_output = str(output_path / f"{video_id}.srt")

        transcribe_task = app.send_task(
            "transcribe",
            args=[local_video_path, transcribe_output],
            queue="transcribe"
        )

        # Wait for transcribe job to complete
        logger.info(f"Waiting for transcribe job {transcribe_task.id} to complete")
        transcribe_result = transcribe_task.get(timeout=1800)  # 30 minute timeout
        logger.info(f"Transcribe job completed: {transcribe_result}")
        #
        # # Parse and save subtitles
        # subtitles = []
        # if Path(transcribe_output).exists():
        #     subtitles = parse_srt_file(transcribe_output)
        #     save_subtitles_to_db(subtitles, video_id)
        #
        #     # Optionally upload SRT file to S3
        #     srt_s3_key = f"transcripts/{video_id}.srt"
        #     upload_file_to_s3(transcribe_output, srt_s3_key)
        # else:
        #     logger.warning(f"SRT file not found at {transcribe_output}")
        #
        # logger.info(f"Video processing completed for {video_id}")
        #
        return {
            "status": "completed",
            "output_path": screenshots_dir,
            # "screenshots_count": len(screenshot_files),
            # "subtitles_count": len(subtitles) if "subtitles" in locals() else 0
        }
        
    except Exception as e:
        logger.error(f"Error processing video: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    import sys
    # Extract video filename without extension for directory naming
    if len(sys.argv) > 1:
        video_key = sys.argv[1]
        video_filename = Path(video_key).stem
        video_id = video_filename

        video_dir = Path(SHARED_VOLUME) / video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        try:
            logger.info(f"Starting video processing for: {video_key}")
            result = process_video(video_key, video_dir)
            logger.info("Waiting for task to complete...")
            logger.info(f"Task completed: {result}")
        except Exception as e:
            logger.error(f"Task failed: {e}")
    else:
        # Start Celery worker
        print("Video key not specified")
