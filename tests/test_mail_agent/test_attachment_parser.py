"""
Tests for the attachment parser.
"""

import base64
import pytest
from pathlib import Path

from mail_agent.tools.attachment_parser import (
    AttachmentParser,
    CorruptedFileError,
    ParsedContent,
    UnsupportedFormatError,
)


class TestAttachmentParser:
    """Tests for AttachmentParser class."""

    def test_init(self):
        """Test parser initialization."""
        parser = AttachmentParser()
        assert parser is not None

    def test_parse_excel_valid(self, sample_excel_base64: str):
        """Test parsing valid Excel file."""
        parser = AttachmentParser()

        result = parser.parse(
            filename="test.xlsx",
            content_base64=sample_excel_base64,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        assert isinstance(result, ParsedContent)
        assert result.content_type == "excel"
        assert result.filename == "test.xlsx"
        assert result.row_count == 10
        assert len(result.headers) > 0
        assert "Recipe Name" in result.headers
        assert len(result.rows) == 10

    def test_parse_csv_valid(self, sample_csv_base64: str):
        """Test parsing valid CSV file."""
        parser = AttachmentParser()

        result = parser.parse(
            filename="test.csv",
            content_base64=sample_csv_base64,
            content_type="text/csv",
        )

        assert isinstance(result, ParsedContent)
        assert result.content_type == "csv"
        assert result.filename == "test.csv"
        assert result.row_count == 10
        assert len(result.headers) > 0
        assert len(result.rows) == 10
        assert result.raw_text is not None

    def test_parse_csv_headerless_single_column(self):
        """Test parsing a headerless single-column CSV."""
        parser = AttachmentParser()
        content = "cat\ndog\nmouse\n"
        result = parser.parse_csv_text(filename="animals.csv", text_content=content)

        assert result.headers == ["Column_0"]
        assert result.row_count == 3
        assert result.rows[0]["Column_0"] == "cat"

    def test_parse_csv_single_column_header_detection(self):
        """Test parsing single-column CSV with an obvious header."""
        parser = AttachmentParser()
        content = "animal\ncat\ndog\n"
        result = parser.parse_csv_text(filename="animals.csv", text_content=content)

        assert result.headers == ["animal"]
        assert result.row_count == 2
        assert result.rows[0]["animal"] == "cat"

    def test_parse_csv_single_column_header_detection_does_not_split_letters(self):
        """Test delimiter sniff doesn't incorrectly split on letters like 'i'."""
        parser = AttachmentParser()
        content = "animal_name\nlion\ntiger\n"
        result = parser.parse_csv_text(filename="animals.csv", text_content=content)

        assert result.headers == ["animal_name"]
        assert result.row_count == 2
        assert result.rows[0]["animal_name"] == "lion"

    def test_parse_excel_by_extension(self, sample_excel_base64: str):
        """Test parsing by file extension (not content-type)."""
        parser = AttachmentParser()

        # Even with generic content-type, should parse by extension
        result = parser.parse(
            filename="data.xlsx",
            content_base64=sample_excel_base64,
            content_type="application/octet-stream",
        )

        assert result.content_type == "excel"
        assert result.row_count == 10

    def test_parse_csv_by_extension(self, sample_csv_base64: str):
        """Test parsing CSV by file extension."""
        parser = AttachmentParser()

        result = parser.parse(
            filename="data.csv",
            content_base64=sample_csv_base64,
            content_type="application/octet-stream",
        )

        assert result.content_type == "csv"
        assert result.row_count == 10

    def test_parse_unsupported_format(self):
        """Test parsing unsupported file format."""
        parser = AttachmentParser()

        with pytest.raises(UnsupportedFormatError) as exc_info:
            parser.parse(
                filename="document.pdf",
                content_base64=base64.b64encode(b"PDF content").decode(),
                content_type="application/pdf",
            )

        assert "pdf" in str(exc_info.value).lower()
        assert "supported" in str(exc_info.value).lower()

    def test_parse_corrupted_excel(self):
        """Test parsing corrupted Excel file."""
        parser = AttachmentParser()

        # Invalid content for Excel
        invalid_content = base64.b64encode(b"not an excel file").decode()

        with pytest.raises(CorruptedFileError):
            parser.parse(
                filename="test.xlsx",
                content_base64=invalid_content,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    def test_parse_invalid_base64(self):
        """Test parsing with invalid base64 content."""
        parser = AttachmentParser()

        with pytest.raises(CorruptedFileError):
            parser.parse(
                filename="test.xlsx",
                content_base64="not valid base64!!!",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    def test_parsed_content_to_json(self, sample_excel_base64: str):
        """Test converting parsed content to JSON."""
        parser = AttachmentParser()

        result = parser.parse(
            filename="test.xlsx",
            content_base64=sample_excel_base64,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        json_output = result.to_json()

        assert isinstance(json_output, str)
        assert "filename" in json_output
        assert "test.xlsx" in json_output
        assert "row_count" in json_output
        assert "10" in json_output

    def test_parsed_content_to_text(self, sample_excel_base64: str):
        """Test converting parsed content to text."""
        parser = AttachmentParser()

        result = parser.parse(
            filename="test.xlsx",
            content_base64=sample_excel_base64,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        text_output = result.to_text()

        assert isinstance(text_output, str)
        assert "test.xlsx" in text_output
        assert "Rows: 10" in text_output

    def test_parse_invalid_excel_insufficient_rows(self, sample_invalid_path: Path):
        """Test parsing Excel with fewer rows (should still parse, validation is separate)."""
        parser = AttachmentParser()

        with open(sample_invalid_path, "rb") as f:
            content_base64 = base64.b64encode(f.read()).decode()

        result = parser.parse(
            filename="invalid.xlsx",
            content_base64=content_base64,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # Parser should still parse the file
        assert result.row_count == 5  # Only 5 rows in invalid file
        assert len(result.rows) == 5


class TestParsedContent:
    """Tests for ParsedContent dataclass."""

    def test_to_json_structure(self):
        """Test JSON output structure."""
        content = ParsedContent(
            content_type="excel",
            filename="test.xlsx",
            headers=["A", "B", "C"],
            rows=[{"A": 1, "B": 2, "C": 3}],
            row_count=1,
            raw_text="raw",
        )

        import json
        json_data = json.loads(content.to_json())

        assert json_data["filename"] == "test.xlsx"
        assert json_data["type"] == "excel"
        assert json_data["headers"] == ["A", "B", "C"]
        assert json_data["row_count"] == 1
        assert len(json_data["data"]) == 1
        assert json_data["raw_text"] == "raw"

    def test_to_text_structure(self):
        """Test text output structure."""
        content = ParsedContent(
            content_type="csv",
            filename="test.csv",
            headers=["Name", "Value"],
            rows=[{"Name": "test", "Value": "123"}],
            row_count=1,
        )

        text = content.to_text()

        assert "File: test.csv" in text
        assert "Type: csv" in text
        assert "Rows: 1" in text
        assert "Columns: Name, Value" in text
