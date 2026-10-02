# Environment report

Inspection date: 2026-10-02. Host: `pakka-dell`. The project virtualenv was created after this inspection and is recorded at the bottom. No tokens are included.

## Observed environment

| Item | Observation |
| --- | --- |
| OS | EndeavourOS (Arch-like), build id 2025.03.19 |
| Kernel | `7.2.3-arch1-3` SMP PREEMPT_DYNAMIC, x86_64 |
| CPU | 12th Gen Intel Core i7-12700H, 14 cores / 20 threads, max 4700 MHz |
| RAM | `MemTotal` 16,042,076 kB (about 15.3 GiB). `free -h` reported 15 GiB total, about 5.1 GiB available, swap 0 |
| Discrete GPU | NVIDIA GeForce RTX 3060 Laptop GPU, 6144 MiB, driver 610.57.04, via `nvidia-smi` |
| CUDA | `nvidia-smi` reports CUDA UMD 13.3. `nvcc` reports release 13.3, V13.3.73 |
| Integrated GPU | Intel Alder Lake-P GT2 (Iris Xe), from `lspci`. VRAM was not queried |
| Apple Silicon | No. `uname` is Linux x86_64 |
| System Python | CPython 3.14.7 at `/usr/bin/python3` |
| pip | `pip3` is pip 26.2.1 for Python 3.14. `pip` on `PATH` is pip 20.3.4 for Python 2.7 under `~/.local` |
| uv | 0.11.6 at `~/.local/bin/uv` |
| Node | v26.8.1 at `/usr/bin/node` |
| npm | 11.12.1 |
| pnpm | Not installed at inspection time |
| FFmpeg | n9.0.1, configured with `--enable-nvdec`, `--enable-nvenc`, and `--enable-cuda-llvm` |
| ffprobe | n9.0.1 |
| Git | 2.55.0 |
| GitHub CLI | 2.83.2, authenticated as `Ammar-1652` for github.com, HTTPS git protocol. Scopes include `repo`. The token value was not copied |
| Directory | `/home/pakka/hero_edit` |
| Git | Not a repository at inspection time. No remotes |
| Disk | `/` is 467G with 26G free (95% used) on `/dev/nvme0n1p2` |
| Make | GNU Make 4.4.1 |

## Suitability

Judged only from the tools that actually ran.

- CPU transcription: the CPU and RAM can host a local ASR process. No ASR library was imported and no model was loaded, so speed and memory headroom were not measured. Swap is off, and available RAM at inspection was about 5 GiB, so a large model beside a desktop session can run out of memory.
- CUDA transcription: the laptop GPU, driver, and CUDA 13.3 toolkit are present. No PyTorch, CTranslate2, or faster-whisper build was installed or executed. CUDA is the likely acceleration path after a wheel that matches CPython and CUDA 13.3 is proven. It is not proven in Round 1.
- Apple Silicon transcription: not applicable.
- Local Remotion rendering: Node and an ffmpeg build with NVENC are present. Disk free space is 26 GiB. Whether the installed Remotion release accepts Node v26 is a separate install result, recorded in the Round 1 validation report. No frame was rendered.

## Missing at inspection

- pnpm
- A git repository and GitHub remote (created later in Round 1)
- Python ASR / CUDA inference packages (intentionally not installed)
- Corepack (not on `PATH`)

`pip` pointing at Python 2.7 is a footgun. Use `uv run` or `pip3`.

## Blockers

- None for Round 1 code, tests, or the SQLite CLI.
- Disk at 95% is a practical blocker for storing long-form sources, proxies, and model weights until space is freed. That blocks comfortable Round 2/3 work, not the foundation tests.
- Low available RAM and no swap are a risk for local ASR, not a Round 1 test failure.

## Recommendations

- Keep the project on uv-managed CPython 3.11 (`.python-version`). Do not point the package at system 3.14 until ASR wheels are known to exist for it.
- Install pnpm for `apps/renderer`.
- Free disk space before downloading footage or weights.
- Install ffmpeg from the EndeavourOS / Arch repositories if a future machine lacks it. This machine already has n9.0.1.
- Re-check `nvidia-smi` and a tiny faster-whisper import in Round 3 before choosing a model size. Do not assume the 6 GiB laptop GPU can hold a large model plus activations.

## Commands used

```bash
uname -a
cat /etc/os-release
uname -m
lscpu
grep -m1 "model name" /proc/cpuinfo
free -h
grep -E "MemTotal|MemAvailable" /proc/meminfo
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
nvidia-smi
lspci | grep -Ei "vga|3d|display|nvidia"
nvcc --version
python3 --version
pip3 --version
pip --version
uv --version
node --version
npm --version
pnpm --version
ffmpeg -version
ffprobe -version
git --version
gh --version
gh auth status
pwd
git status -sb
git remote -v
df -h /
make --version
```

`gh auth status` printed a redacted token. The redacted line was not copied into this file.

## Project interpreter

`uv sync --all-groups` created `.venv` with CPython 3.11.15 (`uv run python` prints `3.11.15`). `.python-version` is `3.11`. System `/usr/bin/python3` remains 3.14.7 and is not the interpreter for tests or the CLI.

pnpm 10.34.6 was installed after the inspection (`npm install -g pnpm@10`) because it was missing. The renderer lockfile was produced with that pnpm.
