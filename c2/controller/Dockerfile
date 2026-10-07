FROM python:3.12-alpine
RUN pip install --no-cache-dir "flask==3.1.*" "docker==7.1.*"
WORKDIR /app
COPY app.py .
COPY static ./static
EXPOSE 8080
CMD ["python", "-u", "app.py"]
