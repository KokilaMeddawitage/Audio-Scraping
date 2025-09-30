import os
import argparse
import collections
import contextlib
import wave
import webrtcvad
import yt_dlp

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
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])

    # Ensure mono, 16kHz WAV
    import subprocess
    fixed_file = "input_fixed.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", output_file,
        "-ac", "1", "-ar", "16000", fixed_file
    ])
    os.replace(fixed_file, output_file)


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

def split_with_vad(input_file="input.wav", out_dir="clips", aggressiveness=2):
    with contextlib.closing(wave.open(input_file, 'rb')) as wf:
        num_channels = wf.getnchannels()
        assert num_channels == 1
        sample_width = wf.getsampwidth()
        assert sample_width == 2
        sample_rate = wf.getframerate()
        assert sample_rate in (8000, 16000, 32000, 48000)
        pcm_data = wf.readframes(wf.getnframes())

    vad = webrtcvad.Vad(aggressiveness)
    frames = list(frame_generator(30, pcm_data, sample_rate))
    segments = vad_collector(sample_rate, 30, 300, vad, frames)

    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    for i, (start, end) in enumerate(segments):
        duration = end - start
        if duration < 5 or duration > 15:
            continue
        with contextlib.closing(wave.open(input_file, 'rb')) as wf:
            wf.setpos(int(start * sample_rate))
            frames_to_read = int(duration * sample_rate)
            data = wf.readframes(frames_to_read)
        out_path = os.path.join(out_dir, f"clip_{i+1}.wav")
        with wave.open(out_path, 'wb') as out_f:
            out_f.setnchannels(1)
            out_f.setsampwidth(2)
            out_f.setframerate(sample_rate)
            out_f.writeframes(data)
        print(f"Saved {out_path}")

def main():
    parser = argparse.ArgumentParser(description="YouTube Audio Downloader & VAD Splitter")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--output", default="input.wav", help="Output WAV filename")
    parser.add_argument("--clips_dir", default="clips", help="Directory to save clips")
    parser.add_argument("--vad_level", type=int, default=2, help="VAD aggressiveness (0-3)")
    args = parser.parse_args()

    print("Downloading audio...")
    download_audio(args.url, args.output)
    print("Splitting with VAD...")
    split_with_vad(args.output, args.clips_dir, aggressiveness=args.vad_level)
    print("Done!")

if __name__ == "__main__":
    main()
