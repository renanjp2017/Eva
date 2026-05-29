# Use Python 3.11 slim
FROM python:3.11-slim

# Evita buffering de logs
ENV PYTHONUNBUFFERED=1

# Diretório da aplicação
WORKDIR /app

# Instala dependências do sistema necessárias (ffmpeg para audio)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copia requirements e instala
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copia o código
COPY . /app

# Porta exposta (opcional)
EXPOSE 8080

# Comando padrão
CMD ["python", "bot.py"]