# FluxClip engine + Studio API (also works as the CLI: docker run fluxclip run video.mp4)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY fluxclip ./fluxclip
RUN pip install --no-cache-dir ".[all]"
ENV FLUXCLIP_DATA=/data \
    FLUXCLIP_CACHE=/data/cache \
    HF_HOME=/data/cache/huggingface \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1
ENTRYPOINT ["fluxclip"]
CMD ["studio", "--host", "0.0.0.0", "--port", "8000"]
