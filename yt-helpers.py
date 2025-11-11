import os
import subprocess
from pathlib import Path

def sanitize_filename(title, max_length=50):
    """
    Sanitize the video title to create a safe directory/filename in snake_case.
    Remove or replace problematic characters, convert to snake_case, and limit length.
    """
    # Characters to remove or replace
    invalid_chars = '<>:"/\\|?*\'"`'
    for char in invalid_chars:
        title = title.replace(char, '')
    
    # Replace multiple spaces with single space and strip
    title = ' '.join(title.split())
    
    # Convert to snake_case
    title = title.lower().replace(' ', '_')
    
    # Remove any remaining non-alphanumeric characters except underscores and hyphens
    title = ''.join(c for c in title if c.isalnum() or c in '_-')
    
    # Replace multiple underscores/hyphens with single underscore
    while '__' in title or '--' in title or '_-' in title or '-_' in title:
        title = title.replace('__', '_').replace('--', '_').replace('_-', '_').replace('-_', '_')
    
    # Remove leading/trailing underscores or hyphens
    title = title.strip('_-')
    
    # Limit length
    if len(title) > max_length:
        title = title[:max_length].strip('_-')
    
    # Ensure we have a valid filename (not empty)
    if not title:
        title = 'untitled'
    
    return title

def yt_dlp_installed() -> bool:
    try:
        subprocess.run(['yt-dlp', '--version'], 
                      capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def download_youtube_video(url, output_dir, video_info):
    """
    Download the video using yt-dlp with audio extraction.
    """
    try:
        safe_title = sanitize_filename(video_info['title'])
        video_filename = f"{safe_title}.%(ext)s"
        video_path = os.path.join(output_dir, video_filename)
        
        cmd = [
            'yt-dlp',
            '--format', 'bestvideo+bestaudio/best',
            '--merge-output-format', 'mp4',
            "--extractor-args", "youtube:player-client=default,-tv_simply",
            '--output', video_path,
            url
        ]
        
        print(f"Downloading video: {video_info['title']}")
        print(f"Output directory: {output_dir}")
        
        subprocess.run(cmd, check=True)
        
        # Find the actual downloaded file
        downloaded_files = list(Path(output_dir).glob(f"{safe_title}.*"))
        if downloaded_files:
            actual_file = downloaded_files[0]
            print(f"Video downloaded successfully: {actual_file}")
            return str(actual_file)
        else:
            print("Warning: Could not locate downloaded file")
            return None
            
    except subprocess.CalledProcessError as e:
        print(f"Error downloading video: {e}")
        return None

def get_youtube_video_info(url):
    """
    Get video information using yt-dlp without downloading.
    Returns title and other metadata.
    """
    try:
        cmd = [
            'yt-dlp',
            '--print', 'title',
            '--print', 'id',
            '--print', 'duration',
            '--no-download',
            url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')
        
        return {
            'title': lines[0] if len(lines) > 0 else 'Unknown',
            'id': lines[1] if len(lines) > 1 else 'unknown',
            'duration': lines[2] if len(lines) > 2 else 'unknown'
        }
    except subprocess.CalledProcessError as e:
        print(f"Error getting video info: {e.stderr}")
        return None
