//%attributes = {"invisible":true,"preemptive":"capable"}

var $htmlPath : Text
var $pdfPath : Text
var $status : Integer

$htmlPath:=Convert path system to POSIX(Get 4D folder(Current resources folder))+"test.html"
$pdfPath:="/tmp/html2pdf_native_test_output.pdf"

$status:=HTML2PDF($htmlPath; $pdfPath)
ASSERT($status=0; "HTML2PDF should return 0 on success, got: "+String($status))
