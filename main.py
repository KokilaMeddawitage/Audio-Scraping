import os
import argparse
import collections
import contextlib
import wave
import webrtcvad
import yt_dlp
import csv
import json
import re

def extract_video_id(youtube_url):
    """Extract YouTube video ID from URL."""
    patterns = [
        r'(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtu\.be\/)([a-zA-Z0-9_-]{11})',
        r'(?:youtube\.com\/v\/)([a-zA-Z0-9_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, youtube_url)
        if match:
            return match.group(1)
    return None

def download_audio(youtube_url, output_file="input.wav"):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_file,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
    }
    
    # Get video metadata
    metadata = None
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # First extract metadata
        info = ydl.extract_info(youtube_url, download=False)
        metadata = {
            'video_id': info.get('id'),
            'title': info.get('title'),
            'description': info.get('description'),
            'duration': info.get('duration'),
            'uploader': info.get('uploader'),
            'upload_date': info.get('upload_date'),
            'view_count': info.get('view_count'),
            'like_count': info.get('like_count'),
            'thumbnail': info.get('thumbnail'),
            'url': youtube_url
        }
        
        # Then download
        ydl.download([youtube_url])

    # Ensure mono, 16kHz WAV
    import subprocess
    
    # Check if yt-dlp created a file with double extension
    double_ext_file = output_file + ".wav"
    actual_input_file = double_ext_file if os.path.exists(double_ext_file) else output_file
    
    if not os.path.exists(actual_input_file):
        raise FileNotFoundError(f"Downloaded audio file not found: {actual_input_file}")
    
    fixed_file = "input_fixed.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", actual_input_file,
        "-ac", "1", "-ar", "16000", fixed_file
    ], check=True)
    
    # Remove the original downloaded file (which might have double extension)
    if os.path.exists(actual_input_file):
        os.remove(actual_input_file)
    
    # Move the fixed file to the desired output location
    os.rename(fixed_file, output_file)
    
    return metadata


class Frame(object):
    def __init__(self, bytes, timestamp, duration):
        self.bytes = bytes
        self.timestamp = timestamp
        self.duration = duration

def frame_generator(frame_duration_ms, audio, sample_rate):
    n = int(sample_rate * (frame_duration_ms / 1000.0) * 2)
    offset = 0
    timestamp = 0.0
    duration = (float(n) / sample_rate) / 2.0
    while offset + n <= len(audio):
        yield Frame(audio[offset:offset + n], timestamp, duration)
        timestamp += duration
        offset += n

def vad_collector(sample_rate, frame_duration_ms, padding_duration_ms, vad, frames):
    num_padding_frames = int(padding_duration_ms / frame_duration_ms)
    ring_buffer = collections.deque(maxlen=num_padding_frames)
    triggered = False
    voiced_frames = []
    segments = []

    for frame in frames:
        is_speech = vad.is_speech(frame.bytes, sample_rate)

        if not triggered:
            ring_buffer.append((frame, is_speech))
            num_voiced = len([f for f, speech in ring_buffer if speech])
            if num_voiced > 0.9 * ring_buffer.maxlen:
                triggered = True
                for f, s in ring_buffer:
                    voiced_frames.append(f)
                ring_buffer.clear()
        else:
            voiced_frames.append(frame)
            ring_buffer.append((frame, is_speech))
            num_unvoiced = len([f for f, speech in ring_buffer if not speech])
            if num_unvoiced > 0.9 * ring_buffer.maxlen:
                triggered = False
                segment_start = voiced_frames[0].timestamp
                segment_end = voiced_frames[-1].timestamp + voiced_frames[-1].duration
                segments.append((segment_start, segment_end))
                ring_buffer.clear()
                voiced_frames = []
    if voiced_frames:
        segment_start = voiced_frames[0].timestamp
        segment_end = voiced_frames[-1].timestamp + voiced_frames[-1].duration
        segments.append((segment_start, segment_end))
    return segments

def split_with_vad(input_file="input.wav", out_dir="clips", video_id=None, aggressiveness=2, start_padding=1.0, end_padding=0.5):
    with contextlib.closing(wave.open(input_file, 'rb')) as wf:
        num_channels = wf.getnchannels()
        assert num_channels == 1
        sample_width = wf.getsampwidth()
        assert sample_width == 2
        sample_rate = wf.getframerate()
        assert sample_rate in (8000, 16000, 32000, 48000)
        pcm_data = wf.readframes(wf.getnframes())
        total_duration = len(pcm_data) / (sample_rate * sample_width)

    vad = webrtcvad.Vad(aggressiveness)
    frames = list(frame_generator(30, pcm_data, sample_rate))
    segments = vad_collector(sample_rate, 30, 300, vad, frames)

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    # Prepare CSV data
    csv_data = []
    clip_counter = 1

    for i, (start, end) in enumerate(segments):
        duration = end - start
        if duration < 4 or duration > 10:
            continue
            
        # Create clip filename with new naming convention
        if video_id:
            clip_name = f"{video_id}-{clip_counter:03d}.wav"
        else:
            clip_name = f"clip_{clip_counter:03d}.wav"
        
        # Extract original audio segment (without extending boundaries)
        with contextlib.closing(wave.open(input_file, 'rb')) as wf:
            wf.setpos(int(start * sample_rate))
            frames_to_read = int(duration * sample_rate)
            audio_data = wf.readframes(frames_to_read)
        
        # Create silent padding for start and end
        start_padding_frames = int(start_padding * sample_rate)
        end_padding_frames = int(end_padding * sample_rate)
        start_silence_bytes = b'\x00' * (start_padding_frames * sample_width)
        end_silence_bytes = b'\x00' * (end_padding_frames * sample_width)
        
        # Combine: start padding + audio + end padding
        padded_data = start_silence_bytes + audio_data + end_silence_bytes
        padded_duration = duration + start_padding + end_padding
            
        out_path = os.path.join(out_dir, clip_name)
        with wave.open(out_path, 'wb') as out_f:
            out_f.setnchannels(1)
            out_f.setsampwidth(2)
            out_f.setframerate(sample_rate)
            out_f.writeframes(padded_data)
        
        # Add to CSV data (essential info only)
        csv_data.append({
            'clip_name': clip_name,
            'start_time': round(start, 2),
            'end_time': round(end, 2),
            'duration': round(duration, 2),
            'padded_duration': round(padded_duration, 2),
            'start_padding_seconds': start_padding,
            'end_padding_seconds': end_padding
        })
        
        print(f"Saved {out_path}")
        clip_counter += 1

    # Save CSV file
    csv_path = os.path.join(out_dir, 'clips_metadata.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['clip_name', 'start_time', 'end_time', 'duration', 
                     'padded_duration', 'start_padding_seconds', 'end_padding_seconds']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_data)
    
    print(f"CSV metadata saved to {csv_path}")
    return csv_data

def save_metadata_json(metadata, output_dir):
    """Save video metadata to JSON file."""
    if metadata:
        json_path = os.path.join(output_dir, 'metadata.json')
        with open(json_path, 'w', encoding='utf-8') as jsonfile:
            json.dump(metadata, jsonfile, indent=2, ensure_ascii=False)
        print(f"Video metadata saved to {json_path}")

def main():
    parser = argparse.ArgumentParser(description="YouTube Audio Downloader & VAD Splitter")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--output", default="input.wav", help="Output WAV filename")
    parser.add_argument("--base_dir", default=".", help="Base directory to create video folder")
    parser.add_argument("--vad_level", type=int, default=2, help="VAD aggressiveness (0-3)")
    parser.add_argument("--start_padding", type=float, default=1.0, help="Silent padding in seconds to add to beginning of clips (default: 1.0)")
    parser.add_argument("--end_padding", type=float, default=0.5, help="Silent padding in seconds to add to end of clips (default: 0.5)")
    args = parser.parse_args()

    # Extract video ID
    video_id = extract_video_id(args.url)
    if not video_id:
        print("Error: Could not extract video ID from URL")
        return

    # Create video-specific directory
    output_dir = os.path.join(args.base_dir, video_id)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Set paths for temporary and output files
    temp_audio_file = os.path.join(output_dir, "temp_audio.wav")

    print(f"Processing video ID: {video_id}")
    print("Downloading audio...")
    metadata = download_audio(args.url, temp_audio_file)
    
    print("Saving video metadata...")
    save_metadata_json(metadata, output_dir)
    
    print("Splitting with VAD...")
    clip_data = split_with_vad(temp_audio_file, output_dir, video_id, aggressiveness=args.vad_level, start_padding=args.start_padding, end_padding=args.end_padding)
    
    # Clean up temporary audio file
    if os.path.exists(temp_audio_file):
        os.remove(temp_audio_file)
    
    print(f"Done! Created {len(clip_data)} clips in '{output_dir}' directory")
    print(f"- Audio clips: {video_id}-001.wav, {video_id}-002.wav, ...")
    print(f"- Metadata: clips_metadata.csv and metadata.json")

if __name__ == "__main__":
    main()
