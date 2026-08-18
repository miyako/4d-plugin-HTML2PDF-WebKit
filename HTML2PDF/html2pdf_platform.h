#ifndef HTML2PDF_PLATFORM_H
#define HTML2PDF_PLATFORM_H

// Platform abstraction for HTML to PDF conversion
// Returns 0 on success, non-zero on error
int html2pdf_convert(const char* htmlPath, const char* pdfPath);

#endif
