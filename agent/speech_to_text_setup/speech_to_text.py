import sounddevice as sd
from faster_whisper import WhisperModel
from scipy.io.wavfile import write


whisper_model = WhisperModel(
    "tiny",
    device="cpu",
    compute_type="int8"
)

SAMPLE_RATE = 16000
DURATION = 5

def record_audio(filename="input.wav"):

    audio = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16"
    )

    sd.wait()

    write(
        filename,
        SAMPLE_RATE,
        audio
    )

    return filename

def speech_to_text(audio_file):
    segments, _ = whisper_model.transcribe(
        audio_file
    )

    text = " ".join(
        segment.text
        for segment in segments
    )

    return text.strip()