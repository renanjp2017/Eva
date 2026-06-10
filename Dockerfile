FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema para Pillow + fontes
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    libpng-dev \
    libfreetype6-dev \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia TODO o projeto (cogs, assets, cards, etc.)
COPY . .

CMD ["python", "-u", "bot.py"]
