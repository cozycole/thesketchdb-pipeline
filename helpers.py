from datetime import time
import os
from typing import  TypedDict, List, Dict
import uuid

from psycopg2.extras import RealDictCursor, execute_values

def get_pending_jobs(conn):
    """Fetch pending jobs from the database."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, sketch_id, video_filename, status
            FROM pipeline_jobs
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        return cur.fetchone()

def update_job_status(conn, job_id, status, error=None):
    """Update job status in the database."""
    with conn.cursor() as cur:
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
        conn.commit()

def get_screenshot_summary(directory_path: str) -> List[Dict[str, str]]:
    """
    Parse a directory of images and extract cluster_id, image_number pairs
    with their corresponding profile and thumbnail paths.
    
    Args:
        directory_path: Path to the directory containing the images
        
    Returns:
        List of dictionaries, each containing:
        - cluster_id: The cluster identifier
        - image_number: The image number within the cluster
        - profile_path: Path to the profile image
        - thumbnail_path: Path to the thumbnail image
    """
    results = []
    pairs = {}
    
    for filename in os.listdir(directory_path):
        # Skip non-jpg files
        if not filename.endswith('.jpg'):
            continue

        parts = filename.replace('.jpg', '').split('_')
        if len(parts) >= 4 and parts[1] == 'cluster':
            cluster_id = parts[0]
            image_number = parts[2]
            image_type = parts[3]  # 'profile' or 'thumbnail'

            key = (cluster_id, image_number)

            if key not in pairs:
                pairs[key] = {
                    'cluster_id': cluster_id,
                    'image_number': image_number,
                    'profile_path': None,
                    'thumbnail_path': None
                }

            full_path = os.path.join(directory_path, filename)
            if image_type == 'profile':
                pairs[key]['profile_path'] = full_path
            elif image_type == 'thumbnail':
                pairs[key]['thumbnail_path'] = full_path

    for pair_data in pairs.values():
        if pair_data['profile_path'] and pair_data['thumbnail_path']:
            results.append(pair_data)

    results.sort(key=lambda x: (x['cluster_id'], x['image_number']))
    return results

def insert_screenshots(image_pairs: List[Dict[str, str]], sketch_id: int, conn):
    """
    Insert image pairs into the cast_auto_screenshots table.
    
    Args:
        image_pairs: List of dictionaries from parse_image_directory()
        sketch_id: The sketch ID to associate with these screenshots
        conn: psycopg2 database connection object
        
    Returns:
        Number of records inserted
    """
    cursor = conn.cursor()
    inserted_count = 0
    
    try:
        for pair in image_pairs:
            img_name = f"{uuid.uuid4()}.jpg"
            cursor.execute("""
                INSERT INTO cast_auto_screenshots 
                (sketch_id, cluster_number, image_number, thumbnail_img, profile_img)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                sketch_id,
                int(pair['cluster_id']),
                int(pair['image_number']),
                pair['image_name'],
                pair['image_name']
            ))
            inserted_count += 1
        
        conn.commit()
        return inserted_count
        
    except Exception as e:
        conn.rollback()
        raise Exception(f"Failed to insert screenshots: {str(e)}")
    finally:
        cursor.close()

class SubtitleEntry(TypedDict):
    start: str
    end: str
    text: str

def srt_time_to_time(srt_timestamp: str) -> time:
    """
    Convert SRT timestamp format (HH:MM:SS,mmm) to Python time object.

    Args:
        srt_timestamp: Timestamp in format "00:00:13,900"

    Returns:
        Python time object with microsecond precision
    """
    # Replace comma with period for parsing
    timestamp = srt_timestamp.replace(',', '.')

    # Parse: HH:MM:SS.mmm
    parts = timestamp.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds_parts = parts[2].split('.')
    seconds = int(seconds_parts[0])
    milliseconds = int(seconds_parts[1])

    # Convert milliseconds to microseconds
    microseconds = milliseconds * 1000

    return time(hour=hours, minute=minutes, second=seconds, microsecond=microseconds)

def parse_srt_file(srt_path):
    subtitles = []
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    entries = content.strip().split("\n\n")
    for entry in entries:
        lines = entry.strip().split("\n")
        if len(lines) >= 3:
            index = lines[0]
            timestamp = lines[1]
            text = " ".join(lines[2:])

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

    return subtitles

def insert_srt_lines(conn, srt_lines, sketch_id) -> int:
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
    cursor = None
    try:
        cursor = conn.cursor()

        values = []
        for line in srt_lines:
            start_time = srt_time_to_time(line['start_time'])
            end_time = srt_time_to_time(line['end_time'])
            text = line['text']
            line_number = int(line['index'])

            values.append((sketch_id, line_number, start_time, end_time, text))

        # Batch insert using execute_values (most efficient method)
        insert_query = f"""
            INSERT INTO transcription_lines (sketch_id, line_number, start_time, end_time, text)
            VALUES %s
        """

        execute_values(cursor, insert_query, values)

        conn.commit()

        return len(values)

    except Exception as e:
        if conn:
            conn.rollback()
        raise Exception(f"Error inserting subtitles: {str(e)}")

    finally:
        if cursor:
            cursor.close()
