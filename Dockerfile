FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY . .

# Создание директории под данные
VOLUME ["/app/data"]

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
