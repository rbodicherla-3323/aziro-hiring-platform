FROM python:3.10-slim

# System deps for psycopg2, reportlab, pdfplumber, C/C++ code execution
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ \
    default-jdk \
    nodejs \
    libpq-dev \
    libfreetype6-dev libjpeg62-turbo-dev libpng-dev \
    mono-mcs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir gunicorn && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Create runtime dirs (volumes will mount over these)
RUN mkdir -p app/uploads app/runtime/reports app/runtime/proctoring \
             app/runtime/coding_exec_tmp instance

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "4", "--timeout", "300", "wsgi:app"]
