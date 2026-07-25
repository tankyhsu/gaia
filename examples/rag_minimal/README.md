# Minimal cited RAG example

This example owns only a small Golden Dataset. The executable acceptance test uses Gaia's public
Loader, Parser, Chunker, Retriever and Citation contracts.

The built-in reference parser accepts UTF-8 text and Markdown. Applications should replace
`DocumentParser` for PDF, Office, OCR or industry formats; Gaia does not hard-code Docling or a
vendor parser.
