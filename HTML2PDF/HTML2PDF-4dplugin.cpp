#include "HTML2PDF-4dplugin.h"
#include "html2pdf_platform.h"
#include <stdlib.h>
#include <string>

// Convert PA_Unistring (UTF-16) to std::string (UTF-8)
static std::string pa_unistring_to_utf8(PA_Unistring* ustr) {
    if (!ustr) return "";
    PA_Unichar* chars = PA_GetUnistring(ustr);
    PA_long32 len = PA_GetUnistringLength(ustr);
    if (!chars || len == 0) return "";

    std::string result;
    result.reserve(len);
    for (PA_long32 i = 0; i < len; i++) {
        unsigned int cp = chars[i];
        // Handle surrogate pairs
        if (cp >= 0xD800 && cp <= 0xDBFF && i + 1 < len) {
            unsigned int low = chars[i + 1];
            if (low >= 0xDC00 && low <= 0xDFFF) {
                cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                i++;
            }
        }
        if (cp < 0x80) {
            result += (char)cp;
        } else if (cp < 0x800) {
            result += (char)(0xC0 | (cp >> 6));
            result += (char)(0x80 | (cp & 0x3F));
        } else if (cp < 0x10000) {
            result += (char)(0xE0 | (cp >> 12));
            result += (char)(0x80 | ((cp >> 6) & 0x3F));
            result += (char)(0x80 | (cp & 0x3F));
        } else {
            result += (char)(0xF0 | (cp >> 18));
            result += (char)(0x80 | ((cp >> 12) & 0x3F));
            result += (char)(0x80 | ((cp >> 6) & 0x3F));
            result += (char)(0x80 | (cp & 0x3F));
        }
    }
    return result;
}

// Wrapper that runs html2pdf_convert on the main thread via PA_RunInMainProcess
typedef struct {
    const char* htmlPath;
    const char* pdfPath;
    int result;
} HTML2PDFContext;

static void html2pdf_main_thread(void* context) {
    HTML2PDFContext* ctx = (HTML2PDFContext*)context;
    ctx->result = html2pdf_convert(ctx->htmlPath, ctx->pdfPath);
}

void PluginMain(PA_long32 selector, PA_PluginParameters params) {
    switch (selector) {
        case 1:
            do_HTML2PDF(params);
            break;
    }
}

static void do_HTML2PDF(PA_PluginParameters params) {
    PA_Unistring* htmlPathParam = PA_GetStringParameter(params, 1);
    PA_Unistring* pdfPathParam = PA_GetStringParameter(params, 2);

    std::string htmlPath = pa_unistring_to_utf8(htmlPathParam);
    std::string pdfPath = pa_unistring_to_utf8(pdfPathParam);

    HTML2PDFContext ctx;
    ctx.htmlPath = htmlPath.c_str();
    ctx.pdfPath = pdfPath.c_str();
    ctx.result = -1;

    PA_RunInMainProcess(html2pdf_main_thread, &ctx);

    PA_ReturnLong(params, ctx.result);
}
