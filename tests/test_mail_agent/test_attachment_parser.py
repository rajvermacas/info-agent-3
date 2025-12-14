"""Tests for attachment parser."""

import base64
from pathlib import Path

import pytest

from mail_agent.tools.attachment_parser import (
    AttachmentParser,
    CorruptedFileError,
    UnsupportedFormatError,
    parse_attachment,
)


@pytest.fixture
def test_data_dir():
    """Get test data directory path."""
    return Path(__file__).parent.parent.parent / "test_data"


@pytest.fixture
def sample_valid_xlsx_base64(test_data_dir):
    """Load sample valid Excel file as base64."""
    xlsx_path = test_data_dir / "sample_recipes_valid.xlsx"
    with open(xlsx_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


@pytest.fixture
def sample_csv_base64(test_data_dir):
    """Load sample CSV file as base64."""
    csv_path = test_data_dir / "sample_recipes.csv"
    with open(csv_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


@pytest.fixture
def sample_empty_xlsx_base64(test_data_dir):
    """Load sample empty Excel file as base64."""
    xlsx_path = test_data_dir / "sample_empty.xlsx"
    with open(xlsx_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


@pytest.fixture
def sample_malformed_xlsx_base64(test_data_dir):
    """Load sample malformed Excel file as base64."""
    xlsx_path = test_data_dir / "sample_malformed.xlsx"
    with open(xlsx_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


class TestAttachmentParserExcel:
    """Tests for Excel parsing."""

    def test_parse_valid_xlsx(self, sample_valid_xlsx_base64):
        """Test parsing valid Excel file with 10 recipes."""
        rows = AttachmentParser.parse_excel(sample_valid_xlsx_base64, "recipes.xlsx")

        assert isinstance(rows, list)
        assert len(rows) == 10  # 10 recipes

        # Check first recipe
        first_recipe = rows[0]
        assert "Recipe Name" in first_recipe
        assert "Cuisine" in first_recipe
        assert first_recipe["Recipe Name"] == "Spaghetti Carbonara"
        assert first_recipe["Cuisine"] == "Italian"

    def test_parse_empty_xlsx(self, sample_empty_xlsx_base64):
        """Test parsing empty Excel file (headers only)."""
        rows = AttachmentParser.parse_excel(sample_empty_xlsx_base64, "empty.xlsx")

        assert isinstance(rows, list)
        assert len(rows) == 0  # No data rows

    def test_parse_malformed_xlsx(self, sample_malformed_xlsx_base64):
        """Test parsing malformed Excel file."""
        # Should not raise - parses best effort
        rows = AttachmentParser.parse_excel(sample_malformed_xlsx_base64, "malformed.xlsx")
        assert isinstance(rows, list)

    def test_parse_xlsx_invalid_base64(self):
        """Test parsing Excel with invalid base64."""
        with pytest.raises(CorruptedFileError, match="Invalid base64"):
            AttachmentParser.parse_excel("not-valid-base64!!!", "test.xlsx")

    def test_parse_xlsx_empty_content(self):
        """Test parsing Excel with empty content."""
        with pytest.raises(ValueError, match="content_base64 is required"):
            AttachmentParser.parse_excel("", "test.xlsx")

    def test_parse_xlsx_corrupted_data(self):
        """Test parsing Excel with corrupted file data."""
        corrupted_base64 = base64.b64encode(b"not an excel file").decode("utf-8")

        with pytest.raises(CorruptedFileError):
            AttachmentParser.parse_excel(corrupted_base64, "test.xlsx")


class TestAttachmentParserCSV:
    """Tests for CSV parsing."""

    def test_parse_valid_csv(self, sample_csv_base64):
        """Test parsing valid CSV file with 10 recipes."""
        rows = AttachmentParser.parse_csv(sample_csv_base64, "recipes.csv")

        assert isinstance(rows, list)
        assert len(rows) == 10  # 10 recipes

        # Check first recipe
        first_recipe = rows[0]
        assert "Recipe Name" in first_recipe
        assert "Cuisine" in first_recipe
        assert first_recipe["Recipe Name"] == "Spaghetti Carbonara"
        assert first_recipe["Cuisine"] == "Italian"

    def test_parse_csv_invalid_base64(self):
        """Test parsing CSV with invalid base64."""
        with pytest.raises(CorruptedFileError, match="Invalid base64"):
            AttachmentParser.parse_csv("not-valid-base64!!!", "test.csv")

    def test_parse_csv_empty_content(self):
        """Test parsing CSV with empty content."""
        with pytest.raises(ValueError, match="content_base64 is required"):
            AttachmentParser.parse_csv("", "test.csv")

    def test_parse_csv_utf8_encoding(self):
        """Test parsing CSV with UTF-8 encoding."""
        csv_content = "Name,Value\nTest,123\n"
        csv_base64 = base64.b64encode(csv_content.encode("utf-8")).decode("utf-8")

        rows = AttachmentParser.parse_csv(csv_base64, "test.csv")
        assert len(rows) == 1
        assert rows[0]["Name"] == "Test"


class TestAttachmentParserGeneric:
    """Tests for generic parse method."""

    def test_is_supported_xlsx(self):
        """Test xlsx files are supported."""
        assert AttachmentParser.is_supported("file.xlsx")
        assert AttachmentParser.is_supported("FILE.XLSX")
        assert AttachmentParser.is_supported("path/to/file.xlsx")

    def test_is_supported_csv(self):
        """Test csv files are supported."""
        assert AttachmentParser.is_supported("file.csv")
        assert AttachmentParser.is_supported("FILE.CSV")
        assert AttachmentParser.is_supported("path/to/file.csv")

    def test_is_not_supported(self):
        """Test unsupported file formats."""
        assert not AttachmentParser.is_supported("file.txt")
        assert not AttachmentParser.is_supported("file.pdf")
        assert not AttachmentParser.is_supported("file.xls")  # Legacy Excel
        assert not AttachmentParser.is_supported("")

    def test_parse_xlsx_via_generic(self, sample_valid_xlsx_base64):
        """Test parsing xlsx via generic parse method."""
        rows = AttachmentParser.parse(sample_valid_xlsx_base64, "recipes.xlsx")
        assert len(rows) == 10

    def test_parse_csv_via_generic(self, sample_csv_base64):
        """Test parsing csv via generic parse method."""
        rows = AttachmentParser.parse(sample_csv_base64, "recipes.csv")
        assert len(rows) == 10

    def test_parse_unsupported_format(self):
        """Test parsing unsupported format raises error."""
        with pytest.raises(UnsupportedFormatError, match="Unsupported file format"):
            AttachmentParser.parse("dGVzdA==", "file.txt")

    def test_parse_no_filename(self):
        """Test parsing without filename raises error."""
        with pytest.raises(ValueError, match="filename is required"):
            AttachmentParser.parse("dGVzdA==", "")


class TestParseAttachmentFunction:
    """Tests for parse_attachment convenience function."""

    def test_parse_attachment_xlsx(self, sample_valid_xlsx_base64):
        """Test parsing attachment dict with xlsx."""
        attachment = {
            "filename": "recipes.xlsx",
            "content_base64": sample_valid_xlsx_base64,
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }

        rows = parse_attachment(attachment)
        assert len(rows) == 10

    def test_parse_attachment_csv(self, sample_csv_base64):
        """Test parsing attachment dict with csv."""
        attachment = {
            "filename": "recipes.csv",
            "content_base64": sample_csv_base64,
            "content_type": "text/csv",
        }

        rows = parse_attachment(attachment)
        assert len(rows) == 10

    def test_parse_attachment_missing_content(self):
        """Test parsing attachment without content_base64."""
        attachment = {"filename": "test.xlsx"}

        with pytest.raises(ValueError, match="content_base64"):
            parse_attachment(attachment)

    def test_parse_attachment_missing_filename(self, sample_valid_xlsx_base64):
        """Test parsing attachment without filename."""
        attachment = {"content_base64": sample_valid_xlsx_base64}

        with pytest.raises(ValueError, match="filename"):
            parse_attachment(attachment)

    def test_parse_attachment_none(self):
        """Test parsing None attachment."""
        with pytest.raises(ValueError, match="attachment is required"):
            parse_attachment(None)
