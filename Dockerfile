# Образ только с программами (Python, FFmpeg, Opus, Deno, шрифты, библиотеки бота).
# Сам код и данные (.env, bot.db, настройки) лежат в папке, подключённой как /app (см. docker-compose.yml),
# поэтому обновления, которые бот скачивает сам, не пропадают при пересоздании контейнера.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libopus0 fonts-dejavu-core curl unzip ca-certificates \
 && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s -- -y \
 && apt-get purge -y unzip && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

ENV PYTHONUNBUFFERED=1
CMD ["python", "-X", "utf8", "supervisor.py"]
