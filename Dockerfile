FROM python:3.10-slim

# Set working directory inside the container
WORKDIR /app

# Copy all files to /app
COPY . .

# Install required Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Run your bot using gunicorn on port 8080
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "main:main"]
