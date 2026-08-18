#include "html2pdf_platform.h"

#ifdef _WIN32

#include <windows.h>
#include <string>
#include <fstream>

// WebView2 headers
#include "WebView2.h"
#include "WebView2EnvironmentOptions.h"
#include <wrl.h>
#include <shlwapi.h>

#pragma comment(lib, "shlwapi.lib")

using namespace Microsoft::WRL;

static std::wstring utf8_to_wide(const char* str) {
    if (!str || !*str) return L"";
    int len = MultiByteToWideChar(CP_UTF8, 0, str, -1, nullptr, 0);
    std::wstring result(len - 1, 0);
    MultiByteToWideChar(CP_UTF8, 0, str, -1, &result[0], len);
    return result;
}

int html2pdf_convert(const char* htmlPath, const char* pdfPath) {
    std::wstring wHtmlPath = utf8_to_wide(htmlPath);
    std::wstring wPdfPath = utf8_to_wide(pdfPath);

    // Check input file exists
    if (GetFileAttributesW(wHtmlPath.c_str()) == INVALID_FILE_ATTRIBUTES) {
        return 1;
    }

    HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(hr) && hr != S_FALSE && hr != RPC_E_CHANGED_MODE) {
        return 2;
    }

    int result = -1;
    HANDLE completionEvent = CreateEvent(nullptr, TRUE, FALSE, nullptr);
    if (!completionEvent) {
        return 3;
    }

    ComPtr<ICoreWebView2Environment> env;
    ComPtr<ICoreWebView2Controller> controller;
    ComPtr<ICoreWebView2> webview;

    // Create WebView2 environment
    hr = CreateCoreWebView2EnvironmentWithOptions(
        nullptr, nullptr, nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [&](HRESULT envHr, ICoreWebView2Environment* createdEnv) -> HRESULT {
                if (FAILED(envHr) || !createdEnv) {
                    result = 4;
                    SetEvent(completionEvent);
                    return S_OK;
                }
                env = createdEnv;

                // Create controller (requires HWND - use desktop window)
                createdEnv->CreateCoreWebView2Controller(
                    GetDesktopWindow(),
                    Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                        [&](HRESULT ctrlHr, ICoreWebView2Controller* createdCtrl) -> HRESULT {
                            if (FAILED(ctrlHr) || !createdCtrl) {
                                result = 5;
                                SetEvent(completionEvent);
                                return S_OK;
                            }
                            controller = createdCtrl;
                            controller->get_CoreWebView2(&webview);

                            // Navigate to html file
                            std::wstring fileUrl = L"file:///" + wHtmlPath;
                            // Replace backslashes
                            for (auto& c : fileUrl) { if (c == L'\\') c = L'/'; }

                            webview->add_NavigationCompleted(
                                Callback<ICoreWebView2NavigationCompletedEventHandler>(
                                    [&](ICoreWebView2* sender, ICoreWebView2NavigationCompletedEventArgs* args) -> HRESULT {
                                        BOOL success = FALSE;
                                        args->get_IsSuccess(&success);
                                        if (!success) {
                                            result = 6;
                                            SetEvent(completionEvent);
                                            return S_OK;
                                        }

                                        // Try PrintToPdf via ICoreWebView2_7
                                        ComPtr<ICoreWebView2_7> webview7;
                                        hr = webview->QueryInterface(IID_PPV_ARGS(&webview7));
                                        if (SUCCEEDED(hr) && webview7) {
                                            ComPtr<ICoreWebView2PrintSettings> printSettings;
                                            ComPtr<ICoreWebView2Environment6> env6;
                                            env->QueryInterface(IID_PPV_ARGS(&env6));
                                            if (env6) {
                                                env6->CreatePrintSettings(&printSettings);
                                            }

                                            webview7->PrintToPdf(
                                                wPdfPath.c_str(),
                                                printSettings.Get(),
                                                Callback<ICoreWebView2PrintToPdfCompletedHandler>(
                                                    [&](HRESULT pdfHr, BOOL isSuccessful) -> HRESULT {
                                                        result = (SUCCEEDED(pdfHr) && isSuccessful) ? 0 : 7;
                                                        SetEvent(completionEvent);
                                                        return S_OK;
                                                    }).Get());
                                        } else {
                                            result = 8;
                                            SetEvent(completionEvent);
                                        }
                                        return S_OK;
                                    }).Get(), nullptr);

                            webview->Navigate(fileUrl.c_str());
                            return S_OK;
                        }).Get());
                return S_OK;
            }).Get());

    if (FAILED(hr)) {
        CloseHandle(completionEvent);
        return 9;
    }

    // Pump messages until completion
    DWORD waitResult;
    MSG msg;
    while ((waitResult = MsgWaitForMultipleObjects(1, &completionEvent, FALSE, 30000, QS_ALLINPUT)) == WAIT_OBJECT_0 + 1) {
        while (PeekMessage(&msg, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg);
            DispatchMessage(&msg);
        }
    }

    if (waitResult == WAIT_TIMEOUT) {
        result = 10;
    }

    CloseHandle(completionEvent);
    CoUninitialize();
    return result;
}

#endif // _WIN32
