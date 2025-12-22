FROM python:3.11-slim

WORKDIR /app

# Create data directory for persistent storage
RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HuggingFace Spaces requires port 7860
EXPOSE 7860

# Set environment variable for HF Spaces
ENV HF_SPACES=true
ENV DATA_DIR=/data

CMD ["python", "main.py"]
