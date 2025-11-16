import os
import logging
from pathlib import Path
import tempfile
import time
import uuid
import sys

from celery import Celery
import boto3
from botocore.exceptions import ClientError
import psycopg2

import helpers as hp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Orchestrator:

    def __init__(self, redis_url, db_url, s3_client, s3_bucket, volume_path):
        self.redis_url = redis_url
        self.db_url = db_url
        self.s3_client = s3_client
        self.s3_bucket = s3_bucket

        self.volume_path = volume_path
        self.app = Celery("orchestrator", broker=REDIS_URL, backend=REDIS_URL)
        self.app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
        )

    def run_service(self, poll_interval=10):
        logger.info("Orchestrator service starting...")
        logger.info(f"Polling interval: {poll_interval} seconds")

        while True:
            retry = 0
            try:
                conn = psycopg2.connect(self.db_url)
                conn.close()
                logger.info("Database connection successful")
                break
            except Exception as e:
                if retry > 5:
                    print(f"Unable to connect to database")
                    return
                logger.error(f"Waiting for database: {e}")
                time.sleep(5)
                retry += 1

        while True:
            try:
                conn = psycopg2.connect(self.db_url)

                job =  hp.get_pending_jobs(conn)
                if job:
                    logger.info(f"Found pending job: {job['id']}")
                    conn.close()
                    self.process_job(job)
                else:
                    conn.close()
                    logger.debug("No pending jobs, sleeping...")
                    time.sleep(poll_interval)

            except KeyboardInterrupt:
                logger.info("Service stopped by user")
                break

            except Exception as e:
                logger.error(f"Error in service loop: {e}", exc_info=True)
                time.sleep(poll_interval)

    def process_job(self, job):
        job_id = job['id']
        video_key = job['video_filename']
        sketch_id = job['sketch_id']

        output_dir = Path(tempfile.mkdtemp(dir=SHARED_VOLUME))
        conn = psycopg2.connect(self.db_url)

        logger.info(f"Starting job {job_id}: {video_key}")
        try:
            hp.update_job_status(conn, job_id, 'processing')

            self.process_video(video_key, output_dir)
            self.process_outputs(sketch_id, output_dir)

            hp.update_job_status(conn, job_id, 'completed')
            logger.info(f"Job {job_id} completed successfully")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            hp.update_job_status(conn, job_id, 'failed', str(e))

        finally:
            conn.close()
            # shutil.rmtree(tmp_dir)

    def process_video(self, video_s3_key, output_path):
        """
        Main orchestration task that coordinates video processing.

        Args:
            video_s3_key: S3 key of the video to process (e.g., "videos/sample.mp4")
        """
        screenshots_dir = Path(output_path) / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        local_video_path = str(output_path / Path(video_s3_key).name)
        logger.info(f"Starting video processing for {video_s3_key}")

        if not self.download_from_s3(video_s3_key, local_video_path):
            raise Exception("Failed to download video from S3")

        logger.info("Enqueueing screenshot job")
        screenshot_task = self.app.send_task(
            "screenshot",
            args=[local_video_path, str(screenshots_dir)],
            queue="screenshot"
        )

        logger.info(f"Waiting for screenshot job {screenshot_task.id} to complete")
        screenshot_result = screenshot_task.get(timeout=600)  # 10 minute timeout
        logger.info(f"Screenshot job completed: {screenshot_result}")

        screenshot_files = list(screenshots_dir.glob("*.jpg")) + list(screenshots_dir.glob("*.png"))
        logger.info(f"Found {len(screenshot_files)} screenshots to upload")

        logger.info("Enqueueing transcribe job")
        transcribe_task = self.app.send_task(
            "transcribe",
            args=[local_video_path, str(output_path)],
            queue="transcribe"
        )

        logger.info(f"Waiting for transcribe job {transcribe_task.id} to complete")
        transcribe_task.get(timeout=600)  # 10 minute timeout
        logger.info("Transcribe job completed")

    def process_outputs(self, sketch_id, output_path):
        """
        Given outputdir contains srt file and screenshot dir with images,
        - upload each image to cloud and insert entry for each in db
        - extract each line of srt file and insert into db
        """

        screenshots_dir = Path(output_path) / "screenshots"
        if os.path.exists(screenshots_dir):
            try:
                self.process_screenshots(screenshots_dir, sketch_id)
            except Exception as e:
                logger.error(str(e), exc_info=True)
                return
        else:
            logger.warning("Skipping screenshot processing, screenshot directory not found")

        srt_files = list(Path(output_path).glob("*.srt"))

        if len(srt_files):
            srt_file = srt_files[0]
            try:
                line_dict = hp.parse_srt_file(srt_file)
                with psycopg2.connect(self.db_url) as conn:
                    hp.insert_srt_lines(conn, line_dict, sketch_id)
            except Exception as e:
                logger.error(f"Error processing srt file {srt_file}. {str(e)}", exc_info=True)
                
        else:
            logger.warning("Skipping transcribe processing, srt file not found")

    def process_screenshots(self, screenshots_dir, sketch_id):
        screenshots = hp.get_screenshot_summary(screenshots_dir)
        for image_pair in screenshots:
            # assign image names to each pairing before adding them to database
            image_pair['image_name'] = f"{uuid.uuid4()}.jpg"

        with psycopg2.connect(self.db_url) as conn:
            hp.insert_screenshots(screenshots, sketch_id, conn)

        for image_pair in screenshots:
            thumb_s3_key = f"cast_auto_screenshots/thumbnail/{image_pair['image_name']}"
            self.upload_to_s3(image_pair["thumbnail_path"], thumb_s3_key)

            profile_s3_key = f"cast_auto_screenshots/profile/{image_pair['image_name']}"
            self.upload_to_s3(image_pair["thumbnail_path"], profile_s3_key)

    def download_from_s3(self, s3_key, local_path):
        try:
            logger.info(f"Downloading {s3_key} from S3 bucket {S3_BUCKET}")
            self.s3_client.download_file(S3_BUCKET, s3_key, local_path)
            logger.info(f"Successfully downloaded to {local_path}")
            return True
        except ClientError as e:
            logger.error(f"Failed to download video: {e}")
            return False

    def upload_to_s3(self, local_path, s3_key):
        try:
            logger.info(f"Uploading {local_path} to s3://{S3_BUCKET}/{s3_key}")
            self.s3_client.upload_file(
                local_path, 
                S3_BUCKET, 
                s3_key,
                ExtraArgs={
                    'ACL': 'public-read'
                }
            )
            logger.info(f"Successfully uploaded to {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to upload file: {e}")
            return False


if __name__ == "__main__":
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
    DB_URL = os.getenv('DB_URL', 'postgresql://postgres:postgres@172.17.0.1:5432/thesketchdb_dev')
    S3_KEY = os.getenv("S3_KEY")
    S3_SECRET = os.getenv("S3_SECRET")
    S3_REGION = os.getenv("S3_REGION", "us-east-1")
    S3_BUCKET = os.getenv("S3_BUCKET")
    S3_ENDPOINT = os.getenv("S3_ENDPOINT", "https://nyc3.digitaloceanspaces.com")
    SHARED_VOLUME = os.getenv("SHARED_VOLUME", "/shared")

    s3_client = boto3.client(
        "s3",
        region_name=S3_REGION,
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_KEY,
        aws_secret_access_key=S3_SECRET,
    )

    orchestrator = Orchestrator(
        REDIS_URL,
        DB_URL,
        s3_client,
        S3_BUCKET,
        SHARED_VOLUME
    )

    if len(sys.argv) > 1:
        video_key = sys.argv[1]
        video_filename = Path(video_key).stem
        video_id = video_filename

        video_dir = Path(SHARED_VOLUME) / video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        try:
            logger.info(f"Starting video processing for: {video_key}")
            result = orchestrator.process_video(video_key, video_dir)
            logger.info("Waiting for task to complete...")
            logger.info(f"Task completed: {result}")
        except Exception as e:
            logger.error(f"Task failed: {e}")
    else:
        logger.info(f"Starting orchestrator service")
        orchestrator.run_service()

