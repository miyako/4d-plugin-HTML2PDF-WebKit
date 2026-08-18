#include "html2pdf_platform.h"

#import <Foundation/Foundation.h>
#import <WebKit/WebKit.h>
#include <dispatch/dispatch.h>

int html2pdf_convert(const char* htmlPath, const char* pdfPath) {
    @autoreleasepool {
        NSString* htmlPathStr = [NSString stringWithUTF8String:htmlPath];
        NSString* pdfPathStr = [NSString stringWithUTF8String:pdfPath];

        NSURL* htmlURL = [NSURL fileURLWithPath:htmlPathStr];
        NSURL* pdfURL = [NSURL fileURLWithPath:pdfPathStr];

        // Verify input file exists
        if (![[NSFileManager defaultManager] fileExistsAtPath:htmlPathStr]) {
            NSLog(@"HTML2PDF: Input file does not exist: %@", htmlPathStr);
            return 1;
        }

        __block int result = -1;
        dispatch_semaphore_t sem = dispatch_semaphore_create(0);

        // WKWebView must be created and used on the main thread
        // PA_RunInMainProcess already ensures we're on the main thread
        WKWebViewConfiguration* config = [[WKWebViewConfiguration alloc] init];
        WKWebView* webView = [[WKWebView alloc] initWithFrame:NSMakeRect(0, 0, 800, 600) configuration:config];

        // Load the HTML file
        NSURLRequest* request = [NSURLRequest requestWithURL:htmlURL];

        // Use a navigation delegate to know when loading finishes
        __block BOOL loadDone = NO;
        __block NSError* loadError = nil;

        // We'll use a helper class for the delegate
        // Since we're in a function, use KVO or polling approach
        [webView loadRequest:request];

        // Poll the run loop until loading is complete
        // WKWebView sets 'loading' property
        NSDate* timeout = [NSDate dateWithTimeIntervalSinceNow:30.0];
        while (webView.isLoading && [[NSDate date] compare:timeout] == NSOrderedAscending) {
            [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        }

        if (webView.isLoading) {
            NSLog(@"HTML2PDF: Timed out loading HTML file");
            return 2;
        }

        // Small delay to let rendering complete
        [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.5]];

        // Generate PDF using createPDFWithConfiguration:completionHandler: (macOS 11+)
        if (@available(macOS 11.0, *)) {
            WKPDFConfiguration* pdfConfig = [[WKPDFConfiguration alloc] init];

            __block BOOL pdfDone = NO;
            [webView createPDFWithConfiguration:pdfConfig completionHandler:^(NSData* pdfData, NSError* error) {
                if (error) {
                    NSLog(@"HTML2PDF: PDF generation failed: %@", error);
                    result = 3;
                } else if (pdfData) {
                    BOOL written = [pdfData writeToURL:pdfURL atomically:YES];
                    if (written) {
                        result = 0;
                    } else {
                        NSLog(@"HTML2PDF: Failed to write PDF to: %@", pdfPathStr);
                        result = 4;
                    }
                } else {
                    result = 5;
                }
                pdfDone = YES;
            }];

            // Poll until PDF generation completes
            NSDate* pdfTimeout = [NSDate dateWithTimeIntervalSinceNow:30.0];
            while (!pdfDone && [[NSDate date] compare:pdfTimeout] == NSOrderedAscending) {
                [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
            }

            if (!pdfDone) {
                NSLog(@"HTML2PDF: Timed out generating PDF");
                return 6;
            }
        } else {
            NSLog(@"HTML2PDF: createPDFWithConfiguration requires macOS 11.0+");
            return 7;
        }

        return result;
    }
}
