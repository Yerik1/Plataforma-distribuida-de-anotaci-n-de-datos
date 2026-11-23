FROM python:3.12-slim
WORKDIR /dataset
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY generador_catalogo.py .
ENTRYPOINT ["python", "generador_catalogo.py"]
