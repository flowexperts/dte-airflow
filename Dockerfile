FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install -e ".[dev]"
COPY . .
CMD ["uvicorn", "dte.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
