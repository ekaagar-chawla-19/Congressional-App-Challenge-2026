# Hemlock Sentinel API with the production model (CPU, ONNX Runtime; no PyTorch).
#   docker build -t hemlock-api .
#   docker run -p 8000:8000 -v hemlock-data:/data -e ANTHROPIC_API_KEY hemlock-api   -> http://localhost:8000/app
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HEMLOCK_DATA=/data HEMLOCK_DB=/data/trees.sqlite HEMLOCK_BLOBS=/data/blobs
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[onnx,app,assistant]"
COPY models ./models
ENV HEMLOCK_MODEL=/app/models/production/hemlock.onnx \
    HEMLOCK_CALIBRATION=/app/models/production/calibration.json \
    HEMLOCK_GAMMA_MODEL=/app/models/gamma/gamma.onnx \
    HEMLOCK_GAMMA_CALIBRATION=/app/models/gamma/calibration.json \
    HEMLOCK_FACE_MODEL=/app/models/third_party/face_detection_yunet_2023mar.onnx
VOLUME /data
EXPOSE 8000
CMD ["hemlock-api", "--port", "8000"]
