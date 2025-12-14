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

    def to_json(self) -> str:
        """Convert parsed content to JSON string."""
        return json.dumps(
            {
                "filename": self.filename,
                "type": self.content_type,
                "headers": self.headers,
                "row_count": self.row_count,
                "data": self.rows,
            },
            indent=2,
            default=str,  # Handle datetime and other non-serializable types
        )

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

            # Try UTF-8 first, fallback to latin-1
            try:
                text_content = decoded_bytes.decode("utf-8")
            except UnicodeDecodeError:
                logger.debug("UTF-8 decode failed, trying latin-1")
                text_content = decoded_bytes.decode("latin-1")

            # Use csv.DictReader to parse
            string_io = io.StringIO(text_content)

            # Detect delimiter
            sample = text_content[:1024]
            try:
                dialect = csv.Sniffer().sniff(sample)
                delimiter = dialect.delimiter
            except csv.Error:
                # Default to comma if sniffing fails
                delimiter = ","
            logger.debug(f"CSV delimiter detected: '{delimiter}'")

            string_io.seek(0)
            reader = csv.DictReader(string_io, delimiter=delimiter)

            if reader.fieldnames is None:
                logger.warning(f"CSV file has no headers: {filename}")
                return ParsedContent(
                    content_type="csv",
                    filename=filename,
                    headers=[],
                    rows=[],
                    row_count=0,
                )

            headers = list(reader.fieldnames)
            data_rows = [row for row in reader]

            result = ParsedContent(
                content_type="csv",
                filename=filename,
                headers=headers,
                rows=data_rows,
                row_count=len(data_rows),
            )

            logger.info(
                f"CSV parsed successfully: {filename}, "
                f"headers={headers}, rows={len(data_rows)}"
            )
            return result

        except CorruptedFileError:
            raise
        except Exception as e:
            error_msg = f"Failed to parse CSV file '{filename}': {e}"
            logger.error(error_msg)
            raise CorruptedFileError(error_msg) from e

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
