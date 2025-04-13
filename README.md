# PDF Converter API

A FastAPI-based service that converts DOC/DOCX files to PDF using LibreOffice.

## Features
- Convert DOC/DOCX files to PDF
- File size limit: 10MB
- Automatic cleanup of temporary files
- Docker support

## Running with Docker

1. Build and start the container:
```bash
docker-compose up --build
```

2. Access the API at http://localhost:8000

## Development Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the development server:
```bash
uvicorn main:app --reload
```

## API Endpoints

- `GET /`: Home page
- `POST /convert-to-pdf/`: Convert DOC/DOCX to PDF

## Environment Variables

- `MAX_FILE_SIZE`: Maximum file size in bytes (default: 10MB)