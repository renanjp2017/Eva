FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg

WORKDIR /app

COPY requirements.txt .
# O -U garante que o yt-dlp será instalado na versão mais recente disponível hoje
RUN pip install --no-cache-dir -U -r requirements.txt

# Copia o bot.py e o cookies.txt para dentro do contêiner
COPY . .

CMD ["python", "bot.py"]
