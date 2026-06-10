FROM python:3.12-slim

WORKDIR /app

# Dependências de sistema para Pillow, CairoSVG e fontes
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    libpng-dev \
    libfreetype6-dev \
    fonts-dejavu-core \
    fonts-liberation \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements da raiz do projeto
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia TUDO (raiz + pasta cassino com assets/cards)
COPY . .

# Entra na pasta cassino e roda o truco_bot.py
WORKDIR /app/cassino

CMD ["python", "-u", "truco_bot.py"]
