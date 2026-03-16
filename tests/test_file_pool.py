"""
Tests for head/file_pool.py - FilePool and related utilities.
"""

import time
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from head.file_pool import (
    FilePool,
    FileEntry,
    _sanitize_filename,
    _guess_mime_type,
)


# ─── Sanitize Filename Tests ───


class TestSanitizeFilename:
    def test_normal_filename(self):
        assert _sanitize_filename("report.pdf") == "report.pdf"

    def test_spaces_replaced_with_hyphens(self):
        assert _sanitize_filename("my report.pdf") == "my-report.pdf"

    def test_path_separators_removed(self):
        assert _sanitize_filename("../../etc/passwd") == "etcpasswd"

    def test_backslash_removed(self):
        result = _sanitize_filename("C:\\Users\\file.txt")
        assert "\\" not in result
        assert "/" not in result

    def test_null_bytes_removed(self):
        assert _sanitize_filename("file\0name.txt") == "filename.txt"

    def test_leading_dots_removed(self):
        assert _sanitize_filename("..hidden.txt") == "hidden.txt"

    def test_shell_metacharacters_removed(self):
        assert _sanitize_filename("file;rm -rf;.txt") == "filerm-rf.txt"

    def test_all_metacharacters_stripped(self):
        result = _sanitize_filename("a&b|c$d`e(f)g{h}i[j]k!l#m~n.txt")
        assert ";" not in result
        assert "&" not in result
        assert "|" not in result
        assert "$" not in result
        assert "`" not in result
        assert "(" not in result
        assert ")" not in result

    def test_empty_after_sanitization(self):
        assert _sanitize_filename("../../../") == "unnamed"

    def test_long_filename_truncated(self):
        long_name = "a" * 250 + ".pdf"
        result = _sanitize_filename(long_name)
        assert len(result) <= 200
        assert result.endswith(".pdf")

    def test_long_filename_preserves_extension(self):
        long_name = "a" * 250 + ".markdown"
        result = _sanitize_filename(long_name)
        assert result.endswith(".markdown")
        assert len(result) <= 200

    def test_consecutive_hyphens_collapsed(self):
        assert _sanitize_filename("a - - b.txt") == "a-b.txt"


# ─── Guess MIME Type Tests ───


class TestGuessMimeType:
    def test_pdf(self):
        assert _guess_mime_type("report.pdf") == "application/pdf"

    def test_png(self):
        assert _guess_mime_type("image.png") == "image/png"

    def test_jpg(self):
        assert _guess_mime_type("photo.jpg") == "image/jpeg"

    def test_txt(self):
        assert _guess_mime_type("notes.txt") == "text/plain"

    def test_markdown(self):
        assert _guess_mime_type("readme.md") == "text/markdown"

    def test_mp4(self):
        assert _guess_mime_type("video.mp4") == "video/mp4"

    def test_mp3(self):
        assert _guess_mime_type("song.mp3") == "audio/mpeg"

    def test_unknown_extension(self):
        assert _guess_mime_type("data.xyz") == "application/octet-stream"

    def test_no_extension(self):
        assert _guess_mime_type("README") == "application/octet-stream"

    def test_case_insensitive(self):
        assert _guess_mime_type("PHOTO.JPG") == "image/jpeg"


# ─── FilePool: is_allowed_type Tests ───


class TestIsAllowedType:
    @pytest.fixture
    def pool(self, tmp_path):
        return FilePool(pool_dir=tmp_path / "pool")

    def test_pdf_allowed(self, pool):
        assert pool.is_allowed_type("doc.pdf", "application/pdf") is True

    def test_text_plain_allowed(self, pool):
        assert pool.is_allowed_type("notes.txt", "text/plain") is True

    def test_markdown_allowed(self, pool):
        assert pool.is_allowed_type("readme.md", "text/markdown") is True

    def test_image_wildcard_png(self, pool):
        assert pool.is_allowed_type("pic.png", "image/png") is True

    def test_image_wildcard_jpeg(self, pool):
        assert pool.is_allowed_type("pic.jpg", "image/jpeg") is True

    def test_video_wildcard(self, pool):
        assert pool.is_allowed_type("vid.mp4", "video/mp4") is True

    def test_audio_wildcard(self, pool):
        assert pool.is_allowed_type("song.mp3", "audio/mpeg") is True

    def test_code_file_rejected(self, pool):
        assert pool.is_allowed_type("main.py", "text/x-python") is False

    def test_binary_rejected(self, pool):
        assert pool.is_allowed_type("data.bin", "application/octet-stream") is False

    def test_none_content_type_falls_back_to_extension(self, pool):
        # No content_type given, should guess from extension
        assert pool.is_allowed_type("doc.pdf", None) is True

    def test_none_content_type_unknown_ext_rejected(self, pool):
        assert pool.is_allowed_type("code.py", None) is False

    def test_custom_allowed_types(self, tmp_path):
        pool = FilePool(pool_dir=tmp_path / "pool", allowed_types=["text/plain"])
        assert pool.is_allowed_type("notes.txt", "text/plain") is True
        assert pool.is_allowed_type("pic.png", "image/png") is False


# ─── FilePool: add_file and get_file Tests ───


class TestAddAndGetFile:
    @pytest.fixture
    def pool(self, tmp_path):
        return FilePool(pool_dir=tmp_path / "pool")

    def test_add_file_returns_entry(self, pool, tmp_path):
        # Create a test file
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"PDF content")

        entry = pool.add_file(test_file, "test.pdf", "application/pdf")
        assert entry.original_name == "test.pdf"
        assert entry.size == len(b"PDF content")
        assert entry.mime_type == "application/pdf"
        assert entry.file_id  # not empty

    def test_get_file_returns_entry(self, pool, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")

        entry = pool.add_file(test_file, "test.txt", "text/plain")
        retrieved = pool.get_file(entry.file_id)
        assert retrieved is not None
        assert retrieved.file_id == entry.file_id
        assert retrieved.original_name == "test.txt"

    def test_get_file_not_found(self, pool):
        assert pool.get_file("nonexistent") is None

    def test_file_id_uniqueness(self, pool, tmp_path):
        f1 = tmp_path / "a.txt"
        f1.write_text("a")
        f2 = tmp_path / "b.txt"
        f2.write_text("b")

        e1 = pool.add_file(f1, "a.txt", "text/plain")
        e2 = pool.add_file(f2, "b.txt", "text/plain")
        assert e1.file_id != e2.file_id

    def test_file_id_includes_session_prefix(self, pool, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"data")

        entry = pool.add_file(test_file, "test.pdf", session_prefix="abc12345")
        assert entry.file_id.startswith("abc12345_")

    def test_file_id_no_prefix_when_empty(self, pool, tmp_path):
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"data")

        entry = pool.add_file(test_file, "test.pdf", session_prefix="")
        # UUID-only, no leading underscore
        assert not entry.file_id.startswith("_")
        assert len(entry.file_id) == 8  # uuid hex[:8]

    def test_add_nonexistent_file_raises(self, pool, tmp_path):
        with pytest.raises(FileNotFoundError):
            pool.add_file(tmp_path / "nope.txt", "nope.txt")

    def test_file_exceeds_max_size_raises(self, tmp_path):
        pool = FilePool(max_size=10, pool_dir=tmp_path / "pool")
        big_file = tmp_path / "big.txt"
        big_file.write_bytes(b"x" * 20)

        with pytest.raises(ValueError, match="exceeds pool max size"):
            pool.add_file(big_file, "big.txt")


# ─── FilePool: total_size and file_count Tests ───


class TestPoolMetrics:
    @pytest.fixture
    def pool(self, tmp_path):
        return FilePool(pool_dir=tmp_path / "pool")

    def test_empty_pool(self, pool):
        assert pool.total_size == 0
        assert pool.file_count == 0

    def test_after_adding_files(self, pool, tmp_path):
        f1 = tmp_path / "a.txt"
        f1.write_bytes(b"12345")  # 5 bytes
        f2 = tmp_path / "b.txt"
        f2.write_bytes(b"123456789")  # 9 bytes

        pool.add_file(f1, "a.txt")
        pool.add_file(f2, "b.txt")

        assert pool.total_size == 14
        assert pool.file_count == 2


# ─── FilePool: LRU Eviction Tests ───


class TestEviction:
    def test_evicts_oldest_when_over_limit(self, tmp_path):
        pool = FilePool(max_size=20, pool_dir=tmp_path / "pool")

        # Add file1 (10 bytes)
        f1 = tmp_path / "first.txt"
        f1.write_bytes(b"a" * 10)
        e1 = pool.add_file(f1, "first.txt")
        old_id = e1.file_id

        # Ensure different timestamps
        time.sleep(0.01)

        # Add file2 (10 bytes) - still within limit (20)
        f2 = tmp_path / "second.txt"
        f2.write_bytes(b"b" * 10)
        pool.add_file(f2, "second.txt")
        assert pool.file_count == 2
        assert pool.total_size == 20

        time.sleep(0.01)

        # Add file3 (5 bytes) - over limit, should evict oldest (first.txt)
        f3 = tmp_path / "third.txt"
        f3.write_bytes(b"c" * 5)
        pool.add_file(f3, "third.txt")

        # first.txt should have been evicted
        assert pool.get_file(old_id) is None
        assert pool.file_count == 2
        assert pool.total_size == 15

    def test_evicts_multiple_if_needed(self, tmp_path):
        pool = FilePool(max_size=30, pool_dir=tmp_path / "pool")

        files_and_entries = []
        for i in range(3):
            f = tmp_path / f"file{i}.txt"
            f.write_bytes(b"x" * 10)
            e = pool.add_file(f, f"file{i}.txt")
            files_and_entries.append(e)
            time.sleep(0.01)

        assert pool.total_size == 30

        # Add a 15-byte file - must evict 2 oldest to fit
        big = tmp_path / "big.txt"
        big.write_bytes(b"y" * 15)
        pool.add_file(big, "big.txt")

        # Two oldest should be gone
        assert pool.get_file(files_and_entries[0].file_id) is None
        assert pool.get_file(files_and_entries[1].file_id) is None
        # Newest original + big should remain
        assert pool.get_file(files_and_entries[2].file_id) is not None
        assert pool.total_size == 25

    def test_pool_directory_created(self, tmp_path):
        pool_dir = tmp_path / "sub" / "dir" / "pool"
        assert not pool_dir.exists()
        FilePool(pool_dir=pool_dir)
        assert pool_dir.exists()


# ─── FilePool: download_discord_attachment Tests ───


class TestDownloadDiscordAttachment:
    @pytest.fixture
    def pool(self, tmp_path):
        return FilePool(pool_dir=tmp_path / "pool")

    @pytest.fixture
    def mock_attachment(self, tmp_path):
        """Create a mock Discord attachment."""
        att = MagicMock()
        att.filename = "report.pdf"
        att.size = 1024
        att.content_type = "application/pdf"

        # Mock save() to write actual bytes
        async def mock_save(path):
            Path(path).write_bytes(b"x" * 1024)

        att.save = mock_save
        return att

    @pytest.mark.asyncio
    async def test_download_success(self, pool, mock_attachment):
        entry = await pool.download_discord_attachment(mock_attachment, session_prefix="sess1234")
        assert entry.original_name == "report.pdf"
        assert entry.size == 1024
        assert entry.mime_type == "application/pdf"
        assert entry.file_id.startswith("sess1234_")
        assert entry.local_path.exists()

    @pytest.mark.asyncio
    async def test_download_no_content_type(self, pool, tmp_path):
        att = MagicMock()
        att.filename = "image.png"
        att.size = 500
        att.content_type = None

        async def mock_save(path):
            Path(path).write_bytes(b"x" * 500)

        att.save = mock_save

        entry = await pool.download_discord_attachment(att)
        assert entry.mime_type == "image/png"  # guessed from extension

    @pytest.mark.asyncio
    async def test_download_file_too_large(self, tmp_path):
        pool = FilePool(max_size=100, pool_dir=tmp_path / "pool")
        att = MagicMock()
        att.filename = "huge.pdf"
        att.size = 200
        att.content_type = "application/pdf"

        with pytest.raises(ValueError, match="exceeds pool max size"):
            await pool.download_discord_attachment(att)

    @pytest.mark.asyncio
    async def test_download_with_unsafe_filename(self, pool):
        att = MagicMock()
        att.filename = "../../etc/passwd"
        att.size = 10
        att.content_type = "text/plain"

        async def mock_save(path):
            Path(path).write_bytes(b"x" * 10)

        att.save = mock_save

        entry = await pool.download_discord_attachment(att)
        # filename should be sanitized
        assert "/" not in entry.local_path.name
        assert ".." not in entry.local_path.name

    @pytest.mark.asyncio
    async def test_download_triggers_eviction(self, tmp_path):
        pool = FilePool(max_size=20, pool_dir=tmp_path / "pool")

        # First: add a file via add_file
        f = tmp_path / "old.txt"
        f.write_bytes(b"a" * 15)
        old_entry = pool.add_file(f, "old.txt")

        time.sleep(0.01)

        # Download new file that pushes over limit
        att = MagicMock()
        att.filename = "new.pdf"
        att.size = 10
        att.content_type = "application/pdf"

        async def mock_save(path):
            Path(path).write_bytes(b"x" * 10)

        att.save = mock_save

        new_entry = await pool.download_discord_attachment(att)
        # old file should be evicted
        assert pool.get_file(old_entry.file_id) is None
        assert pool.get_file(new_entry.file_id) is not None
