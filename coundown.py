import queue
import re
import threading
import time
import tkinter as tk

WINDOW_TITLE = "OBS Countdown"
BACKGROUND = "black"
FOREGROUND = "white"
WARNING_FOREGROUND = "red"
FLASH_INTERVAL = 0.5
FONT = ("Arial", 120, "bold")
WINDOW_SIZE = "900x260"


class CountdownTimer:
    def __init__(self, root):
        self.root = root
        self.commands = queue.Queue()

        self.duration = 0.0
        self.remaining = 0.0
        self.end_time = None
        self.running = False
        self.visible = False
        self.warning_threshold = None

        root.title(WINDOW_TITLE)
        root.geometry(WINDOW_SIZE)
        root.configure(bg=BACKGROUND)
        # Behave like a normal application window. It does not need to stay
        # above the production/control applications for OBS to capture it.
        root.attributes("-topmost", False)

        self.label = tk.Label(
            root,
            text="",
            bg=BACKGROUND,
            fg=FOREGROUND,
            font=FONT,
            anchor="center",
        )
        self.label.pack(expand=True, fill="both")

        root.protocol("WM_DELETE_WINDOW", self.quit)

        # On Windows, OBS normally cannot capture a genuinely minimised window
        # because Windows stops rendering its contents. Treat the minimise
        # button as "send to back" instead: restore the window immediately,
        # then lower it behind other applications so OBS can keep capturing it.
        root.bind("<Unmap>", self.on_unmap)

        root.after(50, self.update)


    def on_unmap(self, event):
        # <Unmap> is generated when the top-level window is minimised. Check the
        # state after Windows has completed the minimise operation, then turn it
        # back into a rendered window and put it at the back of the stack.
        if event.widget is self.root:
            self.root.after(50, self.restore_behind_if_minimised)

    def restore_behind_if_minimised(self):
        try:
            if self.root.state() == "iconic":
                self.root.deiconify()
                self.root.lower()
        except tk.TclError:
            # The application may already be closing.
            pass

    def set_duration(self, seconds):
        self.duration = float(seconds)
        self.remaining = float(seconds)
        self.end_time = None
        self.running = False
        self.visible = True
        self.render()
        print(f"Loaded {format_time(self.remaining)} and displayed it. Type 'start' to begin.")

    def start(self):
        if self.running:
            print("Timer is already running.")
            return
        if self.remaining <= 0:
            if self.duration <= 0:
                print("Set a duration first, e.g. 5:00 or 90s.")
                return
            self.remaining = self.duration

        self.end_time = time.monotonic() + self.remaining
        self.running = True
        self.visible = True
        self.render()
        print("Started.")

    def stop(self):
        if not self.running:
            print("Timer is not running.")
            return

        self.remaining = max(0.0, self.end_time - time.monotonic())
        self.end_time = None
        self.running = False
        self.render()
        print(f"Stopped at {format_time(self.remaining)}.")

    def reset(self):
        self.running = False
        self.end_time = None
        self.remaining = self.duration
        self.visible = False
        self.render()
        print(f"Reset to {format_time(self.remaining)}; output hidden until start.")

    def blank(self):
        self.running = False
        self.end_time = None
        self.visible = False
        self.render()
        print("Output blanked.")

    def show(self):
        self.visible = True
        self.render()
        print("Output shown.")

    def set_warning(self, seconds):
        self.warning_threshold = float(seconds)
        self.render()
        print(f"Warning flash set for {format_time(self.warning_threshold)} remaining.")

    def clear_warning(self):
        self.warning_threshold = None
        self.label.config(fg=FOREGROUND)
        self.render()
        print("Warning flash disabled.")

    def status(self):
        state = "running" if self.running else "stopped"
        visibility = "visible" if self.visible else "hidden"
        warning = (
            f", warning at {format_time(self.warning_threshold)}"
            if self.warning_threshold is not None
            else ", no warning flash"
        )
        print(f"{format_time(self.current_remaining())} - {state}, {visibility}{warning}")

    def current_remaining(self):
        if self.running:
            return max(0.0, self.end_time - time.monotonic())
        return self.remaining

    def render(self):
        if not self.visible:
            self.label.config(text="", fg=FOREGROUND)
            return

        remaining = self.current_remaining()
        foreground = FOREGROUND

        if self.warning_threshold is not None:
            if remaining <= 0:
                # Once a warned timer reaches zero, leave 00:00 solid red.
                foreground = WARNING_FOREGROUND
            elif remaining <= self.warning_threshold:
                # Alternate red/white every FLASH_INTERVAL seconds. This gives a
                # clear flashing warning while keeping the timer readable in OBS.
                flash_phase = int(time.monotonic() / FLASH_INTERVAL) % 2
                foreground = WARNING_FOREGROUND if flash_phase == 0 else FOREGROUND

        self.label.config(text=format_time(remaining), fg=foreground)

    def update(self):
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            self.handle_command(command)

        if self.running:
            self.remaining = max(0.0, self.end_time - time.monotonic())
            if self.remaining <= 0:
                self.remaining = 0.0
                self.end_time = None
                self.running = False
                print("Timer finished.")
            self.render()

        self.root.after(50, self.update)

    def handle_command(self, command):
        text = command.strip().lower()
        if not text:
            return

        if text == "start":
            self.start()
        elif text == "stop":
            self.stop()
        elif text == "reset":
            self.reset()
        elif text == "blank":
            self.blank()
        elif text == "show":
            self.show()
        elif text == "status":
            self.status()
        elif text.startswith("warn ") or text.startswith("warning "):
            _, value = text.split(maxsplit=1)
            if value in {"off", "none", "disable"}:
                self.clear_warning()
            else:
                try:
                    self.set_warning(parse_duration(value))
                except ValueError as exc:
                    print(f"Invalid warning time: {exc}")
        elif text in {"warn", "warning"}:
            if self.warning_threshold is None:
                print("No warning flash is set. Example: warn 30s")
            else:
                print(f"Warning flash starts at {format_time(self.warning_threshold)} remaining.")
        elif text in {"quit", "exit"}:
            self.quit()
        elif text in {"help", "?"}:
            print_help()
        else:
            try:
                self.set_duration(parse_duration(text))
            except ValueError as exc:
                print(f"Invalid command: {exc}")

    def quit(self):
        self.root.quit()
        self.root.destroy()


def format_time(seconds):
    # Ceiling means a freshly-started 5-minute timer displays 05:00,
    # rather than immediately flicking to 04:59 because a few ms elapsed.
    total = max(0, int(seconds + 0.999999))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def parse_duration(text):
    text = text.strip().lower().replace(" ", "")

    # 5:30 = 5 minutes, 30 seconds
    # 1:02:30 = 1 hour, 2 minutes, 30 seconds
    if ":" in text:
        parts = text.split(":")
        if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
            raise ValueError("use M:SS or H:MM:SS")
        values = [int(p) for p in parts]
        if len(values) == 2:
            minutes, seconds = values
            if seconds >= 60:
                raise ValueError("seconds must be below 60 in M:SS")
            total = minutes * 60 + seconds
        else:
            hours, minutes, seconds = values
            if minutes >= 60 or seconds >= 60:
                raise ValueError("minutes and seconds must be below 60 in H:MM:SS")
            total = hours * 3600 + minutes * 60 + seconds
        if total <= 0:
            raise ValueError("duration must be greater than zero")
        return total

    # 5m, 90s, 1m30s, 1h2m30s
    match = re.fullmatch(
        r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?",
        text,
    )
    if match and any(group is not None for group in match.groups()):
        hours = float(match.group(1) or 0)
        minutes = float(match.group(2) or 0)
        seconds = float(match.group(3) or 0)
        total = hours * 3600 + minutes * 60 + seconds
        if total <= 0:
            raise ValueError("duration must be greater than zero")
        return total

    # A bare number means minutes, for fast production use: 5 -> five minutes.
    try:
        minutes = float(text)
    except ValueError:
        raise ValueError("enter a duration or type 'help'") from None

    if minutes <= 0:
        raise ValueError("duration must be greater than zero")
    return minutes * 60


def console_loop(command_queue):
    print_help()
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            command_queue.put("quit")
            return
        command_queue.put(line)
        if line.strip().lower() in {"quit", "exit"}:
            return


def print_help():
    print(
        """
Countdown controls
------------------
5          set 5 minutes
5:30       set 5 minutes 30 seconds
90s        set 90 seconds
1m30s      set 1 minute 30 seconds
1:02:30    set 1 hour 2 minutes 30 seconds

warn 30s   flash red from 30 seconds remaining
warn 1:00  flash red from 1 minute remaining
warn off   disable warning flash

start      start / resume
stop       pause
reset      reset to loaded duration and blank the output
blank      blank the output
show       show the current value without starting
status     print current status
help       show this help
quit       exit
""".strip()
    )


def main():
    root = tk.Tk()
    timer = CountdownTimer(root)

    thread = threading.Thread(
        target=console_loop,
        args=(timer.commands,),
        daemon=True,
    )
    thread.start()

    root.mainloop()


if __name__ == "__main__":
    main()
