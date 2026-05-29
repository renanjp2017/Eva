FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    libffi-dev \
    libsodium-dev \
    python3-dev

WORKDIR /app

COPY requirements.txt .

RUN pip uninstall -y discord discord.py
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]