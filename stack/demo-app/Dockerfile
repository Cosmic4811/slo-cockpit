# shop-api demo service (the same image also runs the load generator).
# Pulled from AWS's public mirror of Docker Hub's official images: no Docker Hub pull limits.
FROM public.ecr.aws/docker/library/python:3.14.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --root-user-action=ignore -r requirements.txt

COPY app.py loadgen.py ./

# Never run the app as root inside the container.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001

EXPOSE 8080
# 1 process with 8 threads: the fault-injection switch lives in memory, so it must be one process.
# --no-control-socket: we don't use gunicorn's runtime control socket (and the disk is read-only).
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", \
     "--worker-tmp-dir", "/dev/shm", "--no-control-socket", "--timeout", "30", \
     "--graceful-timeout", "10", "--log-level", "warning", "app:app"]
