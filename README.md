<<<<<<< HEAD
# Audio-Scraping
=======
# YouTube Audio Downloader & VAD Splitter

This project downloads audio from a YouTube video, converts it to WAV, and splits the audio into speech segments using Voice Activity Detection (VAD).

## Features
- Download audio from YouTube videos
- Convert audio to mono, 16kHz WAV
- Split audio into speech clips using WebRTC VAD

## Requirements
- Python 3.6+
- ffmpeg (must be installed and available in your PATH)

Install Python dependencies:
```
pip install -r requirements.txt
```

## Usage

1. Download and split audio from a YouTube video:
   ```
   python main.py "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
   ```

2. Optional arguments:
   - `--output`: Output WAV filename (default: input.wav)
   - `--clips_dir`: Directory to save clips (default: clips)
   - `--vad_level`: VAD aggressiveness (0-3, default: 2)

   Example:
   ```
   python main.py "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" --output myaudio.wav --clips_dir myclips --vad_level 3
   ```

3. The split audio clips will be saved in the specified clips directory.

## Notes
- Large audio files and output clips are ignored by git (see .gitignore).
- Make sure ffmpeg is installed and accessible from the command line.

## License
MIT License

>>>>>>> master
