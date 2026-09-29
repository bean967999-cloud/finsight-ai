# Day 5 parsing acceptance samples

`AnnualReportResult.json` is a synthetic **normalized output** fixture, not a MinerU response
and not a parsed company filing. Its numbers and title are demonstration-only.

The fixture verifies that a parser adapter can preserve:

- one-based PDF page numbers and complete page coverage;
- reading order within each page;
- heading levels and the section path of a table;
- a table as a distinct block with an explicit Markdown/HTML format;
- a safe relative path for a referenced image;
- full-document Markdown together with page-level structure.

Additional acceptance samples should cover three cases:

1. Born-digital Chinese financial report excerpt with a heading and a simple table.
2. Scanned PDF page requiring OCR, with page number preserved.
3. Complex or merged-cell table and a blank page, to exercise fallback behavior.

Any further fixtures must be labeled with their source and usage permission. The synthetic
fixture above does **not** prove PDF extraction accuracy.

## Opt-in real disclosure test (Day 5 Step 7)

Source: Hang Seng Bank, "2024 annual press release", published on the Hong Kong Exchanges
and Clearing disclosure site:
https://www.hkexnews.hk/listedco/listconews/sehk/2025/0219/2025021900179.pdf

Hang Seng Bank is only the issuer of this public test file. The platform is not a
Hang Seng Bank-specific project, and this sample is not presented as the user's target
company or as a Chinese annual-report acceptance sample.

The source PDF has 43 pages (SHA-256
`5bdf81375914931d8ea3a76038a6eddf2b181b166e5a3449c22ce17589c83795`).
For a short local test, the externally prepared `HangSeng2024TwoPageExcerpt.pdf` contains
only source PDF pages **1 and 7**, now numbered 1 and 2 in the excerpt. Its SHA-256 is
`626f5a5e948772a92977f958c446e01f63d03a2a82cb7140a79bf1ac17c45130`.
The PDF bytes are kept outside the repository; this is a local testing copy of public
disclosure content, not a claim of unrestricted redistribution rights. Recreate it from
the source with a PDF page extraction tool before running elsewhere.

Run `tests/test_real_pdf_parsing.py` with `FINSIGHT_REAL_PDF_INTEGRATION=1` and
`FINSIGHT_REAL_PDF_PATH` set to the excerpt's absolute path. PostgreSQL and this project's
MinerU service must be running. The test uses a disposable PostgreSQL schema and temporary
object storage, then drops them. It checks two pages, one HTML financial table, the
2024/2023 headings and the value `1,396,927`, plus a deliberately invalid PDF that must
leave the upload job succeeded while the parse job fails.

This is a born-digital English disclosure excerpt. It does not validate Chinese OCR,
scanned reports, merged-cell tables, full 43-page throughput, image binary persistence,
or general extraction accuracy. The document's displayed "7" remains the original
published page number; the excerpt's platform page number is 2.
