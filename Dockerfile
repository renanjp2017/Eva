FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    libsodium-dev \
    libopus-dev \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip uninstall -y discord discord.py
RUN pip install --no-cache-dir PyNaCl
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]