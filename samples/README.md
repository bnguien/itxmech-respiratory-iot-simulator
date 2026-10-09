# RespiCare IoT Simulator — Test WAV Samples

This directory holds sample WAV files used for testing the stethoscope simulator.

## Required Format

All WAV files used with the RespiCare stethoscope simulator **must** match:

| Property      | Value       |
|---------------|-------------|
| Encoding      | PCM (linear) |
| Channels      | 1 (mono)    |
| Bit depth     | 16-bit      |
| Sample rate   | 16,000 Hz   |

## Generating a Test WAV with ffmpeg

```bash
# Convert any audio file to the required format:
ffmpeg -i input.wav \
  -ar 16000 \
  -ac 1 \
  -acodec pcm_s16le \
  output-16k-mono.wav

# Generate a 5-second silent test WAV:
ffmpeg -f lavfi \
  -i "sine=frequency=440:duration=5" \
  -ar 16000 \
  -ac 1 \
  -acodec pcm_s16le \
  test-tone-16k-mono.wav
```

## Generating a Test WAV with SoX

```bash
sox -n -r 16000 -c 1 -b 16 test-silence-16k-mono.wav trim 0.0 5.0
```

## Notes

- Do **not** commit real patient audio data.
- Place synthetic/test-only WAV files here for local development.
- The simulator will validate the WAV format before attempting any upload.
