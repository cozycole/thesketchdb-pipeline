import os
import logging
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from celery import Celery
import boto3

import helpers as hp
import video as v
import storage as s
import db
import dispatch as dp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Orchestrator:

    def __init__(
        self, 
        db: db.PipelineDb,
        hot_storage: s.StorageBackend,
        cold_storage: s.StorageBackend,
        task_dispatcher: dp.TaskDispatcher,
        volume_path: str
    ):
        self.db = db
        self.hot_storage = hot_storage
        self.cold_storage = cold_storage
        self.dispatcher = task_dispatcher

        self.volume_path = volume_path

    def run_service(self, poll_interval=10):
        logger.info("Orchestrator service starting...")
        logger.info(f"Polling interval: {poll_interval} seconds")
        logger.info(self.db._db_url)

        while True:
            try:
                job =  self.db.get_pending_jobs()
                if job:
                    logger.info(f"Found pending job: {job['id']}")
                    self.process_job(job)
                else:
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
        video_key = job['hot_s3_key']
        sketch_id = job['sketch_id']

        output_dir = Path(tempfile.mkdtemp(dir=self.volume_path))

        logger.info(f"Starting job {job_id}: {video_key}")
        try:
            self.db.update_job_status(job_id, 'processing')

            src_video_path = str(output_dir / Path(video_key).name)
            self.hot_storage.download(video_key, src_video_path)

            normalized_video_path = str(output_dir / "normalized_video.mp4" )
            logger.info(f"Normalizing source video: {src_video_path} to {normalized_video_path}")
            v.transcode_for_ai_pipeline(
                input_path=src_video_path,
                output_path=normalized_video_path,
            )

            self.process_video(normalized_video_path, output_dir)
            self.process_outputs(sketch_id, output_dir)

            self.db.update_job_status(job_id, "completed")
            logger.info(f"Job {job_id} completed successfully. Starting archival...")

            # Archive the source video in cold storage
            archive_key = f"video/{uuid.uuid4()}{Path(video_key).suffix}"
            self.cold_storage.upload(
                local_path=src_video_path,
                remote_key=archive_key,
            )
            self.db.set_archive(archive_key, job_id)
            self.hot_storage.delete(video_key)

            logger.info(f"Source version of {video_key} uploaded to cold storage as {archive_key}.")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            self.db.update_job_status(job_id, "error", str(e))

        finally:
            shutil.rmtree(output_dir)

    def process_video(self, video_path, output_path: Path):
        """
        Main orchestration task that coordinates video processing

        Args:
            video_s3_key: S3 key of the video to process (e.g., "videos/sample.mp4")
        """
        screenshots_dir = Path(output_path) / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        logger.info(f"Starting video processing for {Path(video_path).name}")


        logger.info("Enqueueing screenshot job")
        self.dispatcher.dispatch(
            "screenshot",
            args=[video_path, str(screenshots_dir)],
            queue="screenshot"
        )

        logger.info(f"Screenshot job completed")

        screenshot_files = list(screenshots_dir.glob("*.jpg")) + list(screenshots_dir.glob("*.png"))
        logger.info(f"Found {len(screenshot_files)} screenshots to upload")

        logger.info("Enqueueing transcribe job")
        self.dispatcher.dispatch(
            "transcribe",
            args=[video_path, str(output_path)],
            queue="transcribe"
        )

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
                self.db.insert_srt_lines(line_dict, sketch_id)
            except Exception as e:
                logger.error(f"Error processing srt file {srt_file}. {str(e)}", exc_info=True)

        else:
            logger.warning("Skipping transcribe processing, srt file not found")

    def process_screenshots(self, screenshots_dir, sketch_id):
        screenshots = hp.get_screenshot_summary(screenshots_dir)
        for image_pair in screenshots:
            # assign image names to each pairing before adding them to database
            image_pair['image_name'] = f"{uuid.uuid4()}.jpg"

        self.db.insert_screenshots(screenshots, sketch_id)

        logger.info(f"Uploading {len(screenshots)} screenshots")
        for image_pair in screenshots:
            thumb_s3_key = f"cast_auto_screenshots/thumbnail/{image_pair['image_name']}"
            self.hot_storage.upload(image_pair["thumbnail_path"], thumb_s3_key)

            profile_s3_key = f"cast_auto_screenshots/profile/{image_pair['image_name']}"
            self.hot_storage.upload(image_pair["profile_path"], profile_s3_key)


if __name__ == "__main__":
    REDIS_URL = os.getenv("REDIS_URL")
    DB_URL = os.getenv('DB_URL')
    SHARED_VOLUME = "/shared"

    ## Set up S3 clients
    storage_env = {
        "HOT_S3_KEY": os.getenv("HOT_S3_KEY"),
        "HOT_S3_SECRET": os.getenv("HOT_S3_SECRET"),
        "HOT_S3_REGION": os.getenv("HOT_S3_REGION"),
        "HOT_S3_BUCKET": os.getenv("HOT_S3_BUCKET"),
        "HOT_S3_ENDPOINT": os.getenv("HOT_S3_ENDPOINT"),

        "COLD_S3_KEY": os.getenv("COLD_S3_KEY"),
        "COLD_S3_SECRET": os.getenv("COLD_S3_SECRET"),
        "COLD_S3_REGION": os.getenv("COLD_S3_REGION"),
        "COLD_S3_BUCKET": os.getenv("COLD_S3_BUCKET"),
        "COLD_S3_ENDPOINT": os.getenv("COLD_S3_ENDPOINT"),
    }

    missing_env = [k for k,v in storage_env.items() if not v]
    if missing_env:
        raise EnvironmentError(f"Missing required env vars: {', '.join(missing_env)}")

    hot_s3_client = boto3.client(
        "s3",
        region_name=storage_env["HOT_S3_REGION"],
        endpoint_url=storage_env["HOT_S3_ENDPOINT"],
        aws_access_key_id=storage_env["HOT_S3_KEY"],
        aws_secret_access_key=storage_env["HOT_S3_SECRET"],
    )

    hot_storage = s.S3StorageBackend(
        client=hot_s3_client,
        bucket=str(storage_env["HOT_S3_BUCKET"])
    )

    cold_s3_client = boto3.client(
        "s3",
        region_name=storage_env["COLD_S3_REGION"],
        endpoint_url=storage_env["COLD_S3_ENDPOINT"],
        aws_access_key_id=storage_env["COLD_S3_KEY"],
        aws_secret_access_key=storage_env["COLD_S3_SECRET"],
    )

    cold_storage = s.S3StorageBackend(
        client=cold_s3_client,
        bucket=str(storage_env["COLD_S3_BUCKET"]),
        public_read=False,
    )

    # Configure celery app
    app = Celery("orchestrator", broker=REDIS_URL, backend=REDIS_URL)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
    )

    dispatcher = dp.CeleryTaskDispatcher(app)

    orchestrator = Orchestrator(
        db=db.PipelineDb(db_url=DB_URL),
        hot_storage=hot_storage,
        cold_storage=cold_storage,
        task_dispatcher=dispatcher,
        volume_path=SHARED_VOLUME
    )

    orchestrator.run_service()

