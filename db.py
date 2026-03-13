from contextlib import contextmanager
import logging
import time
from typing import  List, Dict

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor, execute_values

logger = logging.getLogger(__name__)

class PipelineDb:
    def __init__(self, db_url, minconn=1, maxconn=5, retries=5, retry_delay=5):
        self._db_url = db_url
        self._wait_for_db(retries=retries, retry_delay=retry_delay)
        self.pool = SimpleConnectionPool(minconn, maxconn, dsn=db_url)

    def _wait_for_db(self, retries=5, retry_delay=5):
        last_error = None

        for attempt in range(1, retries + 1):
            try:
                conn = psycopg2.connect(self._db_url)
                conn.close()
                logger.info("Database connection successful")
                return
            except Exception as e:
                last_error = e
                logger.error(f"Database not ready (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(retry_delay)

        raise RuntimeError(f"Unable to connect to database after {retries} attempts") from last_error

    @contextmanager
    def cursor(self, cursor_factory=None):
        conn = self.pool.getconn()
        try:
            with conn:
                with conn.cursor(cursor_factory=cursor_factory) as cur:
                    yield cur
        finally:
            self.pool.putconn(conn)

    def close(self):
        self.pool.closeall()

    def get_pending_jobs(self):
        """Fetch pending jobs from the database."""

        with self.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT p.id, p.status, v.hot_s3_key, v.sketch_id
                FROM pipeline_jobs as p
                JOIN sketch_video as v ON p.video_id = v.id
                WHERE p.status = 'pending'
                ORDER BY p.created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """)
            return cur.fetchone()

    def update_job_status(self, job_id, status, error=None):
        """Update job status in the database."""
        with self.cursor() as cur:
            if error:
                cur.execute("""
                    UPDATE pipeline_jobs
                    SET status = %s, error = %s
                    WHERE id = %s
                """, (status, error, job_id))
            else:
                cur.execute("""
                    UPDATE pipeline_jobs
                    SET status = %s
                    WHERE id = %s
                """, (status, job_id))

    def set_archive(self, video_key, job_id):
        with self.cursor() as cur:
            cur.execute("""
                UPDATE sketch_video as sv 
                SET cold_s3_key = %s,archived_at=NOW() 
                FROM pipeline_jobs as pj 
                WHERE pj.video_id = sv.id 
                AND pj.id = %s;
            """, (video_key, job_id))

    def insert_srt_lines(self, srt_lines, sketch_id) -> int:
        """
        Insert all subtitle entries into a table in a single transaction.

        Args:
            srt_dict: Dictionary returned by parse_srt()
            connection_params: Dictionary with connection parameters 
                              (host, database, user, password, port)
            table_name: Name of the table to insert into (default: 'subtitles')

        Returns:
            Number of rows inserted
        """
        values = []

        for line in srt_lines:
            values.append((
                sketch_id,
                int(line["index"]),
                line["start_time"],
                line["end_time"],
                line["text"],
            ))

        with self.cursor() as cur:
            insert_query = """
                INSERT INTO transcription_lines (sketch_id, line_number, start_ms, end_ms, text)
                VALUES %s
            """

            execute_values(cur, insert_query, values)

            return len(values)

    def insert_screenshots(self, image_pairs: List[Dict[str, str]], sketch_id: int):
        """
        Insert image pairs into the cast_auto_screenshots table.
        
        Args:
            image_pairs: List of dictionaries from parse_image_directory()
            sketch_id: The sketch ID to associate with these screenshots
            conn: psycopg2 database connection object
            
        Returns:
            Number of records inserted
        """
        values = []
        for pair in image_pairs:
            values.append((
                sketch_id,
                int(pair['cluster_id']),
                int(pair['image_number']),
                pair['image_name'],
                pair['image_name']
            ))

        with self.cursor() as cur:
            insert_query = """
                INSERT INTO cast_auto_screenshots 
                (sketch_id, cluster_number, image_number, thumbnail_img, profile_img)
                VALUES %s
            """

            execute_values(cur, insert_query, values)

            return len(values)

