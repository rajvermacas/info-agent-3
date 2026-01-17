"""
Attachment Parser - Extract content from Excel and CSV attachments.

Converts attachments to JSON/text format for LLM validation.
"""

import base64
import csv
import io
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from openpyxl import load_workbook
from openpyxl.workbook import Workbook


logger = logging.getLogger(__name__)


class AttachmentParseError(Exception):
    """Base exception for attachment parsing errors."""

    pass


class UnsupportedFormatError(AttachmentParseError):
    """Attachment format is not supported."""

    pass


class CorruptedFileError(AttachmentParseError):
    """Attachment file is corrupted or invalid."""

    pass


@dataclass
class ParsedContent:
    """Result of parsing an attachment."""

    content_type: str  # "excel" or "csv"
    filename: str
    headers: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    raw_text: Optional[str] = None

    def to_json(self) -> str:
        """Convert parsed content to JSON string."""
        payload: dict[str, Any] = {
            "filename": self.filename,
            "type": self.content_type,
            "headers": self.headers,
            "row_count": self.row_count,
            "data": self.rows,
        }
        if self.raw_text is not None:
            payload["raw_text"] = self.raw_text
        return json.dumps(payload, indent=2, default=str)

    def to_text(self) -> str:
        """Convert parsed content to human-readable text."""
        lines = [
            f"File: {self.filename}",
            f"Type: {self.content_type}",
            f"Rows: {self.row_count}",
            f"Columns: {', '.join(self.headers)}",
            "",
            "Data:",
        ]
        for i, row in enumerate(self.rows, 1):
            row_str = ", ".join(f"{k}: {v}" for k, v in row.items())
            lines.append(f"  {i}. {row_str}")
        return "\n".join(lines)


class AttachmentParser:
    """
    Parser for extracting content from email attachments.

    Supports Excel (.xlsx) and CSV files only.
    """

    SUPPORTED_EXCEL_TYPES = [
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ]
    SUPPORTED_CSV_TYPES = [
        "text/csv",
        "application/csv",
        "text/plain",  # Sometimes CSV is sent as text/plain
    ]

    def __init__(self) -> None:
        """Initialize attachment parser."""
        logger.debug("AttachmentParser initialized")

    def parse(
        self,
        filename: str,
        content_base64: str,
        content_type: str,
    ) -> ParsedContent:
        """
        Parse an attachment and extract its content.

        Args:
            filename: Original filename of the attachment.
            content_base64: Base64-encoded file content.
            content_type: MIME type of the attachment.

        Returns:
            ParsedContent with extracted data.

        Raises:
            UnsupportedFormatError: If file format is not supported.
            CorruptedFileError: If file cannot be parsed.
        """
        logger.info(f"Parsing attachment: filename={filename}, type={content_type}")

        # Determine file type from extension and content_type
        file_ext = filename.lower().split(".")[-1] if "." in filename else ""

        if file_ext == "xlsx" or content_type in self.SUPPORTED_EXCEL_TYPES:
            return self._parse_excel(filename, content_base64)
        elif file_ext == "csv" or content_type in self.SUPPORTED_CSV_TYPES:
            return self._parse_csv(filename, content_base64)
        else:
            error_msg = (
                f"Unsupported attachment format: filename={filename}, "
                f"type={content_type}. Only .xlsx and .csv are supported."
            )
            logger.error(error_msg)
            raise UnsupportedFormatError(error_msg)

    def _decode_base64(self, content_base64: str) -> bytes:
        """Decode base64 content to bytes."""
        try:
            return base64.b64decode(content_base64)
        except Exception as e:
            error_msg = f"Failed to decode base64 content: {e}"
            logger.error(error_msg)
            raise CorruptedFileError(error_msg) from e

    def _parse_excel(
        self,
        filename: str,
        content_base64: str,
    ) -> ParsedContent:
        """
        Parse Excel (.xlsx) file content.

        Args:
            filename: Original filename.
            content_base64: Base64-encoded Excel file.

        Returns:
            ParsedContent with extracted data.

        Raises:
            CorruptedFileError: If Excel file cannot be parsed.
        """
        logger.debug(f"Parsing Excel file: {filename}")

        try:
            decoded_bytes = self._decode_base64(content_base64)
            bytes_io = io.BytesIO(decoded_bytes)

            # Load workbook with data_only=True to get values instead of formulas
            wb: Workbook = load_workbook(filename=bytes_io, data_only=True)
            ws = wb.active

            if ws is None:
                raise CorruptedFileError("Excel file has no active sheet")

            # Read all rows as tuples
            all_rows = list(ws.iter_rows(values_only=True))

            if not all_rows:
                logger.warning(f"Excel file is empty: {filename}")
                return ParsedContent(
                    content_type="excel",
                    filename=filename,
                    headers=[],
                    rows=[],
                    row_count=0,
                )

            # First row is headers
            raw_headers = all_rows[0]
            # Convert None headers to empty strings and ensure string type
            headers = [str(h) if h is not None else f"Column_{i}" for i, h in enumerate(raw_headers)]

            # Remaining rows are data
            data_rows = []
            for row in all_rows[1:]:
                # Skip completely empty rows
                if not any(cell is not None for cell in row):
                    continue
                row_dict = {
                    headers[i]: cell for i, cell in enumerate(row) if i < len(headers)
                }
                data_rows.append(row_dict)

            result = ParsedContent(
                content_type="excel",
                filename=filename,
                headers=headers,
                rows=data_rows,
                row_count=len(data_rows),
            )

            logger.info(
                f"Excel parsed successfully: {filename}, "
                f"headers={headers}, rows={len(data_rows)}"
            )
            return result

        except CorruptedFileError:
            raise
        except Exception as e:
            error_msg = f"Failed to parse Excel file '{filename}': {e}"
            logger.error(error_msg)
            raise CorruptedFileError(error_msg) from e

    def _parse_csv(
        self,
        filename: str,
        content_base64: str,
    ) -> ParsedContent:
        """
        Parse CSV file content.

        Args:
            filename: Original filename.
            content_base64: Base64-encoded CSV file.

        Returns:
            ParsedContent with extracted data.

        Raises:
            CorruptedFileError: If CSV file cannot be parsed.
        """
        logger.debug(f"Parsing CSV file: {filename}")

        try:
            decoded_bytes = self._decode_base64(content_base64)
            text_content = self._decode_text(decoded_bytes)
            return self.parse_csv_text(filename=filename, text_content=text_content)

        except CorruptedFileError:
            raise
        except Exception as e:
            error_msg = f"Failed to parse CSV file '{filename}': {e}"
            logger.error(error_msg)
            raise CorruptedFileError(error_msg) from e

    def _decode_text(self, decoded_bytes: bytes) -> str:
        try:
            return decoded_bytes.decode("utf-8")
        except UnicodeDecodeError:
            logger.debug("UTF-8 decode failed, trying latin-1")
            return decoded_bytes.decode("latin-1")

    def _sniff_csv_delimiter(self, sample: str) -> str:
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            return ","

    def _sniff_has_header(self, sample: str) -> bool:
        try:
            return csv.Sniffer().has_header(sample)
        except csv.Error:
            return False

    def _truncate_raw_text(self, text: str, max_chars: int = 20000) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "...(truncated)"

    def parse_csv_text(self, filename: str, text_content: str) -> ParsedContent:
        """
        Parse CSV content provided as text (e.g., from an email body).

        Handles headerless CSV by generating generic column names.
        """
        sample = text_content[:4096]
        delimiter = self._sniff_csv_delimiter(sample)
        has_header = self._sniff_has_header(sample)
        logger.debug(f"CSV delimiter detected: '{delimiter}', has_header={has_header}")

        reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
        raw_rows = [r for r in reader if any((c or "").strip() for c in r)]
        if not raw_rows:
            return ParsedContent(
                content_type="csv",
                filename=filename,
                headers=[],
                rows=[],
                row_count=0,
                raw_text=self._truncate_raw_text(text_content),
            )

        max_cols = max(len(r) for r in raw_rows)
        normalized = [r + [""] * (max_cols - len(r)) for r in raw_rows]

        if max_cols == 1 and len(normalized) >= 2:
            first_cell = (normalized[0][0] or "").strip().lower()
            if first_cell in {"animal", "animals", "animal_name", "animal_names", "name", "names"}:
                has_header = True

        if has_header and len(normalized) >= 2:
            headers = [
                (h or "").strip() or f"Column_{i}" for i, h in enumerate(normalized[0])
            ]
            data_rows = normalized[1:]
        else:
            headers = [f"Column_{i}" for i in range(max_cols)]
            data_rows = normalized

        rows = [
            {headers[i]: (cell or "").strip() for i, cell in enumerate(row)}
            for row in data_rows
            if any((cell or "").strip() for cell in row)
        ]

        result = ParsedContent(
            content_type="csv",
            filename=filename,
            headers=headers,
            rows=rows,
            row_count=len(rows),
            raw_text=self._truncate_raw_text(text_content),
        )
        logger.info(
            f"CSV parsed successfully: {filename}, headers={headers}, rows={len(rows)}"
        )
        return result

    def parse_from_attachment_object(
        self,
        attachment: Any,
    ) -> ParsedContent:
        """
        Parse from an Attachment dataclass object.

        Args:
            attachment: Attachment object with filename, content_base64, content_type.

        Returns:
            ParsedContent with extracted data.
        """
        return self.parse(
            filename=attachment.filename,
            content_base64=attachment.content_base64,
            content_type=attachment.content_type,
        )
