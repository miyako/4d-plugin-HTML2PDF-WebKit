cmake_minimum_required(VERSION 3.20)

# Read version from VERSION file
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/../VERSION" PROJECT_VERSION_STRING)
string(STRIP "${PROJECT_VERSION_STRING}" PROJECT_VERSION_STRING)

project(HTML2PDF VERSION ${PROJECT_VERSION_STRING} LANGUAGES C CXX)

# --- Windows: static CRT BEFORE any add_subdirectory ---
if(WIN32)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>" CACHE STRING "" FORCE)
endif()

# --- SDK path ---
set(SDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../4D-Plugin-SDK/4D Plugin API")

# --- WebView2 SDK (Windows only) ---
if(WIN32)
    include(FetchContent)
    FetchContent_Declare(
        webview2
        URL https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/1.0.2903.40
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    )
    FetchContent_MakeAvailable(webview2)
    set(WEBVIEW2_INCLUDE "${webview2_SOURCE_DIR}/build/native/include")
    set(WEBVIEW2_LIB "${webview2_SOURCE_DIR}/build/native/x64/WebView2LoaderStatic.lib")
endif()

# --- Source files ---
set(PLUGIN_SOURCES
    HTML2PDF-4dplugin.cpp
    "${SDK_DIR}/4DPluginAPI.c"
)

if(APPLE)
    list(APPEND PLUGIN_SOURCES html2pdf_mac.mm)
elseif(WIN32)
    list(APPEND PLUGIN_SOURCES html2pdf_win.cpp)
endif()

# --- macOS: Bundle ---
if(APPLE)
    add_library(HTML2PDF MODULE ${PLUGIN_SOURCES})
    set_target_properties(HTML2PDF PROPERTIES
        BUNDLE TRUE
        BUNDLE_EXTENSION "bundle"
        MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"
        MACOSX_BUNDLE_BUNDLE_NAME "HTML2PDF"
        MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}"
        MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION}"
        MACOSX_BUNDLE_EXECUTABLE_NAME "HTML2PDF"
        OUTPUT_NAME "HTML2PDF"
        LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/HTML2PDF-test/Plugins"
    )
    target_link_libraries(HTML2PDF PRIVATE "-framework WebKit" "-framework CoreGraphics" "-framework Foundation")
    set_source_files_properties("${SDK_DIR}/4DPluginAPI.c" PROPERTIES LANGUAGE CXX)
    set_source_files_properties(html2pdf_mac.mm PROPERTIES COMPILE_FLAGS "-fobjc-arc")

# --- Windows: DLL (.4DX) ---
elseif(WIN32)
    add_library(HTML2PDF SHARED ${PLUGIN_SOURCES})
    set_target_properties(HTML2PDF PROPERTIES
        OUTPUT_NAME "HTML2PDF"
        SUFFIX ".4DX"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/HTML2PDF-test/Plugins/HTML2PDF/Contents/Windows64"
    )
    target_link_options(HTML2PDF PRIVATE "/DEF:${SDK_DIR}/4DPluginAPI.def")
    target_link_libraries(HTML2PDF PRIVATE shlwapi)
    target_include_directories(HTML2PDF PRIVATE "${WEBVIEW2_INCLUDE}")
    target_link_libraries(HTML2PDF PRIVATE "${WEBVIEW2_LIB}")

    # Copy resources
    add_custom_command(TARGET HTML2PDF POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_CURRENT_SOURCE_DIR}/HTML2PDF-test/Plugins/HTML2PDF/Contents/Resources"
        COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/manifest.json" "${CMAKE_CURRENT_SOURCE_DIR}/HTML2PDF-test/Plugins/HTML2PDF/Contents/Resources/"
        COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/constants.xlf" "${CMAKE_CURRENT_SOURCE_DIR}/HTML2PDF-test/Plugins/HTML2PDF/Contents/Resources/"
    )
endif()

target_include_directories(HTML2PDF PRIVATE "${SDK_DIR}" "${CMAKE_CURRENT_SOURCE_DIR}")
set_source_files_properties("${SDK_DIR}/4DPluginAPI.c" PROPERTIES LANGUAGE CXX)

# --- macOS: copy resources into bundle ---
if(APPLE)
    set_source_files_properties(
        "${CMAKE_CURRENT_SOURCE_DIR}/manifest.json"
        "${CMAKE_CURRENT_SOURCE_DIR}/constants.xlf"
        PROPERTIES MACOSX_PACKAGE_LOCATION Resources
    )
    target_sources(HTML2PDF PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/manifest.json"
        "${CMAKE_CURRENT_SOURCE_DIR}/constants.xlf"
    )
endif()
