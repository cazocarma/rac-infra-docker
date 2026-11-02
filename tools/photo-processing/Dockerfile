# Isolated CPU proof image, not an activated production worker.
FROM golang:1.27.3
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr=5.5.0-1+b1 \
      tesseract-ocr-eng=1:4.1.0-2 \
      tesseract-ocr-spa=1:4.1.0-2 \
 && test -f /usr/share/tesseract-ocr/5/tessdata/eng.traineddata \
 && test -f /usr/share/tesseract-ocr/5/tessdata/spa.traineddata \
 && rm -rf /var/lib/apt/lists/*
ENV OMP_THREAD_LIMIT=1
WORKDIR /work
