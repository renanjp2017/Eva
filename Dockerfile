FROM python:3.11-slim

# Instala ffmpeg, codecs de áudio do Opus e ferramentas essenciais de sistema
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libopus0 \
    libopus-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -U -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
