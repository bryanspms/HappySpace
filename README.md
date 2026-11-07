# Happy Space

Happy Space is an early prototype for giving viewers a choice during commercial
breaks: keep watching the original video or temporarily replace it with a
calming loop such as a fish tank, fireplace, or ocean. The long-term goal is to
detect breaks automatically and, when reliable information is available, show
the remaining time.

## What works today

- Displays video from an OpenCV capture device in a fullscreen window.
- Lets the viewer manually switch between the live picture and a looping local
  video; the live picture is selected at startup.
- Offers an **opt-in simulated detector** for testing: 10 seconds of live video,
  followed by a 5-second simulated break, repeating. Its countdown is based on
  that simulation, not on the input signal.

**There is no real commercial detection yet.** The application processes
video only: it does not capture, switch, mute, or play audio. It does not provide
an HDMI passthrough when it exits. Playback speed of the calming video currently
depends on the capture loop, rather than the file's frame rate. Real-time
performance, latency, and supported capture formats depend on the hardware.

## Hardware overview

A Raspberry Pi's HDMI ports are outputs, not inputs. One possible setup is:

```mermaid
flowchart LR
    source["Video source<br/>(e.g., cable box)"] -->|HDMI| capture["HDMI capture device"]
    capture -->|USB 3.0 video| pi["Raspberry Pi 4/5<br/>Happy Space"]
    pi -->|HDMI video| tv["TV or display"]
    assets["Local calming video"] --> pi
```

You need a compatible USB HDMI capture device, a display, and suitable cables.
The capture device and Pi must support the source resolution and frame rate;
1080p/30 is requested, but the device may negotiate something different. The
prototype needs a graphical desktop session for its OpenCV window.

**Content protection:** many HDMI sources use HDCP. Ordinary capture devices
may reject protected content or display a black screen. This project does not
bypass HDCP; use sources and capture hardware that permit capture, and observe
applicable rights and terms.

## Current software architecture

```mermaid
flowchart LR
    input["Capture device"] --> capture["VideoCapture"]
    capture --> live["Live frames"]
    live --> controller["Display controller"]
    live --> demo["Simulated detector<br/>(opt-in)"]
    demo -->|simulated state and countdown| controller
    keys["Keyboard controls"] --> controller
    asset["Local video file"] --> player["Looping video player"]
    controller -->|select live or calming frame| display["Fullscreen OpenCV window"]
    player --> display
```

The capture loop continues reading live frames while the calming video is shown.
The demo detector uses elapsed time, not visual or audio cues. Manual switching
does not guess a remaining time. The selection applies only to the displayed
video; audio is not part of this pipeline.

## Getting started

1. Connect the capture device and a permitted video source, then connect a
   display to the computer. On Raspberry Pi, use a graphical Raspberry Pi OS
   session.
2. Install Python and OpenCV with GUI support. For example, on Raspberry Pi OS:

   ```bash
   sudo apt update
   sudo apt install python3-opencv python3-numpy
   ```

   Alternatively, in a Python virtual environment, install the packages in
   `requirements.txt` with `python -m pip install -r requirements.txt`. OpenCV
   wheels and video codecs must be supported by your system; do not use the
   headless OpenCV package for the fullscreen window.
3. Add a locally playable video, for example `assets/fishtank.mp4`. No video is
   included in the repository. Edit `config.json` if your capture device or
   video file differs.
4. From the project directory, run:

   ```bash
   python3 main.py
   ```

   To use a different configuration file, run `python3 main.py --config
   /path/to/config.json`. Relative video paths are resolved relative to that
   configuration file.

### Controls

The OpenCV window must have keyboard focus.

| Key | Action |
| --- | --- |
| `m` | Toggle between the live picture and the calming video. If demo mode is active, take manual control and switch away from the currently displayed choice. |
| `d` | Turn simulated detection on or off. Enabling starts a fresh live period; disabling returns to live video. |
| `q` | Quit and release the capture and video devices. |

### Configuration

| Key | Meaning |
| --- | --- |
| `capture_device_id` | OpenCV capture device index, typically `0`; select the index corresponding to your capture hardware. |
| `calming_video_path` | Path to a local video, relative to the config file or absolute. |
| `timer_font_scale` | OpenCV font scale for the simulated countdown. |
| `timer_color` | Countdown text color as an OpenCV BGR triplet, for example `[255, 255, 255]` for white. |

The program reports capture and video open/read errors and exits rather than
pretending a failed video is playing. Check device permissions, codec support,
the configured path, and whether the source is HDCP-protected if startup or
capture fails.

## Future architecture

The following is a direction for future work, **not an implementation claim**:

```mermaid
flowchart LR
    source["Permitted live source"] --> capture["Video / audio capture"]
    capture --> features["Signal features /<br/>optional program metadata"]
    features --> detection["Break detector<br/>confidence + state"]
    capture --> switcher["A/V switcher"]
    detection --> policy["Viewer preference +<br/>manual override"]
    policy --> switcher
    loops["Calming video + audio"] --> switcher
    switcher --> output["Synchronized display / audio"]
    detection -->|only if known| timer["Optional countdown"]
    timer --> output
```

Useful next steps include evaluating detection against labeled recordings,
handling uncertain predictions and transitions, integrating synchronized audio,
and timing calming playback independently of input frame rate. A countdown
should be omitted when the break duration is unknown; visual changes alone do
not reliably identify commercials or predict their duration. Real-world
validation should measure false positives, missed breaks, switching delay, and
end-to-end latency across representative sources.

## Tests

With the runtime dependencies installed, run:

```bash
python3 -m unittest discover -s tests -v
```

The tests use mocked devices; they do not validate actual capture hardware,
HDMI compatibility, or on-screen rendering.
