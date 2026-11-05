---
name: image-reader
description: Read text and dimensions from images using local Windows OCR.
---

# Image Reader

Use read_image(path) for image text and dimensions. The output is OCR plus metadata, not visual scene understanding. Quote extracted text when relevant. Respect ocr_available and warning fields; do not claim unread images were understood. Windows needs an installed OCR language.
