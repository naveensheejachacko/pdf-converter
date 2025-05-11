from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os
import subprocess
import asyncio  # Add this with other importrt
from pathlib import Path
from uuid import uuid4
import time
import os.path

def format_size(size):
    """Convert size in bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

# Update size constants
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
CHUNK_SIZE = 4096  # 4KB chunks for better memory usage
SMALL_FILE_THRESHOLD = 2 * 1024 * 1024  # 2MB threshold for small files

app = FastAPI()

# Configure templates
templates = Jinja2Templates(directory="templates")

# Create required directories
UPLOAD_DIR = Path("uploads")
STATIC_DIR = Path("static")
UPLOAD_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# Mount static files with absolute path
app.mount("/static", StaticFiles(directory=str(STATIC_DIR.absolute())), name="static")

SUPPORTED_FORMATS = ('.doc', '.docx')
UNSUPPORTED_FORMATS = ('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.txt')

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(
        name="index.html",
        context={
            "request": request, 
            "title": "PDF Converter - Convert DOC/DOCX to PDF"
        }
    )

@app.post("/convert-to-pdf/")
async def convert_to_pdf(file: UploadFile = File(...)):
    """Convert DOC/DOCX files to PDF"""
    filename_lower = file.filename.lower()
    
    # Format checks
    if any(filename_lower.endswith(fmt) for fmt in UNSUPPORTED_FORMATS):
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot convert {file.filename}. This tool only converts DOC/DOCX files to PDF."
        )
    
    if not any(filename_lower.endswith(fmt) for fmt in SUPPORTED_FORMATS):
        raise HTTPException(
            status_code=400, 
            detail="Only DOC/DOCX files are supported. Please upload a valid document file."
        )
    
    try:
        # Check file size with first chunk
        initial_chunk = await file.read(64 * 1024)  # Read first 64KB
        file_size = len(initial_chunk)
        
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File size ({format_size(file_size)}) exceeds limit of 10MB"
            )
        
        # Read the rest of the file
        chunks = [initial_chunk]
        total_size = file_size
        
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail="File size exceeds 10MB limit"
                )
            chunks.append(chunk)
        
        contents = b''.join(chunks)

        # Generate unique filename with proper path handling
        unique_id = str(uuid4())
        input_filename = f"{unique_id}_{file.filename}"
        file_path = UPLOAD_DIR / input_filename
        
        # Save uploaded file
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Convert to PDF using LibreOffice (fixed command parameters)
        process = await asyncio.create_subprocess_exec(
            "soffice",  # Use soffice instead of libreoffice
            "--headless",
            "--convert-to",
            "pdf:writer_pdf_Export",  # Specify the PDF export filter
            "--outdir",
            str(UPLOAD_DIR.absolute()),  # Use absolute path
            str(file_path.absolute()),  # Use absolute path
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        # Get the output PDF path (LibreOffice creates it with .pdf extension)
        output_path = UPLOAD_DIR / f"{os.path.splitext(input_filename)[0]}.pdf"
        
        if process.returncode != 0:
            print(f"Conversion error: {stderr.decode()}")  # Debug output
            raise HTTPException(
                status_code=500,
                detail=f"Conversion failed: {stderr.decode()}"
            )
        
        # Wait a moment for file system
        await asyncio.sleep(1)
        
        # Verify the output file exists
        if not output_path.exists():
            print(f"Missing output file: {output_path}")  # Debug output
            raise HTTPException(
                status_code=500,
                detail=f"Conversion failed: Output file not found at {output_path}"
            )
        
        # Schedule cleanup task
        cleanup_task = asyncio.create_task(cleanup_files(file_path, output_path))
        
        # Return the PDF file without background task in FileResponse
        response = FileResponse(
            path=str(output_path),
            filename=os.path.splitext(file.filename)[0] + '.pdf',
            media_type="application/pdf"
        )
        
        # Add cleanup task to response headers to keep it alive
        response.background = cleanup_task
        return response
        
    except Exception as e:
        print(f"Error during conversion: {str(e)}")  # Debug output
        # Clean up files in case of error
        if file_path.exists():
            file_path.unlink()
        if output_path.exists():
            output_path.unlink()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))

# Update cleanup function to handle task properly
async def cleanup_files(*files):
    """Clean up temporary files with retry"""
    try:
        await asyncio.sleep(5)  # Wait for download to complete
        for file_path in files:
            if isinstance(file_path, (str, Path)):
                path = Path(file_path)
                try:
                    if path.exists():
                        path.unlink()
                except Exception as e:
                    print(f"First cleanup attempt failed for {path}: {e}")
                    # Retry once after delay
                    await asyncio.sleep(2)
                    if path.exists():
                        path.unlink(missing_ok=True)
    except Exception as e:
        print(f"Cleanup error: {e}")

# Add cleanup task
async def cleanup_old_files():
    """Remove files older than 1 hour"""
    while True:
        try:
            current_time = time.time()
            for file_path in UPLOAD_DIR.glob('*'):
                if current_time - file_path.stat().st_mtime > 3600:  # 1 hour
                    file_path.unlink(missing_ok=True)
        except Exception:
            pass
        await asyncio.sleep(3600)  # Run every hour

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_files())