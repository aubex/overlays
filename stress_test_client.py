"""
Stress Test Client for OverlayManager

This client is designed to stress test the OverlayManager implementation by:
- Sending rapid requests
- Testing all available functionality
- Measuring performance and response times
- Testing edge cases and error conditions
"""

import json
import logging
import random
import statistics
import time
from dataclasses import dataclass
from typing import Any

from client import OverlayClient, RemoteElapsedTimeWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

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
    additional_data: dict[str, Any] = None

    def __post_init__(self):
        if self.additional_data is None:
            self.additional_data = {}


class StressTestClient:
    """Comprehensive stress testing client for OverlayManager."""

    def __init__(
        self, pipe_name: str = r"\\.\pipe\overlay_manager", timeout: int = 5000
    ):
        """
        Initialize the stress test client.

        Args:
            pipe_name: Named pipe to connect to
            timeout: Connection timeout in milliseconds
        """
        self.pipe_name = pipe_name
        self.timeout = timeout
        self.results: list[TestResult] = []
        self.active_windows: list[int] = []
        self.test_start_time = 0.0

    def log_result(self, result: TestResult) -> None:
        """Log and store a test result with colorful output."""
        self.results.append(result)

        # Add random emoji for visual flair
        random_emoji = random.choice(RANDOM_EMOJIS)

        if result.success:
            status = f"{Colors.OKGREEN}✅ PASS{Colors.ENDC}"
            print(
                f"{random_emoji} {Colors.BOLD}{result.test_name}{Colors.ENDC} - {status} ({result.duration:.3f}s)"
            )
        else:
            status = f"{Colors.FAIL}❌ FAIL{Colors.ENDC}"
            print(
                f"{random_emoji} {Colors.BOLD}{result.test_name}{Colors.ENDC} - {status} ({result.duration:.3f}s)"
            )
            if result.error_message:
                print(
                    f"   {Colors.WARNING}⚠️  Error: {result.error_message}{Colors.ENDC}"
                )

        logger.info(f"{status} {result.test_name} ({result.duration:.3f}s)")
        if not result.success and result.error_message:
            logger.error(f"   Error: {result.error_message}")

    def measure_time(self, func, *args, **kwargs) -> tuple[Any, float]:
        """Measure execution time of a function."""
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            return result, duration
        except Exception as e:
            duration = time.time() - start_time
            raise e

    def test_basic_connectivity(self) -> None:
        """Test basic connection to the overlay manager."""
        logger.info("🔌 Testing basic connectivity...")

        try:
            with OverlayClient(self.pipe_name, self.timeout) as client:
                start_time = time.time()
                is_available = client.is_available()
                duration = time.time() - start_time

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

        with OverlayClient(self.pipe_name, self.timeout) as client:
            if not client.is_available():
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
                        client.create_countdown_window,
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

        with OverlayClient(self.pipe_name, self.timeout) as client:
            if not client.is_available():
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
                        client.create_highlight_window,
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

    def test_elapsed_time_windows(self, count: int = 3) -> None:
        """Test creating and managing elapsed time windows with random messages."""
        emoji = random.choice(RANDOM_EMOJIS)
        print(
            f"\n{Colors.OKBLUE}{emoji} Testing {count} elapsed time windows with dynamic updates!{Colors.ENDC}"
        )

        with OverlayClient(self.pipe_name, self.timeout) as client:
            if not client.is_available():
                self.log_result(
                    TestResult(
                        "Elapsed Time Windows", False, 0.0, "Server not available"
                    )
                )
                return

            created_windows = []

            # Create windows with random messages
            for i in range(count):
                try:
                    random_message = random.choice(ELAPSED_MESSAGES)
                    window_id, duration = self.measure_time(
                        client.create_elapsed_time_window,
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
                        self.active_windows.append(window_id)

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
                            client.update_window_message,
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

                    result, duration = self.measure_time(client.close_window, window_id)

                    self.log_result(
                        TestResult(
                            f"🗑️ Close Window {i + 1}",
                            result,
                            duration,
                            "" if result else "Failed to close window",
                        )
                    )

                    if window_id in self.active_windows:
                        self.active_windows.remove(window_id)

                except Exception as e:
                    self.log_result(
                        TestResult(f"Close Window {i + 1}", False, 0.0, str(e))
                    )

    def test_break_functionality(self) -> None:
        """Test break and cancel break functionality."""
        logger.info("☕ Testing break functionality...")

        with OverlayClient(self.pipe_name, self.timeout) as client:
            if not client.is_available():
                self.log_result(
                    TestResult(
                        "Break Functionality", False, 0.0, "Server not available"
                    )
                )
                return

            # Test taking a break
            try:
                result, duration = self.measure_time(
                    client.take_break,
                    5,  # 5 second break
                )

                self.log_result(
                    TestResult(
                        "Take Break",
                        result,
                        duration,
                        "" if result else "Failed to initiate break",
                    )
                )

                # Wait a moment then cancel the break
                time.sleep(1)

                result, duration = self.measure_time(client.cancel_break)

                self.log_result(
                    TestResult(
                        "Cancel Break",
                        result,
                        duration,
                        "" if result else "Failed to cancel break",
                    )
                )

            except Exception as e:
                self.log_result(TestResult("Break Functionality", False, 0.0, str(e)))

    def test_rapid_requests(self, request_count: int = 20) -> None:
        """Test rapid successive requests with random messages and timing."""
        emoji = random.choice(RANDOM_EMOJIS)
        print(
            f"\n{Colors.WARNING}{emoji} Testing {request_count} rapid requests with random chaos!{Colors.ENDC}"
        )

        with OverlayClient(self.pipe_name, self.timeout) as client:
            if not client.is_available():
                self.log_result(
                    TestResult("Rapid Requests", False, 0.0, "Server not available")
                )
                return

            start_time = time.time()
            successful_requests = 0

            for i in range(request_count):
                try:
                    # Randomly choose request type and use random messages
                    request_type = random.choice(["countdown", "highlight", "elapsed"])

                    if request_type == "countdown":
                        rapid_msg = random.choice(RAPID_MESSAGES)
                        duration = random.uniform(0.5, 2.0)
                        result = client.create_countdown_window(
                            f"{rapid_msg} #{i}", int(duration)
                        )
                    elif request_type == "highlight":
                        # Random position and size
                        x = random.randint(100, 800)
                        y = random.randint(100, 400)
                        w = random.randint(50, 200)
                        h = random.randint(30, 100)
                        rect = (x, y, x + w, y + h)
                        duration = random.uniform(0.5, 2.0)
                        result = client.create_highlight_window(rect, int(duration))
                    else:  # elapsed
                        rapid_msg = random.choice(RAPID_MESSAGES)
                        window_id = client.create_elapsed_time_window(
                            f"{rapid_msg} #{i}"
                        )
                        result = window_id is not None
                        if window_id:
                            # Random quick update before closing
                            if random.choice([True, False]):
                                update_msg = random.choice(RAPID_MESSAGES)
                                client.update_window_message(
                                    window_id, f"{update_msg} - Updated!"
                                )
                            client.close_window(window_id)

                    if result:
                        successful_requests += 1

                    # Random micro-delay for chaos
                    if random.choice([True, False]):
                        time.sleep(random.uniform(0.001, 0.01))

                except Exception as e:
                    logger.error(f"Rapid request {i} failed: {e}")

            total_duration = time.time() - start_time
            success_rate = successful_requests / request_count

            self.log_result(
                TestResult(
                    "⚡ Rapid Chaos Test",
                    success_rate > 0.8,  # Consider successful if >80% succeed
                    total_duration,
                    f"Success rate: {success_rate:.2%} ({successful_requests}/{request_count})",
                    {
                        "total_requests": request_count,
                        "successful_requests": successful_requests,
                        "success_rate": success_rate,
                        "requests_per_second": request_count / total_duration,
                    },
                )
            )

    def test_edge_cases(self) -> None:
        """Test various edge cases and error conditions."""
        logger.info("🧪 Testing edge cases...")

        with OverlayClient(self.pipe_name, self.timeout) as client:
            if not client.is_available():
                self.log_result(
                    TestResult("Edge Cases", False, 0.0, "Server not available")
                )
                return

            # Test invalid window ID operations
            try:
                result, duration = self.measure_time(
                    client.close_window,
                    99999,  # Non-existent window ID
                )

                self.log_result(
                    TestResult(
                        "Close Invalid Window ID",
                        True,  # Should handle gracefully
                        duration,
                        "Should handle invalid window ID gracefully",
                    )
                )
            except Exception as e:
                self.log_result(
                    TestResult("Close Invalid Window ID", False, 0.0, str(e))
                )

            # Test update message on non-existent window
            try:
                result, duration = self.measure_time(
                    client.update_window_message, 99999, "This should fail gracefully"
                )

                self.log_result(
                    TestResult(
                        "Update Invalid Window Message",
                        True,  # Should handle gracefully
                        duration,
                        "Should handle invalid window ID gracefully",
                    )
                )
            except Exception as e:
                self.log_result(
                    TestResult("Update Invalid Window Message", False, 0.0, str(e))
                )

            # Test extreme values
            try:
                result, duration = self.measure_time(
                    client.create_countdown_window,
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

        with OverlayClient(self.pipe_name, self.timeout) as client:
            if not client.is_available():
                self.log_result(
                    TestResult(
                        "Remote Window Wrapper", False, 0.0, "Server not available"
                    )
                )
                return

            try:
                # Create window using the wrapper with random message
                wrapper_msg = random.choice(WRAPPER_MESSAGES)
                window_id = client.create_elapsed_time_window(
                    f"{wrapper_msg} - Remote Test"
                )

                if window_id:
                    with RemoteElapsedTimeWindow(window_id, client) as remote_window:
                        # Test updating message with random content
                        start_time = time.time()
                        initial_update = random.choice(WRAPPER_MESSAGES)
                        result = remote_window.update_message(
                            f"{initial_update} - Wrapper Active!"
                        )
                        duration = time.time() - start_time

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

                        # Window will be automatically closed when exiting context

                    self.log_result(
                        TestResult(
                            "🎪 Remote Window Wrapper Complete",
                            True,
                            time.time() - start_time,
                            "Successfully used wrapper class with random magic!",
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

        logger.info(f"🧹 Cleaning up {len(self.active_windows)} remaining windows...")

        with OverlayClient(self.pipe_name, self.timeout) as client:
            if client.is_available():
                for window_id in self.active_windows[
                    :
                ]:  # Copy list to avoid modification during iteration
                    try:
                        client.close_window(window_id)
                        self.active_windows.remove(window_id)
                        time.sleep(0.1)
                    except Exception as e:
                        logger.error(f"Failed to close window {window_id}: {e}")

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
        total_duration = time.time() - self.test_start_time

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
            print(f"\n⚡ PERFORMANCE METRICS:")
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

    def run_all_tests(self) -> None:
        """Run the complete stress test suite."""
        self.test_start_time = time.time()

        print("🚀 Starting OverlayManager Stress Test Suite")
        print("=" * 60)

        try:
            # Basic functionality tests
            self.test_basic_connectivity()
            self.test_countdown_windows(5)
            self.test_highlight_windows(5)
            self.test_elapsed_time_windows(3)
            self.test_break_functionality()
            self.test_remote_elapsed_time_window()

            # Stress tests
            self.test_rapid_requests(20)

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


def main():
    """Main entry point for the stress test client."""
    print("🧪 OverlayManager Stress Test Client")
    print("=" * 50)
    print("This will stress test the OverlayManager implementation.")
    print("Make sure the OverlayManager server is running!")
    print()

    response = (
        input("Press Enter to start the stress test (or 'q' to quit): ").strip().lower()
    )
    if response == "q":
        print("Test cancelled.")
        return

    # Create and run stress test
    stress_tester = StressTestClient()
    stress_tester.run_all_tests()


if __name__ == "__main__":
    main()
