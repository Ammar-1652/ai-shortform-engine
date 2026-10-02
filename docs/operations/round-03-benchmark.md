# Round 3 benchmark

This measures whether faster-whisper runs on this machine. The input is one second of silence, not a podcast. It is not a word-error rate.

## Machine

- EndeavourOS, Intel i7-12700H, about 15.3 GiB RAM, no swap noted in the environment report
- NVIDIA GeForce RTX 3060 Laptop, 6144 MiB, driver 610.57.04
- CUDA toolkit 13.3 (`nvcc` on PATH)
- faster-whisper 1.2.1, CTranslate2 4.8.2, PyAV 18.1.0
- Model `tiny.en`, hub revision `0d3d19a32d3338f10357c0889762bd8d64bbdeba`, about 75 MiB on disk

## CPU

| Item | Value |
| --- | --- |
| Device | cpu |
| Compute type | int8 |
| Audio | 1.0 s, 16 kHz mono FLAC silence |
| Model load | 0.316 s |
| Load plus segment consumption | 0.710 s |
| Inference after load | about 0.39 s |
| Real-time factor | about 0.39 |
| Segments | 0 |
| Words | 0 |

A second cached run loaded in 0.308 s. The wall time moved around, which is expected for a one-second file. espeak-ng is not installed, so no speech phrase was synthesized. No TTS package was added.

Peak RAM and peak VRAM were not sampled. No monitoring package was added for that.

## GPU

An explicit CUDA run was attempted while CTranslate2 still reported CUDA compute types. Model construction returned, then segment generation failed:

`RuntimeError: Library libcublas.so.12 is not found or cannot be loaded`

`libcudnn.so.9` is also absent. `libcublas.so.13` is present and is not a substitute. The system CUDA install was not changed.

After that result, the runtime probe treats those missing libraries as CUDA unusable. A later smoke does not start a CUDA model. There is no GPU real-time factor.

## Auto

`--device auto` selects CPU `int8` and warns that `libcublas.so.12` and `libcudnn.so.9` did not load.

## Production profile

The default profile stays `small.en`, English, beam 5, VAD off. It was not downloaded and was not timed. `tiny.en` only proves the adapter, the clock, and the CPU path. A 6 GiB laptop GPU is not a reason to switch the default to a larger model while CUDA 12 libraries are missing. A later measurement can compare `small.en` and `medium.en` once GPU execution is actually possible, or on CPU if the operator accepts the runtime.
