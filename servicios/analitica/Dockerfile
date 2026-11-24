FROM spark:3.5.9-java17-python3
USER root
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.32.1" valkey==6.0.2
WORKDIR /opt/servicio
COPY app ./app
COPY spark ./spark
USER spark
EXPOSE 8000
CMD ["sh", "-c", "export PYTHONPATH=/opt/spark/python:$(ls /opt/spark/python/lib/py4j-*-src.zip) && exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]
