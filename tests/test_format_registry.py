import unittest
from backend.app.utils.format_registry import format_registry, FormatCategory
from backend.app.enums import FileTypeEnum

class TestFormatRegistry(unittest.TestCase):
    def test_image_formats(self):
        self.assertTrue(format_registry.is_image("photo.jpg"))
        self.assertTrue(format_registry.is_image("photo.JPEG"))
        self.assertTrue(format_registry.is_image("photo.png"))
        self.assertTrue(format_registry.is_image("photo.avif"))
        self.assertTrue(format_registry.is_image("photo.heic"))
        self.assertTrue(format_registry.is_image("photo.heif"))
        self.assertTrue(format_registry.is_image("photo.jxl"))
        self.assertTrue(format_registry.is_image("photo.bmp"))
        self.assertTrue(format_registry.is_image("photo.tiff"))
        self.assertTrue(format_registry.is_image("photo.tif"))
        self.assertTrue(format_registry.is_image(".webp"))

    def test_video_formats(self):
        self.assertTrue(format_registry.is_video("clip.mp4"))
        self.assertTrue(format_registry.is_video("clip.webm"))
        self.assertTrue(format_registry.is_video("clip.mov"))
        self.assertTrue(format_registry.is_video("clip.mkv"))
        self.assertTrue(format_registry.is_video("clip.avi"))
        self.assertTrue(format_registry.is_video("clip.m4v"))
        self.assertTrue(format_registry.is_video("/path/to/folder/video.MP4"))

    def test_archive_formats(self):
        self.assertTrue(format_registry.is_archive("backup.zip"))
        self.assertTrue(format_registry.is_archive("backup.tar.gz"))
        self.assertTrue(format_registry.is_archive("backup.tgz"))
        self.assertTrue(format_registry.is_archive("backup.tar"))

    def test_unsupported_and_edge_cases(self):
        self.assertFalse(format_registry.is_supported("malware.exe"))
        self.assertFalse(format_registry.is_supported("script.sh"))
        self.assertFalse(format_registry.is_supported(""))
        self.assertFalse(format_registry.is_supported(None))
        self.assertIsNone(format_registry.get_format("unknown.xyz"))
        self.assertIsNone(format_registry.get_format_by_mime("unknown/mime"))

    def test_alias_resolution(self):
        # .jpeg should resolve to canonical .jpg format
        jpeg_fmt = format_registry.get_format(".jpeg")
        self.assertIsNotNone(jpeg_fmt)
        self.assertEqual(jpeg_fmt.extension, ".jpg")
        self.assertIn(".jpeg", jpeg_fmt.aliases)

        # .tif should resolve to canonical .tiff format
        tif_fmt = format_registry.get_format(".tif")
        self.assertIsNotNone(tif_fmt)
        self.assertEqual(tif_fmt.extension, ".tiff")
        self.assertIn(".tif", tif_fmt.aliases)

        # .heif should resolve to canonical .heic format
        heif_fmt = format_registry.get_format(".heif")
        self.assertIsNotNone(heif_fmt)
        self.assertEqual(heif_fmt.extension, ".heic")
        self.assertIn(".heif", heif_fmt.aliases)

        # .tgz should resolve to canonical .tar.gz format
        tgz_fmt = format_registry.get_format(".tgz")
        self.assertIsNotNone(tgz_fmt)
        self.assertEqual(tgz_fmt.extension, ".tar.gz")
        self.assertIn(".tgz", tgz_fmt.aliases)

    def test_requires_transcode(self):
        heic = format_registry.get_format(".heic")
        self.assertIsNotNone(heic)
        self.assertTrue(heic.requires_transcode)
        self.assertEqual(heic.transcode_target, ".webp")

        mkv = format_registry.get_format(".mkv")
        self.assertIsNotNone(mkv)
        self.assertTrue(mkv.requires_transcode)
        self.assertEqual(mkv.transcode_target, ".mp4")

        mov = format_registry.get_format(".mov")
        self.assertIsNotNone(mov)
        self.assertTrue(mov.requires_transcode)
        self.assertEqual(mov.transcode_target, ".mp4")

        jpg = format_registry.get_format(".jpg")
        self.assertIsNotNone(jpg)
        self.assertFalse(jpg.requires_transcode)

        jxl = format_registry.get_format(".jxl")
        self.assertIsNotNone(jxl)
        self.assertFalse(jxl.requires_transcode)
        self.assertIsNone(jxl.transcode_target)

    def test_to_json_dict_serialization(self):
        data = format_registry.to_json_dict()
        # Canonical formats should be top-level keys
        self.assertIn(".jpg", data)
        self.assertIn(".png", data)
        self.assertIn(".mp4", data)
        self.assertIn(".heic", data)
        self.assertIn(".jxl", data)
        self.assertIn(".tar.gz", data)

        # Aliases should NOT be top-level keys
        self.assertNotIn(".jpeg", data)
        self.assertNotIn(".tif", data)
        self.assertNotIn(".heif", data)
        self.assertNotIn(".tgz", data)

        # Aliases should be listed in canonical entry
        self.assertIn(".jpeg", data[".jpg"]["aliases"])
        self.assertIn(".heif", data[".heic"]["aliases"])

    def test_mime_type_lookup(self):
        self.assertEqual(format_registry.get_mime_type("test.avif"), "image/avif")
        self.assertEqual(format_registry.get_mime_type("test.mov"), "video/quicktime")
        self.assertEqual(format_registry.get_mime_type("test.heic"), "image/heic")
        self.assertEqual(format_registry.get_mime_type("test.jxl"), "image/jxl")
        self.assertEqual(format_registry.get_mime_type("test.unknown", default="application/octet-stream"), "application/octet-stream")

        # Reverse lookup by MIME
        fmt_jpg = format_registry.get_format_by_mime("image/jpeg")
        self.assertIsNotNone(fmt_jpg)
        self.assertEqual(fmt_jpg.extension, ".jpg")

        fmt_mp4 = format_registry.get_format_by_mime("video/mp4")
        self.assertIsNotNone(fmt_mp4)
        self.assertEqual(fmt_mp4.extension, ".mp4")

    def test_get_supported_extensions(self):
        images_with_aliases = format_registry.get_supported_extensions(FormatCategory.IMAGE, include_aliases=True)
        self.assertIn(".jpg", images_with_aliases)
        self.assertIn(".jpeg", images_with_aliases)

        images_primary_only = format_registry.get_supported_extensions(FormatCategory.IMAGE, include_aliases=False)
        self.assertIn(".jpg", images_primary_only)
        self.assertNotIn(".jpeg", images_primary_only)

        videos = format_registry.get_supported_extensions(FormatCategory.VIDEO)
        self.assertIn(".mp4", videos)
        self.assertIn(".mkv", videos)

    def test_determine_file_type(self):
        self.assertEqual(format_registry.determine_file_type("image/jpeg", "sample.jpg"), FileTypeEnum.image)
        self.assertEqual(format_registry.determine_file_type("image/gif", "sample.gif"), FileTypeEnum.gif)
        self.assertEqual(format_registry.determine_file_type("video/mp4", "sample.mp4"), FileTypeEnum.video)
        self.assertEqual(format_registry.determine_file_type("video/quicktime", "sample.mov"), FileTypeEnum.video)
        self.assertEqual(format_registry.determine_file_type("video/x-matroska", "sample.mkv"), FileTypeEnum.video)
        self.assertEqual(format_registry.determine_file_type("application/octet-stream", "sample.avif"), FileTypeEnum.image)
        self.assertEqual(format_registry.determine_file_type(None, "sample.mkv"), FileTypeEnum.video)
        self.assertEqual(format_registry.determine_file_type(None, "sample.unknown"), FileTypeEnum.image)

if __name__ == "__main__":
    unittest.main()
