FROM python:3.8 as python_with_os_libs

RUN apt-get update && apt-get install -y \
    libmariadb3 \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*

FROM python_with_os_libs as python_with_libraries

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

FROM python_with_libraries

WORKDIR /image-transform

ENV PYTHONUNBUFFERED="1" \
    DB_HOST="127.0.0.1" \
    DB_TABLE="photos2" \
    DB_USERNAME="photos" \
    DB_PASSWORD="photos" \
    POOL_SIZE="10" \
    ROOT_CONTEXT="/photos/photo/" \
    LFU_CACHE_MAX_COUNT="32"

COPY src .

EXPOSE 8080

VOLUME /mnt/photos

CMD ["python", "server.py"]
