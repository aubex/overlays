"""
Stress test client for the overlays server.

This client is designed to stress test the server implementation by:
- Sending rapid requests
- Testing all available functionality
- Measuring performance and response times
- Testing edge cases and error conditions
"""

import argparse
import logging
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

try:
    from overlays.client import RemoteElapsedTimeWindow, get_overlay_client
except ImportError:
    from src.overlays.client import RemoteElapsedTimeWindow, get_overlay_client

try:
    import win32api
except ImportError:
    win32api = None

logger = logging.getLogger(__name__)
T = TypeVar("T")
DEMO_REPO_URL = "https://github.com/aubex/overlays"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure console logging for standalone execution."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

# Fun randomization constants
RANDOM_EMOJIS = [
    "🎯",
    "🎪",
    "🎨",
    "🎭",
    "🎪",
    "🎊",
    "🎉",
    "✨",
    "💫",
    "⭐",
    "🌟",
    "💥",
    "🔥",
    "⚡",
    "🌈",
    "🎆",
]
COUNTDOWN_MESSAGES = [
    "🚀 Launching in",
    "⏰ Countdown active",
    "🎯 Target acquired",
    "💥 Detonation in",
    "🌟 Magic happens in",
    "⚡ Power surge in",
    "🎪 Show starts in",
    "🎨 Creating art in",
    "🎭 Performance begins in",
    "🎊 Party starts in",
    "✨ Sparkles appear in",
    "💫 Wonder begins in",
]
HIGHLIGHT_MESSAGES = [
    "🔍 Spotlight",
    "🎯 Focus here",
    "⭐ Look at this",
    "💥 Attention",
    "🌟 Important area",
]
ELAPSED_MESSAGES = [
    "🎪 Show in progress",
    "🎨 Creating masterpiece",
    "⚡ Processing magic",
    "🌟 Working wonders",
    "💫 Crafting excellence",
    "🎯 Mission active",
    "🔥 In the zone",
    "✨ Making magic happen",
]
RAPID_MESSAGES = [
    "🚀 Rocket",
    "⚡ Lightning",
    "💥 Boom",
    "🌟 Star",
    "🎯 Dart",
    "🔥 Fire",
    "💫 Comet",
    "✨ Spark",
]
WRAPPER_MESSAGES = [
    "🎭 Theater mode",
    "🎪 Circus act",
    "🎨 Art studio",
    "🌟 Star chamber",
    "⚡ Power lab",
    "💫 Wonder room",
]
DEMO_ELAPSED_UPDATES = [
    "Python drives the overlay state remotely",
    "Messages update live without blocking your workflow",
    "Clean enough for demos, streams, and handoffs",
]


# Color codes for console output
class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


@dataclass
class TestResult:
    """Container for test results."""

    test_name: str
    success: bool
    duration: float
    error_message: str = ""
    additional_data: dict[str, Any] = field(default_factory=dict)


class StressTestClient:
    """Comprehensive stress testing client for the overlay server."""

    def __init__(self, timeout: int = 5000, seed: int | None = None):
        """
        Initialize the stress test client.

        Args:
            timeout: Connection timeout in milliseconds
            seed: Optional random seed for reproducible runs
        """
        self.timeout = timeout
        self.seed = seed
        self.results: list[TestResult] = []
        self.active_windows: list[int] = []
        self.test_start_time = 0.0
        if self.seed is not None:
            random.seed(self.seed)
            logger.info("Using random seed %s", self.seed)
        self.overlay_client = get_overlay_client(self.timeout)

    def log_result(self, result: TestResult) -> None:
        """Log and store a test result with colorful output."""
        self.results.append(result)

        # Add random emoji for visual flair
        random_emoji = random.choice(RANDOM_EMOJIS)

        if result.success:
            status = f"{Colors.OKGREEN}✅ PASS{Colors.ENDC}"
            log_status = "PASS"
            print(
                f"{random_emoji} {Colors.BOLD}{result.test_name}{Colors.ENDC} - {status} ({result.duration:.3f}s)"
            )
        else:
            status = f"{Colors.FAIL}❌ FAIL{Colors.ENDC}"
            log_status = "FAIL"
            print(
                f"{random_emoji} {Colors.BOLD}{result.test_name}{Colors.ENDC} - {status} ({result.duration:.3f}s)"
            )
            if result.error_message:
                print(
                    f"   {Colors.WARNING}⚠️  Error: {result.error_message}{Colors.ENDC}"
                )

        logger.info("%s %s (%.3fs)", log_status, result.test_name, result.duration)
        if not result.success and result.error_message:
            logger.error("Error: %s", result.error_message)

    def measure_time(self, func, *args, **kwargs) -> tuple[T, float]:
        """Measure execution time of a function."""
        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration = time.perf_counter() - start_time
            return result, duration
        except Exception:
            duration = time.perf_counter() - start_time
            logger.debug(
                "Operation %s failed after %.3fs",
                getattr(func, "__name__", repr(func)),
                duration,
            )
            raise

    def _track_window(self, window_id: int | None) -> None:
        """Track a created window so cleanup can retry if needed."""
        if window_id is not None and window_id not in self.active_windows:
            self.active_windows.append(window_id)

    def _mark_window_closed(self, window_id: int) -> None:
        """Forget a window once it has been closed successfully."""
        if window_id in self.active_windows:
            self.active_windows.remove(window_id)

    def _close_tracked_window(self, window_id: int) -> bool:
        """Close a window and only forget it if the close succeeded."""
        closed = self.overlay_client.close_window(window_id)
        if closed:
            self._mark_window_closed(window_id)
        return closed

    def _run_rapid_request(self, request_index: int) -> tuple[bool, str | None]:
        """Execute one rapid request and report whether the full request succeeded."""
        request_type = random.choice(["countdown", "highlight", "elapsed"])

        if request_type == "countdown":
            rapid_msg = random.choice(RAPID_MESSAGES)
            duration = random.uniform(0.5, 2.0)
            succeeded = self.overlay_client.create_countdown_window(
                f"{rapid_msg} #{request_index}", int(duration)
            )
            return succeeded, None if succeeded else "countdown creation failed"

        if request_type == "highlight":
            x = random.randint(100, 800)
            y = random.randint(100, 400)
            width = random.randint(50, 200)
            height = random.randint(30, 100)
            rect = (x, y, x + width, y + height)
            duration = random.uniform(0.5, 2.0)
            succeeded = self.overlay_client.create_highlight_window(rect, int(duration))
            return succeeded, None if succeeded else "highlight creation failed"

        rapid_msg = random.choice(RAPID_MESSAGES)
        window_id = self.overlay_client.create_elapsed_time_window(
            f"{rapid_msg} #{request_index}"
        )
        if window_id is None:
            return False, "elapsed window creation failed"

        self._track_window(window_id)

        if random.choice([True, False]):
            update_msg = random.choice(RAPID_MESSAGES)
            updated = self.overlay_client.update_window_message(
                window_id, f"{update_msg} - Updated!"
            )
            if not updated:
                closed = self._close_tracked_window(window_id)
                if not closed:
                    return False, "elapsed update failed and cleanup close failed"
                return False, "elapsed update failed"

        closed = self._close_tracked_window(window_id)
        if not closed:
            return False, "elapsed close failed"

        return True, None

    def _print_scene_banner(
        self, title: str, subtitle: str, color: str = Colors.OKCYAN
    ) -> None:
        """Print a clean banner for showcase scenes."""
        print(f"\n{color}{Colors.BOLD}{title}{Colors.ENDC}")
        print(f"{Colors.OKCYAN}{subtitle}{Colors.ENDC}")

    def _get_screen_size(self) -> tuple[int, int]:
        """Return the primary screen dimensions, with a conservative fallback."""
        if win32api is not None:
            try:
                width = win32api.GetSystemMetrics(0)
                height = win32api.GetSystemMetrics(1)
                if width > 0 and height > 0:
                    return width, height
            except Exception as e:
                logger.debug("Falling back from win32api screen metrics: %s", e)

        try:
            import ctypes

            width = ctypes.windll.user32.GetSystemMetrics(0)
            height = ctypes.windll.user32.GetSystemMetrics(1)
            if width > 0 and height > 0:
                return width, height
        except Exception as e:
            logger.debug("Falling back to default screen metrics: %s", e)

        return 1920, 1080

    def _demo_highlight_rectangles(self) -> list[tuple[int, int, int, int]]:
        """Build a few visually balanced highlight regions for the showcase."""
        screen_width, screen_height = self._get_screen_size()
        margin_x = max(48, screen_width // 24)
        margin_y = max(48, screen_height // 18)
        center_width = max(280, screen_width // 3)
        center_height = max(180, screen_height // 4)

        return [
            (
                margin_x,
                margin_y,
                margin_x + max(240, screen_width // 4),
                margin_y + max(140, screen_height // 5),
            ),
            (
                (screen_width - center_width) // 2,
                (screen_height - center_height) // 2,
                (screen_width + center_width) // 2,
                (screen_height + center_height) // 2,
            ),
            (
                screen_width - max(240, screen_width // 4) - margin_x,
                screen_height - max(180, screen_height // 4) - margin_y,
                screen_width - margin_x,
                screen_height - margin_y,
            ),
        ]

    def _run_demo_scene(self, scene_name: str, scene: Callable[[], None]) -> bool:
        """Run one showcase scene and record a single high-level result."""
        try:
            _, duration = self.measure_time(scene)
            self.log_result(TestResult(scene_name, True, duration))
            return True
        except Exception as e:
            self.log_result(TestResult(scene_name, False, 0.0, str(e)))
            return False

    def _demo_highlights_scene(self) -> None:
        """Show crisp highlight overlays in deliberate positions."""
        self._print_scene_banner(
            "Highlight Any Screen Region",
            "Guide attention instantly with clean click-through outlines.",
            Colors.OKCYAN,
        )
        for index, rect in enumerate(self._demo_highlight_rectangles(), start=1):
            created = self.overlay_client.create_highlight_window(rect, 2)
            if not created:
                raise RuntimeError(f"Failed to create highlight overlay {index}")
            time.sleep(0.55)
        time.sleep(1.1)

    def _demo_countdown_scene(self) -> None:
        """Show a countdown overlay with enough time to read it in a GIF."""
        self._print_scene_banner(
            "Start a Countdown Instantly",
            "Useful for demos, presentations, and focused handoffs.",
            Colors.WARNING,
        )
        created = self.overlay_client.create_countdown_window("Launch sequence", 3)
        if not created:
            raise RuntimeError("Failed to create countdown overlay")
        time.sleep(3.4)

    def _demo_elapsed_scene(self) -> None:
        """Show a live timer with a few clear message updates."""
        self._print_scene_banner(
            "Update a Live Timer Remotely",
            "Drive overlay state from Python while work continues.",
            Colors.OKBLUE,
        )
        window_id = self.overlay_client.create_elapsed_time_window(
            "Overlay demo running..."
        )
        if window_id is None:
            raise RuntimeError("Failed to create elapsed-time overlay")

        self._track_window(window_id)
        time.sleep(0.7)

        for update in DEMO_ELAPSED_UPDATES:
            updated = self.overlay_client.update_window_message(window_id, update)
            if not updated:
                raise RuntimeError("Failed to update elapsed-time overlay")
            time.sleep(0.85)

        closed = self._close_tracked_window(window_id)
        if not closed:
            raise RuntimeError("Failed to close elapsed-time overlay")

    def _demo_qrcode_scene(self, repo_url: str) -> None:
        """Show a QR code that points viewers to the repository."""
        self._print_scene_banner(
            "Share a Link Instantly",
            "Turn any URL into a scannable QR overlay.",
            Colors.OKGREEN,
        )
        caption = repo_url.removeprefix("https://").removeprefix("http://")
        window_id = self.overlay_client.create_qrcode_window(
            repo_url,
            duration=10,
            caption=caption,
        )
        if window_id is None:
            raise RuntimeError("Failed to create QR code overlay")

        self._track_window(window_id)
        time.sleep(2.6)

        closed = self._close_tracked_window(window_id)
        if not closed:
            raise RuntimeError("Failed to close QR code overlay")

    def _demo_finale_scene(self) -> None:
        """End with a layered scene that shows multiple overlay types together."""
        self._print_scene_banner(
            "Combine Overlay Types",
            "Countdowns, highlights, timers, and QR codes can share the screen.",
            Colors.HEADER,
        )
        hero_rect = self._demo_highlight_rectangles()[1]
        highlighted = self.overlay_client.create_highlight_window(hero_rect, 3)
        if not highlighted:
            raise RuntimeError("Failed to create finale highlight")

        window_id = self.overlay_client.create_elapsed_time_window(
            "Remote overlays in real time"
        )
        if window_id is None:
            raise RuntimeError("Failed to create finale status window")

        self._track_window(window_id)
        time.sleep(0.45)

        countdown_started = self.overlay_client.create_countdown_window("Wrap-up in", 3)
        if not countdown_started:
            raise RuntimeError("Failed to create finale countdown")

        time.sleep(0.85)
        updated = self.overlay_client.update_window_message(
            window_id,
            "Highlights, countdowns, timers, and QR codes",
        )
        if not updated:
            raise RuntimeError("Failed to update finale status window")

        time.sleep(1.4)
        closed = self._close_tracked_window(window_id)
        if not closed:
            raise RuntimeError("Failed to close finale status window")

        time.sleep(0.8)

    def run_demo(self, repo_url: str = DEMO_REPO_URL) -> None:
        """Run a short, deterministic showcase intended for screencasts."""
        self.test_start_time = time.perf_counter()
        initial_result_count = len(self.results)

        print("🎬 Starting overlay showcase")
        print("=" * 60)

        if not self.overlay_client.is_available():
            self.log_result(
                TestResult("Showcase Setup", False, 0.0, "Server not available")
            )
            return

        scene_plan = [
            ("✨ Spotlight Regions", self._demo_highlights_scene),
            ("⏰ Countdown Overlay", self._demo_countdown_scene),
            ("🔄 Live Timer Updates", self._demo_elapsed_scene),
            ("🔗 QR Code Share", lambda: self._demo_qrcode_scene(repo_url)),
            ("🎬 Overlay Finale", self._demo_finale_scene),
        ]

        try:
            for scene_name, scene in scene_plan:
                if not self._run_demo_scene(scene_name, scene):
                    break
        except KeyboardInterrupt:
            logger.warning("Showcase interrupted by user")
        finally:
            self.cleanup_remaining_windows()

        scene_results = self.results[initial_result_count:]
        passed_scenes = sum(1 for result in scene_results if result.success)
        print("\n🎥 Showcase complete")
        print(f"Scenes completed: {passed_scenes}/{len(scene_results)}")
        print(f"Runtime: {time.perf_counter() - self.test_start_time:.2f}s")

    def test_basic_connectivity(self) -> None:
        """Test basic connection to the overlay server."""
        logger.info("🔌 Testing basic connectivity...")

        try:
            start_time = time.perf_counter()
            is_available = self.overlay_client.is_available()
            duration = time.perf_counter() - start_time

            self.log_result(
                TestResult(
                    "Basic Connectivity",
                    is_available,
                    duration,
                    "" if is_available else "Server not available",
                )
            )
        except Exception as e:
            self.log_result(TestResult("Basic Connectivity", False, 0.0, str(e)))

    def test_countdown_windows(self, count: int = 5) -> None:
        """Test creating multiple countdown windows with random messages and timing."""
        emoji = random.choice(RANDOM_EMOJIS)
        print(
            f"\n{Colors.HEADER}{emoji} Testing {count} countdown windows with random flair!{Colors.ENDC}"
        )

        if not self.overlay_client.is_available():
            self.log_result(
                TestResult("Countdown Windows", False, 0.0, "Server not available")
            )
            return

        for i in range(count):
            try:
                # Use random countdown message and timing
                random_message = random.choice(COUNTDOWN_MESSAGES)
                random_duration = random.uniform(
                    1.5, 3.5
                )  # Random duration between 1.5-3.5 seconds

                result, duration = self.measure_time(
                    self.overlay_client.create_countdown_window,
                    f"{random_message} {i + 1}",
                    int(random_duration),
                )

                self.log_result(
                    TestResult(
                        f"🎯 Countdown Window {i + 1}",
                        result,
                        duration,
                        "" if result else "Failed to create countdown window",
                    )
                )

                # Random delay between operations for visual effect
                time.sleep(random.uniform(0.05, 0.2))

            except Exception as e:
                self.log_result(
                    TestResult(f"Countdown Window {i + 1}", False, 0.0, str(e))
                )

    def test_highlight_windows(self, count: int = 5) -> None:
        """Test creating multiple highlight windows with random positions and timing."""
        emoji = random.choice(RANDOM_EMOJIS)
        print(
            f"\n{Colors.OKCYAN}{emoji} Testing {count} highlight windows with random positions!{Colors.ENDC}"
        )

        if not self.overlay_client.is_available():
            self.log_result(
                TestResult("Highlight Windows", False, 0.0, "Server not available")
            )
            return

        for i in range(count):
            try:
                # Generate more varied random rectangle coordinates
                screen_width = random.randint(
                    800, 1920
                )  # Simulate different screen sizes
                screen_height = random.randint(600, 1080)

                x1 = random.randint(50, screen_width // 2)
                y1 = random.randint(50, screen_height // 2)
                width = random.randint(80, 400)
                height = random.randint(40, 200)
                x2 = min(x1 + width, screen_width - 50)
                y2 = min(y1 + height, screen_height - 50)
                rect = (x1, y1, x2, y2)

                # Random duration for variety
                random_duration = random.uniform(1.0, 4.0)

                result, duration = self.measure_time(
                    self.overlay_client.create_highlight_window,
                    rect,
                    int(random_duration),
                )

                # Use random highlight message for display
                highlight_msg = random.choice(HIGHLIGHT_MESSAGES)
                self.log_result(
                    TestResult(
                        f"🎯 {highlight_msg} {i + 1}",
                        result,
                        duration,
                        "" if result else "Failed to create highlight window",
                        {"rect": rect, "size": f"{width}x{height}"},
                    )
                )

                # Random delay for visual effect
                time.sleep(random.uniform(0.05, 0.25))

            except Exception as e:
                self.log_result(
                    TestResult(f"Highlight Window {i + 1}", False, 0.0, str(e))
                )

    def test_qrcode_window(self, duration: int = 1) -> None:
        """Test creating qr code window."""

        if not self.overlay_client.is_available():
            self.log_result(
                TestResult("Create QR code window", False, 0.0, "Server not available")
            )
            return

        try:
            window_id, actual_duration = self.measure_time(
                self.overlay_client.create_qrcode_window,
                **{
                    "data": "dummy_test",
                    "duration": duration,
                    "caption": "dummy_test",
                },
            )

            success = window_id is not None
            self.log_result(
                TestResult(
                    "⏱️ Create QR code window",
                    success,
                    actual_duration,
                    "" if success else "Failed to create QR code window",
                    {"window_id": window_id},
                )
            )

            # Random delay for visual effect
            time.sleep(random.uniform(0.08, 0.15))

        except Exception as e:
            self.log_result(
                TestResult("Create QR code window", False, duration, str(e))
            )

    def test_elapsed_time_windows(self, count: int = 3) -> None:
        """Test creating and managing elapsed time windows with random messages."""
        emoji = random.choice(RANDOM_EMOJIS)
        print(
            f"\n{Colors.OKBLUE}{emoji} Testing {count} elapsed time windows with dynamic updates!{Colors.ENDC}"
        )

        if not self.overlay_client.is_available():
            self.log_result(
                TestResult("Elapsed Time Windows", False, 0.0, "Server not available")
            )
            return

        created_windows = []

        # Create windows with random messages
        for i in range(count):
            try:
                random_message = random.choice(ELAPSED_MESSAGES)
                window_id, duration = self.measure_time(
                    self.overlay_client.create_elapsed_time_window,
                    f"{random_message} #{i + 1}",
                )

                success = window_id is not None
                self.log_result(
                    TestResult(
                        f"⏱️ Create {random_message} {i + 1}",
                        success,
                        duration,
                        "" if success else "Failed to create elapsed time window",
                        {"window_id": window_id},
                    )
                )

                if window_id:
                    created_windows.append(window_id)
                self._track_window(window_id)

                # Random delay for visual effect
                time.sleep(random.uniform(0.08, 0.15))

            except Exception as e:
                self.log_result(
                    TestResult(
                        f"Create Elapsed Time Window {i + 1}", False, 0.0, str(e)
                    )
                )

        # Update messages with random content
        for i, window_id in enumerate(created_windows):
            try:
                # Generate multiple random updates
                update_count = random.randint(2, 4)
                for update_num in range(update_count):
                    random_update = random.choice(ELAPSED_MESSAGES)
                    result, duration = self.measure_time(
                        self.overlay_client.update_window_message,
                        window_id,
                        f"{random_update} - Update {update_num + 1}",
                    )

                    self.log_result(
                        TestResult(
                            f"🔄 Update Window {i + 1}-{update_num + 1}",
                            result,
                            duration,
                            "" if result else "Failed to update window message",
                        )
                    )

                    # Random delay between updates
                    time.sleep(random.uniform(0.05, 0.12))

            except Exception as e:
                self.log_result(
                    TestResult(f"Update Window Message {i + 1}", False, 0.0, str(e))
                )

        # Close windows with random timing
        for i, window_id in enumerate(created_windows):
            try:
                # Random delay before closing
                time.sleep(random.uniform(0.1, 0.3))

                result, duration = self.measure_time(
                    self._close_tracked_window, window_id
                )

                self.log_result(
                    TestResult(
                        f"🗑️ Close Window {i + 1}",
                        result,
                        duration,
                        "" if result else "Failed to close window",
                    )
                )
            except Exception as e:
                self.log_result(TestResult(f"Close Window {i + 1}", False, 0.0, str(e)))

    def test_break_functionality(self, break_duration: int = 5) -> None:
        """Test break behavior, including command discard and recovery."""
        logger.info("☕ Testing break functionality...")

        if not self.overlay_client.is_available():
            self.log_result(
                TestResult("Break Functionality", False, 0.0, "Server not available")
            )
            return

        # Test taking a break
        try:
            result, duration = self.measure_time(
                self.overlay_client.take_break,
                break_duration,
            )

            self.log_result(
                TestResult(
                    "Take Break",
                    result,
                    duration,
                    "" if result else "Failed to initiate break",
                )
            )

            if not result:
                return

            discard_response, discard_duration = self.measure_time(
                self.overlay_client._send_command,
                "create_elapsed_time",
                {"message_text": "This should be discarded during break"},
            )
            discarded = (
                discard_response
                == {
                    "status": "ignored",
                    "reason": "break_active",
                    "message": "Command discarded during break",
                }
                and discard_duration < 1
            )

            self.log_result(
                TestResult(
                    "Discard Command During Break",
                    discarded,
                    discard_duration,
                    ""
                    if discarded
                    else f"Unexpected response while paused: {discard_response!r}",
                    {"response": discard_response},
                )
            )

            if discard_response.get("status") == "success":
                leaked_window_id = discard_response.get("window_id")
                if leaked_window_id:
                    self._track_window(leaked_window_id)
                    self._close_tracked_window(leaked_window_id)

            result, duration = self.measure_time(self.overlay_client.cancel_break)

            self.log_result(
                TestResult(
                    "Cancel Break",
                    result,
                    duration,
                    "" if result else "Failed to cancel break",
                )
            )

            if not result:
                return

            window_id, duration = self.measure_time(
                self.overlay_client.create_elapsed_time_window,
                "Break finished - commands active again",
            )
            resumed = window_id is not None

            self.log_result(
                TestResult(
                    "Command After Break",
                    resumed,
                    duration,
                    "" if resumed else "Command still blocked after cancel_break",
                    {"window_id": window_id},
                )
            )

            if window_id:
                self._track_window(window_id)

        except Exception as e:
            self.log_result(TestResult("Break Functionality", False, 0.0, str(e)))

    def test_rapid_requests(self, request_count: int = 20) -> None:
        """Test rapid successive requests with random messages and timing."""
        emoji = random.choice(RANDOM_EMOJIS)
        print(
            f"\n{Colors.WARNING}{emoji} Testing {request_count} rapid requests with random chaos!{Colors.ENDC}"
        )

        if not self.overlay_client.is_available():
            self.log_result(
                TestResult("Rapid Requests", False, 0.0, "Server not available")
            )
            return

        if request_count <= 0:
            self.log_result(
                TestResult(
                    "Rapid Requests",
                    False,
                    0.0,
                    "request_count must be greater than zero",
                )
            )
            return

        start_time = time.perf_counter()
        successful_requests = 0
        failure_samples: list[str] = []

        for i in range(request_count):
            try:
                result, failure_reason = self._run_rapid_request(i)
                if result:
                    successful_requests += 1
                elif failure_reason and len(failure_samples) < 3:
                    failure_samples.append(failure_reason)

                # Random micro-delay for chaos
                if random.choice([True, False]):
                    time.sleep(random.uniform(0.001, 0.01))

            except Exception as e:
                logger.error("Rapid request %s failed: %s", i, e)
                if len(failure_samples) < 3:
                    failure_samples.append(str(e))

        total_duration = time.perf_counter() - start_time
        success_rate = successful_requests / request_count
        requests_per_second = (
            request_count / total_duration if total_duration > 0 else float("inf")
        )
        message = f"Success rate: {success_rate:.2%} ({successful_requests}/{request_count})"
        if failure_samples:
            message = f"{message}; sample failures: {', '.join(failure_samples)}"

        self.log_result(
            TestResult(
                "⚡ Rapid Chaos Test",
                success_rate > 0.8,  # Consider successful if >80% succeed
                total_duration,
                message,
                {
                    "total_requests": request_count,
                    "successful_requests": successful_requests,
                    "success_rate": success_rate,
                    "requests_per_second": requests_per_second,
                    "failure_samples": failure_samples,
                },
            )
        )

    def test_edge_cases(self) -> None:
        """Test various edge cases and error conditions."""
        logger.info("🧪 Testing edge cases...")

        if not self.overlay_client.is_available():
            self.log_result(
                TestResult("Edge Cases", False, 0.0, "Server not available")
            )
            return

        # Test invalid window ID operations
        try:
            result, duration = self.measure_time(
                self.overlay_client.close_window,
                99999,  # Non-existent window ID
            )

            self.log_result(
                TestResult(
                    "Close Invalid Window ID",
                    result is False,
                    duration,
                    ""
                    if result is False
                    else "Unexpectedly closed a non-existent window",
                    {"returned": result},
                )
            )
        except Exception as e:
            self.log_result(TestResult("Close Invalid Window ID", False, 0.0, str(e)))

        # Test update message on non-existent window
        try:
            result, duration = self.measure_time(
                self.overlay_client.update_window_message,
                99999,
                "This should fail gracefully",
            )

            self.log_result(
                TestResult(
                    "Update Invalid Window Message",
                    result is False,
                    duration,
                    ""
                    if result is False
                    else "Unexpectedly updated a non-existent window",
                    {"returned": result},
                )
            )
        except Exception as e:
            self.log_result(
                TestResult("Update Invalid Window Message", False, 0.0, str(e))
            )

        # Test extreme values
        try:
            result, duration = self.measure_time(
                self.overlay_client.create_countdown_window,
                "A" * 1000,  # Very long message
                0,  # Zero countdown
            )

            self.log_result(
                TestResult(
                    "Extreme Values Test",
                    result,
                    duration,
                    "" if result else "Failed with extreme values",
                )
            )
        except Exception as e:
            self.log_result(TestResult("Extreme Values Test", False, 0.0, str(e)))

    def test_remote_elapsed_time_window(self) -> None:
        """Test the RemoteElapsedTimeWindow wrapper class with random messages."""
        emoji = random.choice(RANDOM_EMOJIS)
        print(
            f"\n{Colors.HEADER}{emoji} Testing RemoteElapsedTimeWindow wrapper with random magic!{Colors.ENDC}"
        )

        if not self.overlay_client.is_available():
            self.log_result(
                TestResult("Remote Window Wrapper", False, 0.0, "Server not available")
            )
            return

        try:
            wrapper_start_time = time.perf_counter()
            # Create window using the wrapper with random message
            wrapper_msg = random.choice(WRAPPER_MESSAGES)
            window_id = self.overlay_client.create_elapsed_time_window(
                f"{wrapper_msg} - Remote Test"
            )

            if window_id:
                self._track_window(window_id)
                remote_window = RemoteElapsedTimeWindow(window_id, self.overlay_client)

                # Test updating message with random content
                start_time = time.perf_counter()
                initial_update = random.choice(WRAPPER_MESSAGES)
                result = remote_window.update_message(
                    f"{initial_update} - Wrapper Active!"
                )
                duration = time.perf_counter() - start_time

                self.log_result(
                    TestResult(
                        "🎭 Remote Window Update",
                        result,
                        duration,
                        "" if result else "Failed to update via wrapper",
                    )
                )

                # Test multiple random updates with varying delays
                update_count = random.randint(3, 6)
                for i in range(update_count):
                    random_delay = random.uniform(0.05, 0.2)
                    time.sleep(random_delay)

                    random_wrapper_msg = random.choice(WRAPPER_MESSAGES)
                    random_emoji_msg = random.choice(RANDOM_EMOJIS)
                    update_result = remote_window.update_message(
                        f"{random_wrapper_msg} {random_emoji_msg} - Update #{i + 1}"
                    )

                    self.log_result(
                        TestResult(
                            f"🔄 Wrapper Update {i + 1}",
                            update_result,
                            random_delay,
                            ""
                            if update_result
                            else f"Failed wrapper update {i + 1}",
                        )
                    )

                closed, close_duration = self.measure_time(remote_window.close)
                self.log_result(
                    TestResult(
                        "🗑️ Remote Window Close",
                        closed,
                        close_duration,
                        "" if closed else "Failed to close remote window",
                    )
                )

                if closed:
                    self._mark_window_closed(window_id)

                self.log_result(
                    TestResult(
                        "🎪 Remote Window Wrapper Complete",
                        True,
                        time.perf_counter() - wrapper_start_time,
                    )
                )
            else:
                self.log_result(
                    TestResult(
                        "Remote Window Wrapper",
                        False,
                        0.0,
                        "Failed to create window for wrapper test",
                    )
                )

        except Exception as e:
            self.log_result(TestResult("Remote Window Wrapper", False, 0.0, str(e)))

    def cleanup_remaining_windows(self) -> None:
        """Clean up any remaining windows."""
        if not self.active_windows:
            return

        logger.info("🧹 Cleaning up %s remaining windows...", len(self.active_windows))

        if not self.overlay_client.is_available():
            logger.warning(
                "Overlay server unavailable during cleanup; %s window(s) remain tracked: %s",
                len(self.active_windows),
                self.active_windows,
            )
            return

        for window_id in self.active_windows[:]:
            try:
                closed = self._close_tracked_window(window_id)
                if not closed:
                    logger.warning(
                        "Window %s remained tracked because close_window() returned False",
                        window_id,
                    )
                time.sleep(0.1)
            except Exception as e:
                logger.error("Failed to close window %s: %s", window_id, e)

        if self.active_windows:
            logger.warning(
                "Cleanup finished with %s tracked window(s) still open: %s",
                len(self.active_windows),
                self.active_windows,
            )

    def generate_report(self) -> None:
        """Generate and display a comprehensive test report."""
        if not self.results:
            logger.warning("No test results to report")
            return

        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.success)
        failed_tests = total_tests - passed_tests

        durations = [r.duration for r in self.results if r.duration > 0]
        avg_duration = statistics.mean(durations) if durations else 0
        total_duration = time.perf_counter() - self.test_start_time

        print("\n" + "=" * 80)
        print("🧪 STRESS TEST REPORT")
        print("=" * 80)
        print(f"📊 Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests} ({passed_tests / total_tests:.1%})")
        print(f"❌ Failed: {failed_tests} ({failed_tests / total_tests:.1%})")
        print(f"⏱️ Total Duration: {total_duration:.2f}s")
        print(f"📈 Average Test Duration: {avg_duration:.3f}s")

        if durations:
            print(f"⚡ Fastest Test: {min(durations):.3f}s")
            print(f"🐌 Slowest Test: {max(durations):.3f}s")

        if self.active_windows:
            print(f"⚠️ Remaining tracked windows: {len(self.active_windows)}")
            print(f"   IDs: {', '.join(str(window_id) for window_id in self.active_windows)}")

        # Show failed tests
        failed_results = [r for r in self.results if not r.success]
        if failed_results:
            print(f"\n❌ FAILED TESTS ({len(failed_results)}):")
            print("-" * 40)
            for result in failed_results:
                print(f"  • {result.test_name}: {result.error_message}")

        # Show performance metrics
        performance_results = [
            r
            for r in self.results
            if "rapid" in r.test_name.lower() or "concurrent" in r.test_name.lower()
        ]
        if performance_results:
            print("\n⚡ PERFORMANCE METRICS:")
            print("-" * 40)
            for result in performance_results:
                if result.additional_data:
                    if "requests_per_second" in result.additional_data:
                        rps = result.additional_data["requests_per_second"]
                        print(f"  • {result.test_name}: {rps:.1f} requests/second")
                    if "success_rate" in result.additional_data:
                        rate = result.additional_data["success_rate"]
                        print(f"    Success Rate: {rate:.1%}")

        print("=" * 80)

    def run_all_tests(
        self,
        countdown_count: int = 5,
        highlight_count: int = 5,
        elapsed_count: int = 3,
        qr_duration: int = 1,
        break_duration: int = 5,
        rapid_request_count: int = 20,
    ) -> None:
        """Run the complete stress test suite."""
        self.test_start_time = time.perf_counter()

        print("🚀 Starting overlay server stress test suite")
        print("=" * 60)

        try:
            # Basic functionality tests
            self.test_basic_connectivity()
            self.test_countdown_windows(countdown_count)
            self.test_qrcode_window(qr_duration)
            self.test_highlight_windows(highlight_count)
            self.test_elapsed_time_windows(elapsed_count)
            self.test_break_functionality(break_duration)
            self.test_remote_elapsed_time_window()

            # Stress tests
            self.test_rapid_requests(rapid_request_count)

            # Edge case tests
            self.test_edge_cases()

        except KeyboardInterrupt:
            logger.warning("Test suite interrupted by user")
        except Exception as e:
            logger.error(f"Unexpected error during testing: {e}")
        finally:
            # Cleanup
            self.cleanup_remaining_windows()

            # Generate report
            self.generate_report()


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the stress test client."""
    parser = argparse.ArgumentParser(
        description="Stress test or showcase the overlays server."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run a short scripted showcase instead of the full stress suite.",
    )
    parser.add_argument(
        "--demo-url",
        default=DEMO_REPO_URL,
        help="URL to encode in the showcase QR scene.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Run immediately without an interactive confirmation prompt.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5000,
        help="Named-pipe connection timeout in milliseconds.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducible request/message selection.",
    )
    parser.add_argument(
        "--rapid-request-count",
        type=int,
        default=20,
        help="Number of rapid requests to issue during the rapid test.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the stress test client."""
    args = build_parser().parse_args(argv)
    configure_logging(logging.WARNING if args.demo else logging.INFO)

    if args.demo:
        print("🎬 Overlay Showcase Demo")
        print("=" * 50)
        print("A short scripted showcase for screencasts and README gifs.")
    else:
        print("🧪 Overlay Server Stress Test Client")
        print("=" * 50)
        print("This will stress test the Rust overlay server.")
    print("Make sure the overlay server is running.")
    if not args.demo and args.seed is not None:
        print(f"Using random seed: {args.seed}")
    print("=" * 50)
    print()

    if not args.yes:
        prompt = (
            "Press Enter to start the showcase (or 'q' to quit): "
            if args.demo
            else "Press Enter to start the stress test (or 'q' to quit): "
        )
        response = input(prompt).strip().lower()
        if response == "q":
            print("Test cancelled.")
            return 0

    # Create and run stress test
    stress_tester = StressTestClient(
        timeout=args.timeout,
        seed=None if args.demo else args.seed,
    )
    if args.demo:
        stress_tester.run_demo(repo_url=args.demo_url)
    else:
        stress_tester.run_all_tests(rapid_request_count=args.rapid_request_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
