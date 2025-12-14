"""Attachment parser for Excel and CSV files."""

import base64
import csv
import io
import logging
from typing import Any

from openpyxl import load_workbook

logger = logging.getLogger(__name__)


class AttachmentParseError(Exception):
    """Base exception for attachment parsing errors."""
    pass


class UnsupportedFormatError(AttachmentParseError):
    """Exception raised when attachment format is not supported."""
    pass


class CorruptedFileError(AttachmentParseError):
    """Exception raised when attachment file is corrupted or cannot be parsed."""
    pass


class AttachmentParser:
    """Parser for email attachments (Excel and CSV)."""

    SUPPORTED_EXTENSIONS = {".xlsx", ".csv"}

    @staticmethod
    def parse_excel(content_base64: str, filename: str) -> list[dict[str, Any]]:
        """Parse Excel (.xlsx) file from base64 content.

        Args:
            content_base64: Base64-encoded Excel file content
            filename: Original filename (for logging)

        Returns:
            list[dict]: List of row dictionaries with column headers as keys

        Raises:
            CorruptedFileError: If Excel file cannot be parsed
            ValueError: If content_base64 is invalid
        """
        if not content_base64 or not content_base64.strip():
            raise ValueError("content_base64 is required")

        logger.debug(f"Parsing Excel file: {filename}")

        try:
            # Decode base64
            file_bytes = base64.b64decode(content_base64)
            file_io = io.BytesIO(file_bytes)

            # Load workbook
            wb = load_workbook(file_io, data_only=True)
            ws = wb.active

            # Extract headers from first row
            headers_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)

            if not headers_row:
                raise CorruptedFileError(f"Excel file has no headers: {filename}")

            headers = [str(h) if h is not None else f"Column_{i}" for i, h in enumerate(headers_row)]

            # Extract data rows
            rows = []
            for row_values in ws.iter_rows(min_row=2, values_only=True):
                # Skip completely empty rows
                if all(v is None or str(v).strip() == "" for v in row_values):
                    continue

                # Create dict mapping headers to values
                row_dict = {}
                for i, value in enumerate(row_values):
                    if i < len(headers):
                        # Convert None to empty string
                        row_dict[headers[i]] = value if value is not None else ""

                rows.append(row_dict)

            logger.info(
                f"Parsed Excel file: {filename}, "
                f"headers={headers}, rows={len(rows)}"
            )

            return rows

        except base64.binascii.Error as e:
            error_msg = f"Invalid base64 content: {str(e)}"
            logger.error(error_msg)
            raise CorruptedFileError(error_msg) from e

        except Exception as e:
            error_msg = f"Failed to parse Excel file {filename}: {str(e)}"
            logger.error(error_msg)
            raise CorruptedFileError(error_msg) from e

    @staticmethod
    def parse_csv(content_base64: str, filename: str) -> list[dict[str, Any]]:
        """Parse CSV file from base64 content.

        Args:
            content_base64: Base64-encoded CSV file content
            filename: Original filename (for logging)

        Returns:
            list[dict]: List of row dictionaries with column headers as keys

        Raises:
            CorruptedFileError: If CSV file cannot be parsed
            ValueError: If content_base64 is invalid
        """
        if not content_base64 or not content_base64.strip():
            raise ValueError("content_base64 is required")

        logger.debug(f"Parsing CSV file: {filename}")

        try:
            # Decode base64
            file_bytes = base64.b64decode(content_base64)

            # Try UTF-8 first, fallback to latin-1
            try:
                text = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                logger.debug("UTF-8 decode failed, trying latin-1")
                text = file_bytes.decode("latin-1")

            # Parse CSV
            csv_reader = csv.DictReader(io.StringIO(text))
            rows = list(csv_reader)

            logger.info(
                f"Parsed CSV file: {filename}, "
                f"headers={csv_reader.fieldnames}, rows={len(rows)}"
            )

            return rows

        except base64.binascii.Error as e:
            error_msg = f"Invalid base64 content: {str(e)}"
            logger.error(error_msg)
            raise CorruptedFileError(error_msg) from e

        except Exception as e:
            error_msg = f"Failed to parse CSV file {filename}: {str(e)}"
            logger.error(error_msg)
            raise CorruptedFileError(error_msg) from e

    @classmethod
    def is_supported(cls, filename: str) -> bool:
        """Check if filename has supported extension.

        Args:
            filename: Attachment filename

        Returns:
            bool: True if extension is supported (.xlsx or .csv)
        """
        if not filename:
            return False

        filename_lower = filename.lower()
        return any(filename_lower.endswith(ext) for ext in cls.SUPPORTED_EXTENSIONS)

    @classmethod
    def parse(cls, content_base64: str, filename: str) -> list[dict[str, Any]]:
        """Parse attachment based on filename extension.

        Args:
            content_base64: Base64-encoded file content
            filename: Original filename (determines parser)

        Returns:
            list[dict]: List of row dictionaries

        Raises:
            UnsupportedFormatError: If file format is not supported
            CorruptedFileError: If file cannot be parsed
            ValueError: If parameters are invalid
        """
        if not filename:
            raise ValueError("filename is required")

        if not cls.is_supported(filename):
            supported = ", ".join(cls.SUPPORTED_EXTENSIONS)
            raise UnsupportedFormatError(
                f"Unsupported file format: {filename}. "
                f"Supported formats: {supported}"
            )

        filename_lower = filename.lower()

        if filename_lower.endswith(".xlsx"):
            return cls.parse_excel(content_base64, filename)
        elif filename_lower.endswith(".csv"):
            return cls.parse_csv(content_base64, filename)
        else:
            # Should never reach here due to is_supported check
            raise UnsupportedFormatError(f"Unknown format: {filename}")


def parse_attachment(attachment: dict) -> list[dict[str, Any]]:
    """Convenience function to parse attachment dict from email.

    Args:
        attachment: Attachment dict with 'content_base64' and 'filename' keys

    Returns:
        list[dict]: Parsed rows

    Raises:
        UnsupportedFormatError: If file format is not supported
        CorruptedFileError: If file cannot be parsed
        ValueError: If attachment dict is invalid
    """
    if not attachment:
        raise ValueError("attachment is required")

    if "content_base64" not in attachment:
        raise ValueError("attachment must have 'content_base64' key")

    if "filename" not in attachment:
        raise ValueError("attachment must have 'filename' key")

    return AttachmentParser.parse(
        attachment["content_base64"],
        attachment["filename"]
    )
