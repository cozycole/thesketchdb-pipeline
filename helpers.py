import os
from typing import  TypedDict, List, Dict

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


class SubtitleEntry(TypedDict):
    start: str
    end: str
    text: str

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
                    "start_time": srt_timestamp_to_ms(start_time),
                    "end_time": srt_timestamp_to_ms(end_time),
                    "text": text
                })

    return subtitles

def srt_timestamp_to_ms(timestamp: str) -> int:
    """
    Convert an SRT timestamp (e.g. "00:00:06,360") to milliseconds.
    """
    try:
        time_part, ms_part = timestamp.strip().split(",")
        hours, minutes, seconds = map(int, time_part.split(":"))
        milliseconds = int(ms_part)

        return (
            hours * 3_600_000
            + minutes * 60_000
            + seconds * 1_000
            + milliseconds
        )
    except Exception:
        raise ValueError("Invalid SRT timestamp format. Expected 'HH:MM:SS,mmm'")
