import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from backend.app.config import settings
from backend.app.enums import FileTypeEnum, RatingEnum
from backend.app.models import Media
from backend.app.schemas import MediaResponse
from backend.app.utils.media_processor import process_media_file
from backend.app.utils.transcoder import (
    get_transcoded_path_for_original,
    get_transcode_target_ext,
    get_video_codec,
    is_transcoding_required,
    transcode_image,
    transcode_media_if_needed,
    transcode_video,
)
from tests.test_base import BackupTestBase

class TestTranscoderComprehensive(BackupTestBase):

    # --- Path Resolution & Hierarchy Preservation Tests ---

    def test_transcoded_path_deeply_nested_subfolders(self):
        orig_nested = settings.ORIGINAL_DIR / "2026" / "08" / "vacation" / "clip.mkv"
        trans_nested = get_transcoded_path_for_original(orig_nested, ".mp4")
        expected = (settings.TRANSCODED_DIR / "2026" / "08" / "vacation" / "clip.mkv.mp4").resolve()
        self.assertEqual(trans_nested, expected)

    def test_transcoded_path_root_original_folder(self):
        orig_file = settings.ORIGINAL_DIR / "standalone.heic"
        trans_file = get_transcoded_path_for_original(orig_file, ".webp")
        expected = (settings.TRANSCODED_DIR / "standalone.heic.webp").resolve()
        self.assertEqual(trans_file, expected)

    def test_transcoded_path_outside_original_dir_fallback(self):
        external_file = Path("/tmp/outside/nested/file.avi")
        trans_file = get_transcoded_path_for_original(external_file, ".mp4")
        expected = (settings.TRANSCODED_DIR / "file.avi.mp4").resolve()
        self.assertEqual(trans_file, expected)

    def test_transcoded_path_collision_safety(self):
        mkv_file = settings.ORIGINAL_DIR / "clip.mkv"
        mp4_file = settings.ORIGINAL_DIR / "clip.mp4"
        trans_mkv = get_transcoded_path_for_original(mkv_file, ".mp4")
        trans_mp4 = get_transcoded_path_for_original(mp4_file, ".mp4")
        self.assertNotEqual(trans_mkv, trans_mp4)
        self.assertTrue(trans_mkv.name.endswith("clip.mkv.mp4"))
        self.assertTrue(trans_mp4.name.endswith("clip.mp4.mp4"))

    # --- Image Transcoding Color Modes & Metadata Tests ---

    def test_transcode_image_rgb(self):
        src = self.base_path / "rgb_test.heic"
        with Image.new("RGB", (200, 100), color=(255, 128, 64)) as img:
            img.save(src, "PNG")

        dest = self.base_path / "rgb_out.webp"
        self.assertTrue(transcode_image(src, dest))
        self.assertTrue(dest.exists())
        with Image.open(dest) as out:
            self.assertEqual(out.format, "WEBP")
            self.assertEqual(out.size, (200, 100))

    def test_transcode_image_rgba_preserves_transparency(self):
        src = self.base_path / "rgba_test.heic"
        with Image.new("RGBA", (150, 150), color=(0, 0, 255, 128)) as img:
            img.save(src, "PNG")

        dest = self.base_path / "rgba_out.webp"
        self.assertTrue(transcode_image(src, dest))
        self.assertTrue(dest.exists())
        with Image.open(dest) as out:
            self.assertEqual(out.format, "WEBP")
            self.assertEqual(out.mode, "RGBA")

    def test_transcode_image_palette_mode(self):
        src = self.base_path / "palette_test.heic"
        with Image.new("P", (80, 80)) as img:
            img.save(src, "PNG")

        dest = self.base_path / "palette_out.webp"
        self.assertTrue(transcode_image(src, dest))
        self.assertTrue(dest.exists())

    def test_transcode_image_grayscale(self):
        src = self.base_path / "gray_test.heic"
        with Image.new("L", (100, 100), color=128) as img:
            img.save(src, "PNG")

        dest = self.base_path / "gray_out.webp"
        self.assertTrue(transcode_image(src, dest))
        self.assertTrue(dest.exists())

    def test_transcode_image_corrupt_file_cleans_up_temp(self):
        corrupt_src = self.base_path / "corrupt.heic"
        with open(corrupt_src, "wb") as f:
            f.write(b"NOT_A_VALID_IMAGE_DATA_CORRUPT")

        dest = self.base_path / "corrupt_out.webp"
        self.assertFalse(transcode_image(corrupt_src, dest))
        self.assertFalse(dest.exists())
        # Check no dangling .tmp files
        tmp_files = list(self.base_path.glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    # --- Video Transcoding Tests with FFmpeg & Mocking ---

    @patch("subprocess.run")
    def test_transcode_video_successful_execution(self, mock_run):
        # Simulate successful FFmpeg run creating temp file
        def fake_ffmpeg(cmd, **kwargs):
            self.assertTrue("ffmpeg" in cmd[0])
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"FAKE_MP4_CONTENT")
            result = MagicMock()
            result.returncode = 0
            return result

        mock_run.side_effect = fake_ffmpeg

        src = self.base_path / "sample.mkv"
        src.touch()
        dest = self.base_path / "output.mp4"

        self.assertTrue(transcode_video(src, dest))
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), b"FAKE_MP4_CONTENT")

    @patch("subprocess.run")
    def test_transcode_video_error_cleans_up_temp(self, mock_run):
        def fake_ffmpeg_error(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"PARTIAL_BROKEN_DATA")
            result = MagicMock()
            result.returncode = 1
            result.stderr = "Invalid data found when processing input"
            return result

        mock_run.side_effect = fake_ffmpeg_error

        src = self.base_path / "broken.mkv"
        src.touch()
        dest = self.base_path / "broken_out.mp4"

        self.assertFalse(transcode_video(src, dest))
        self.assertFalse(dest.exists())
        tmp_files = list(self.base_path.glob("*.tmp.mp4"))
        self.assertEqual(len(tmp_files), 0)

    # --- transcode_media_if_needed Logic & Caching Tests ---

    def test_transcode_media_if_needed_standard_formats_skipped(self):
        standard_extensions = [".jpg", ".png", ".gif", ".webp", ".avif", ".jxl", ".mp4", ".webm"]
        for ext in standard_extensions:
            p = self.base_path / f"test{ext}"
            p.touch()
            self.assertIsNone(transcode_media_if_needed(p))

    def test_transcode_media_if_needed_unsupported_formats_skipped(self):
        unsupported = [".txt", ".zip", ".tar.gz", ".csv", ".exe", ".pdf"]
        for ext in unsupported:
            p = self.base_path / f"test{ext}"
            p.touch()
            self.assertIsNone(transcode_media_if_needed(p))

    def test_transcode_media_if_needed_reuses_existing_transcode(self):
        # Place an original file in ORIGINAL_DIR
        settings.ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
        settings.TRANSCODED_DIR.mkdir(parents=True, exist_ok=True)
        
        orig_file = settings.ORIGINAL_DIR / "cached_test.heic"
        orig_file.touch()

        expected_transcoded = settings.TRANSCODED_DIR / "cached_test.heic.webp"
        expected_transcoded.write_bytes(b"ALREADY_TRANSCODED_WEBP_DATA")

        result = transcode_media_if_needed(orig_file)
        self.assertEqual(result, expected_transcoded)

        # Clean up test files from settings dirs
        orig_file.unlink(missing_ok=True)
        expected_transcoded.unlink(missing_ok=True)

    # --- Database Model & Schema Tests ---

    def test_media_model_and_schema_transcoded_path_field(self):
        from datetime import datetime, timezone
        media_inst = Media(
            id=1,
            filename="video.mkv",
            path="media/original/video.mkv",
            transcoded_path="media/transcoded/video.mp4",
            thumbnail_path="media/thumbnails/video.jpg",
            hash="abc123hash",
            file_type=FileTypeEnum.video,
            mime_type="video/x-matroska",
            file_size=1024000,
            width=1920,
            height=1080,
            duration=12.5,
            rating=RatingEnum.safe,
            uploaded_at=datetime.now(timezone.utc),
            is_shared=False,
        )
        self.assertEqual(media_inst.transcoded_path, "media/transcoded/video.mp4")

        # Test Pydantic serialization
        schema_obj = MediaResponse.model_validate(media_inst)
        self.assertEqual(schema_obj.transcoded_path, "media/transcoded/video.mp4")

    # --- Integration with process_media_file ---

    def test_process_media_file_integrates_transcode(self):
        # Create an image that requires transcoding
        settings.ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
        orig_heic = settings.ORIGINAL_DIR / "photo_process.heic"
        with Image.new("RGB", (320, 240), color=(100, 150, 200)) as img:
            img.save(orig_heic, "PNG")

        meta = process_media_file(orig_heic)
        self.assertEqual(meta["file_type"], FileTypeEnum.image)
        self.assertEqual(meta["width"], 320)
        self.assertEqual(meta["height"], 240)
        self.assertIsNotNone(meta["transcoded_path"])
        self.assertTrue(meta["transcoded_path"].endswith(".webp"))

        # Clean up
        orig_heic.unlink(missing_ok=True)
        trans_out = settings.BASE_DIR / meta["transcoded_path"]
        trans_out.unlink(missing_ok=True)

    # --- Codec Inspection & Transcoding Requirement Tests ---

    @patch("subprocess.run")
    def test_get_video_codec(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = (
            "Input #0, mov,mp4,m4a,3gp,3g2,mj2:\n"
            "  Stream #0:0[0x1](und): Video: hevc (Main) (hev1 / 0x31766568), yuv420p, 2560x1440\n"
        )
        mock_run.return_value = mock_proc
        test_file = self.base_path / "video.mp4"
        test_file.write_bytes(b"dummy")

        codec = get_video_codec(test_file)
        self.assertEqual(codec, "hevc")

    @patch("backend.app.utils.transcoder.probe_media_streams")
    def test_is_transcoding_required_for_hevc_mp4(self, mock_probe):
        mock_probe.return_value = {
            "success": True,
            "video_streams": [{"codec": "hevc", "profile": "main", "pix_fmt": "yuv420p"}],
            "audio_streams": [{"codec": "aac"}]
        }
        test_file = self.base_path / "video.mp4"
        test_file.touch()

        self.assertTrue(is_transcoding_required(test_file))

    @patch("backend.app.utils.transcoder.probe_media_streams")
    def test_is_transcoding_not_required_for_h264_mp4(self, mock_probe):
        mock_probe.return_value = {
            "success": True,
            "video_streams": [{"codec": "h264", "profile": "high", "pix_fmt": "yuv420p"}],
            "audio_streams": [{"codec": "aac"}]
        }
        test_file = self.base_path / "video.mp4"
        test_file.touch()

        self.assertFalse(is_transcoding_required(test_file))

    def test_is_transcoding_required_for_mkv_by_format(self):
        test_file = self.base_path / "video.mkv"
        self.assertTrue(is_transcoding_required(test_file))

    def test_get_transcode_target_ext(self):
        mkv = Path("clip.mkv")
        self.assertEqual(get_transcode_target_ext(mkv), ".mp4")
        heic = Path("photo.heic")
        self.assertEqual(get_transcode_target_ext(heic), ".webp")
        mp4 = Path("clip.mp4")
        self.assertEqual(get_transcode_target_ext(mp4), ".mp4")

    @patch("subprocess.run")
    def test_stream_probe_skips_attached_pic_and_detects_streams(self, mock_run):
        from backend.app.utils.transcoder import probe_media_streams, get_video_transcode_action
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = (
            "Input #0, matroska,webm, from 'test.mkv':\n"
            "  Stream #0:0(eng): Video: mjpeg (Baseline), yuvj420p, 500x500 (attached pic)\n"
            "  Stream #0:1(eng): Video: h264 (High), yuv420p(progressive), 1920x1080\n"
            "  Stream #0:2(eng): Audio: aac (LC), 48000 Hz, stereo\n"
        )
        mock_run.return_value = mock_proc
        test_file = self.base_path / "test.mkv"
        test_file.write_bytes(b"dummy")

        probe = probe_media_streams(test_file)
        self.assertTrue(probe["success"])
        self.assertEqual(len(probe["video_streams"]), 1)
        self.assertEqual(probe["video_streams"][0]["codec"], "h264")
        self.assertEqual(probe["video_streams"][0]["profile"], "high")

        # MKV with safe H.264 + AAC requires remux
        req, mode = get_video_transcode_action(test_file)
        self.assertTrue(req)
        self.assertEqual(mode, "remux")

    @patch("subprocess.run")
    def test_h264_high10_requires_full_transcode(self, mock_run):
        from backend.app.utils.transcoder import get_video_transcode_action
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = (
            "Input #0, mov,mp4,m4a:\n"
            "  Stream #0:0(und): Video: h264 (High 10), yuv420p10le, 1920x1080\n"
            "  Stream #0:1(und): Audio: aac (LC), 48000 Hz\n"
        )
        mock_run.return_value = mock_proc
        test_file = self.base_path / "clip.mp4"
        test_file.write_bytes(b"dummy")

        req, mode = get_video_transcode_action(test_file)
        self.assertTrue(req)
        self.assertEqual(mode, "full")

    @patch("subprocess.run")
    def test_h264_ac3_audio_requires_audio_transcode(self, mock_run):
        from backend.app.utils.transcoder import get_video_transcode_action
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = (
            "Input #0, mov,mp4,m4a:\n"
            "  Stream #0:0(und): Video: h264 (High), yuv420p, 1920x1080\n"
            "  Stream #0:1(und): Audio: ac3, 48000 Hz\n"
        )
        mock_run.return_value = mock_proc
        test_file = self.base_path / "clip.mp4"
        test_file.write_bytes(b"dummy")

        req, mode = get_video_transcode_action(test_file)
        self.assertTrue(req)
        self.assertEqual(mode, "audio_only")

    @patch("subprocess.run")
    def test_probe_failure_returns_unknown(self, mock_run):
        from backend.app.utils.transcoder import get_video_transcode_action, is_transcoding_required
        mock_run.side_effect = Exception("Probe timeout")
        test_file = self.base_path / "clip.mp4"
        test_file.write_bytes(b"dummy")

        req, mode = get_video_transcode_action(test_file)
        self.assertIsNone(req)
        self.assertEqual(mode, "unknown")
        self.assertIsNone(is_transcoding_required(test_file))

    @patch("subprocess.run")
    def test_transcode_video_remux_command_structure(self, mock_run):
        def fake_ffmpeg(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"REMUXED_DATA")
            res = MagicMock()
            res.returncode = 0
            return res
        mock_run.side_effect = fake_ffmpeg

        src = self.base_path / "clip.mkv"
        src.touch()
        dest = self.base_path / "clip.mkv.mp4"

        ok = transcode_video(src, dest, mode="remux")
        self.assertTrue(ok)
        self.assertTrue(dest.exists())
        cmd = mock_run.call_args[0][0]
        self.assertIn("-c", cmd)
        idx = cmd.index("-c")
        self.assertEqual(cmd[idx + 1], "copy")
        self.assertIn("-map", cmd)
        self.assertIn("0:v:0", cmd)
        self.assertIn("0:a:0?", cmd)

    @patch("subprocess.run")
    def test_transcode_video_audio_only_command_structure(self, mock_run):
        def fake_ffmpeg(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.write_bytes(b"AUDIO_TRANSCODED_DATA")
            res = MagicMock()
            res.returncode = 0
            return res
        mock_run.side_effect = fake_ffmpeg

        src = self.base_path / "clip.mp4"
        src.touch()
        dest = self.base_path / "clip.mp4.mp4"

        ok = transcode_video(src, dest, mode="audio_only")
        self.assertTrue(ok)
        self.assertTrue(dest.exists())
        cmd = mock_run.call_args[0][0]
        self.assertIn("-c:v", cmd)
        v_idx = cmd.index("-c:v")
        self.assertEqual(cmd[v_idx + 1], "copy")
        self.assertIn("-c:a", cmd)
        a_idx = cmd.index("-c:a")
        self.assertEqual(cmd[a_idx + 1], "aac")
        self.assertIn("-map", cmd)
        self.assertIn("0:v:0", cmd)
        self.assertIn("0:a:0?", cmd)

    @patch("subprocess.run")
    def test_transcode_video_fallback_when_remux_fails(self, mock_run):
        calls = []
        def fake_ffmpeg(cmd, **kwargs):
            calls.append(cmd)
            res = MagicMock()
            if len(calls) == 1:
                # First attempt (remux) fails
                res.returncode = 1
                res.stderr = "Invalid codec parameters"
                return res
            else:
                # Fallback to full transcode succeeds
                out_file = Path(cmd[-1])
                out_file.write_bytes(b"FULL_TRANSCODE_DATA")
                res.returncode = 0
                return res

        mock_run.side_effect = fake_ffmpeg

        src = self.base_path / "clip.mkv"
        src.touch()
        dest = self.base_path / "clip.mkv.mp4"

        ok = transcode_video(src, dest, mode="remux")
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        # Verify first call was remux (-c copy)
        self.assertIn("copy", calls[0])
        # Verify second call was full re-encode (-c:v libx264)
        self.assertIn("libx264", calls[1])

    @patch("backend.app.utils.transcoder.is_transcoding_required")
    @patch("backend.app.utils.transcoder.transcode_media_if_needed")
    def test_admin_do_transcode_incompatible_media_progressive_commit(self, mock_transcode, mock_req):
        from backend.app.routes.admin.media import _do_transcode_incompatible_media, _transcode_status
        from backend.app.database import SessionLocal

        mock_req.return_value = True
        mock_dest = self.base_path / "transcoded_out.mp4"
        mock_dest.write_bytes(b"DATA")
        mock_transcode.return_value = mock_dest

        orig = settings.ORIGINAL_DIR / "sample_admin.mkv"
        orig.touch()

        # Create a test media entry
        db = SessionLocal()
        try:
            m = Media(
                filename="sample_admin.mkv",
                path=str(orig.relative_to(settings.BASE_DIR)),
                hash="admin_hash_1",
                file_type=FileTypeEnum.video,
                mime_type="video/x-matroska",
                file_size=1000
            )
            db.add(m)
            db.commit()
            m_id = m.id
        finally:
            db.close()

        try:
            res = _do_transcode_incompatible_media()
            self.assertGreaterEqual(res["transcoded"], 1)
            self.assertFalse(_transcode_status["running"])
            self.assertIsNotNone(_transcode_status["last_result"])

            # Verify it committed to DB
            db2 = SessionLocal()
            try:
                updated = db2.query(Media).filter(Media.id == m_id).first()
                self.assertIsNotNone(updated.transcoded_path)
            finally:
                db2.close()
        finally:
            orig.unlink(missing_ok=True)
            mock_dest.unlink(missing_ok=True)
            db3 = SessionLocal()
            try:
                db3.query(Media).filter(Media.id == m_id).delete()
                db3.commit()
            finally:
                db3.close()

    @patch("backend.app.routes.admin.media.threading.Thread")
    def test_admin_transcode_media_route_sets_running_immediately(self, mock_thread_cls):
        import asyncio
        from fastapi import HTTPException
        from backend.app.routes.admin.media import transcode_media, _transcode_status, _maintenance_lock

        # Pre-seed status with stale results from a previous run
        _transcode_status.update({
            "running": False,
            "current": 10,
            "total": 10,
            "transcoded": 5,
            "already_transcoded": 5,
            "skipped": 0,
            "failed": 0,
            "current_file": "old.mp4",
            "error": "stale_error",
            "last_result": {"transcoded": 5},
        })

        mock_thread_instance = MagicMock()
        mock_thread_cls.return_value = mock_thread_instance

        # Call route
        mock_user = MagicMock()
        res = asyncio.run(transcode_media(current_user=mock_user))

        self.assertEqual(res["status"], "started")
        # Ensure thread was started
        mock_thread_instance.start.assert_called_once()

        # Verify running was immediately set to True and counters/error reset
        self.assertTrue(_transcode_status["running"])
        self.assertEqual(_transcode_status["current"], 0)
        self.assertEqual(_transcode_status["total"], 0)
        self.assertEqual(_transcode_status["transcoded"], 0)
        self.assertIsNone(_transcode_status["error"])
        self.assertIsNone(_transcode_status["last_result"])

        # While lock is acquired, calling again must raise 409
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(transcode_media(current_user=mock_user))
        self.assertEqual(ctx.exception.status_code, 409)

        # Cleanup lock and status
        if _maintenance_lock.locked():
            _maintenance_lock.release()
        _transcode_status["running"] = False

if __name__ == "__main__":
    unittest.main()
