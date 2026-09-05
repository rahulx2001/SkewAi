"""In-cabin vehicle acoustics and driving environment detector."""

from __future__ import annotations

import numpy as np


def detect_driving_environment(pcm_16k_chunk: bytes) -> bool:
    """
    Evaluates spectral energy and low-frequency rumble (40Hz - 250Hz) 
    characteristic of vehicular highway travel and road noise.
    """
    if not pcm_16k_chunk:
        return False

    audio_data = np.frombuffer(pcm_16k_chunk, dtype=np.int16).astype(np.float32)
    if len(audio_data) == 0:
        return False

    # Compute Fast Fourier Transform
    fft = np.fft.rfft(audio_data)
    freqs = np.fft.rfftfreq(len(audio_data), 1.0 / 16000)
    magnitudes = np.abs(fft)

    # Calculate ratio of low-frequency engine/road hum to speech frequencies (300Hz-3400Hz)
    road_band = np.sum(magnitudes[(freqs >= 40) & (freqs <= 250)])
    speech_band = np.sum(magnitudes[(freqs >= 300) & (freqs <= 3400)]) + 1e-6

    rumble_ratio = road_band / speech_band
    # Threshold empirically calibrated against in-cabin automotive datasets
    return bool(rumble_ratio > 3.8)


DRIVE_SAFETY_SCRIPT = (
    "I can hear substantial background traffic and engine noise. For your safety, "
    "are you currently operating a motor vehicle? If so, I can immediately send you "
    "a secure link via text message to complete this once you are safely parked."
)
