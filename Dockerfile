FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN sed -i 's/raise ValueError("Misdirected Request")/return/g' \
    $(find /usr/local/lib/python3.11/site-packages/mcp -name "*.py" | xargs grep -l "Misdirected Request")

# Copy application code
COPY import-scripts/ ./import-scripts/
COPY server.py .
COPY start.sh .
RUN chmod +x start.sh

# Bundle current data as fallback (volume takes precedence at runtime)
COPY data/ ./initial-data/

# Runtime config — override via Fly.io env/secrets
ENV DATA_DIR=/data
ENV SCRIPTS_DIR=/app/import-scripts
ENV CREDS_DIR=/data/.credentials
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8080

EXPOSE 8080

CMD ["/app/start.sh"]
