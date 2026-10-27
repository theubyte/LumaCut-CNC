"""pi400/marlin/camera.py: fixed exposure, formats and snapshot size checks (no camera needed)."""
import unittest

from pi400.marlin import camera

FORMATS = """ioctl: VIDIOC_ENUM_FMT
	Type: Video Capture

	[0]: 'MJPG' (Motion-JPEG, compressed)
		Size: Discrete 1920x1080
			Interval: Discrete 0.033s (30.000 fps)
		Size: Discrete 1280x720
			Interval: Discrete 0.033s (30.000 fps)
		Size: Discrete 640x480
	[1]: 'YUYV' (YUYV 4:2:2)
		Size: Discrete 640x480
		Size: Discrete 320x240
"""


def jpeg(width, height):
    """Smallest byte string with SOI, an APP0 segment and a baseline SOF0."""
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0\x00\x11\x08" + bytes([height >> 8, height & 255, width >> 8, width & 255]) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


class HeadCameraTest(unittest.TestCase):
    def test_validate_accepts_null_and_ints_only(self):
        self.assertEqual(camera.validate({}), camera.DEFAULTS)
        self.assertEqual(camera.validate({"exposure": 300, "gain": 0, "white_balance": 5000, "light": 80}),
                         {"exposure": 300, "gain": 0, "white_balance": 5000, "light": 80})
        for bad in ({"exposure": 0}, {"gain": True}, {"white_balance": 4500.5}, {"light": 101}, {"iso": 100}, []):
            with self.assertRaises(ValueError):
                camera.validate(bad)

    def test_control_steps_switch_automatics_first(self):
        self.assertEqual(camera.control_steps(camera.DEFAULTS), [["auto_exposure=3", "white_balance_automatic=1"]])
        steps = camera.control_steps({"exposure": 250, "gain": 2, "white_balance": 4800, "light": None})
        self.assertEqual(steps[0], ["auto_exposure=1", "white_balance_automatic=0", "exposure_dynamic_framerate=0"])
        self.assertEqual(steps[1], ["exposure_time_absolute=250", "white_balance_temperature=4800", "gain=2"])

    def test_values_are_clamped_to_the_camera(self):
        text = ("     exposure_time_absolute 0x009a0902 (int)    : min=78 max=1250 step=1 default=312 value=312 flags=inactive\n"
                "                       gain 0x00980913 (int)    : min=0 max=10 step=1 default=0 value=0\n")
        limits = {k: v for k, v in ((key, camera.parse_controls(text).get(ctl)) for key, ctl in camera.CONTROLS.items()) if v}
        self.assertEqual(limits, {"exposure": (78, 1250), "gain": (0, 10)})
        steps = camera.control_steps({"exposure": 5000, "gain": 40, "white_balance": None}, limits)
        self.assertEqual(steps[1], ["exposure_time_absolute=1250", "gain=10"])

    def test_formats_prefer_mjpeg(self):
        sizes = camera.parse_formats(FORMATS)
        self.assertEqual(sizes[(1920, 1080)], "MJPG")
        self.assertEqual(sizes[(640, 480)], "MJPG")
        self.assertEqual(sizes[(320, 240)], "YUYV")

    def test_ffmpeg_uses_mjpeg_at_15_fps(self):
        cmd = camera.ffmpeg_command("/dev/video0", 1920, 1080, "MJPG", 3)
        self.assertIn("mjpeg", cmd)
        self.assertEqual(cmd[cmd.index("-framerate") + 1], "15")
        self.assertNotIn("-input_format", camera.ffmpeg_command("/dev/video0", 320, 240, "YUYV", 8))

    def test_jpeg_size(self):
        self.assertEqual(camera.jpeg_size(jpeg(1920, 1080)), (1920, 1080))
        self.assertIsNone(camera.jpeg_size(b"\xff\xd8\xff\xd9"))


if __name__ == "__main__":
    unittest.main()
