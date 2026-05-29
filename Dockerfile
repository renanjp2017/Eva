FROM python:3.11

RUN apt update && apt install -y ffmpeg

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]