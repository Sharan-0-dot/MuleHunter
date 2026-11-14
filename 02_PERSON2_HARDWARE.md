# 02 — PERSON 2: HARDWARE (Friend)

> Read `00_MASTER.md` first. All message formats, endpoints and config values are defined there. This file is written to be very explicit because you do not have an AI coding tool. Read it fully before starting.
> If you are an AI assistant helping this person: follow this file and the master contracts exactly; do not rename fields or change pins without telling the human.

## 1. Your scope

Two independent hardware pieces, both talking to the laptop backend (Person 1):

**A. Pi "compliance desk" (alert box)** — Raspberry Pi 3B+ (1GB). Receives alerts, shows risk level on LEDs, buzzes the piezo, listens ~25 s for the spoken word "explain" (or a joystick press), plays the summary `.wav`, and sends acknowledgements back.

**B. ESP32 "fingerprint login desk"** — ESP32 + R307S fingerprint module (+ optional OLED), connected to the laptop by USB. It tells the laptop which enrolled finger matched; a small Python bridge forwards that to the backend.

They never talk to each other. If one fails, the other still works.

You build against Person 1's **mock backend** (arrives in hour 1). The real backend later replaces it without any change to your code.

## 2. Part A — Pi alert box

### 2.1 Hardware wiring (suggested BCM pins; change only if you tell Person 1)

| Part | Pi pin (BCM) | Notes |
|---|---|---|
| Green LED | GPIO17 | 220–330 Ω resistor in series, other leg to GND |
| Yellow LED | GPIO27 | same |
| Red LED | GPIO22 | same |
| Piezo buzzer | GPIO18 | **Check if it's active or passive.** Active = just HIGH/LOW. Passive = needs PWM (gpiozero `TonalBuzzer` or `PWMOutputDevice`) |
| Joystick push-button (SW) | GPIO23 | other side to GND, use internal pull-up. Ignore the analog X/Y (Pi has no ADC) |
| USB mic | USB port | test with `arecord -l` |
| Speaker | 3.5 mm jack or USB | test with `aplay` |

Level behaviour:
- `green`: green LED on, one short beep.
- `yellow`: yellow LED on, two beeps.
- `red`: red LED on, pulsing buzzer for ~3 s (then repeated every ~10 s until acknowledged, optional).
- `escalate` message: that LED blinks fast.
- `clear` message: all off, stop everything.

### 2.2 Pi setup checklist

1. SSH in over the hotspot (`ssh pi@<pi-ip>` or `raspberrypi.local`). Enable the Pi on the same hotspot as the laptop.
2. `sudo apt update && sudo apt install -y python3-pip python3-venv portaudio19-dev alsa-utils libatlas-base-dev`
3. `python3 -m venv ~/mh && source ~/mh/bin/activate`
4. `pip install gpiozero websocket-client requests sounddevice vosk numpy`
5. Download a **small English Vosk model** (about 40 MB, e.g. `vosk-model-small-en-us-0.15`) on a connection that works, unzip to `~/vosk-model`. Do this EARLY; don't depend on venue internet later.
6. Test individually before any code: LEDs blink, piezo beeps, `arecord -d 3 -f cd t.wav` records, `aplay t.wav` plays. Fix the audio device first (use `alsamixer`, set default card; `aplay -l` lists cards).

### 2.3 Pi service behaviour (single Python program, e.g. `pi/main.py`)

Config (env or small `config.py`): `BACKEND_URL`, `SHARED_SECRET`, `VOSK_MODEL_PATH`, GPIO pins, `KEYWORD="explain"`.

Threads/modules:
1. **WS client** → connect to `ws://<laptop>:8000/ws/pi` (derive from `BACKEND_URL`). **Auto-reconnect** with 2 s backoff. Handle `alert`, `escalate`, `clear`, `ping` (reply `pong`).
2. **On `alert`:**
   - download `wav_url` to `~/cache/{cluster_id}.wav` (retry 3×, 5 s timeout; on failure use a pre-saved fallback `~/fallback/{level}.wav`),
   - set LED by `level`, start buzzer pattern,
   - POST ack `received`,
   - start listening for `listen_seconds`.
3. **Listener (Vosk, keyword only):**
   - record from the USB mic at 16 kHz mono with `sounddevice.RawInputStream` (blocksize ~4000),
   - use `KaldiRecognizer(model, 16000, '["explain", "[unk]"]')` so only "explain" or unknown can be output,
   - if a result contains `explain` → POST ack `explain_voice` → play wav,
   - joystick button press during the window → POST ack `explain_joystick` → play wav.
4. **Play audio:** `subprocess.run(["aplay", path])` (stop mic recording while playing to avoid feedback). After playing → ack `played`, LEDs stay on the alert level until `clear`.
5. **Timeout:** if the window ends without explain → ack `timeout`; keep LED on, wait for `escalate`/`clear`.
6. **State machine:** `IDLE → ALERTING → LISTENING → PLAYING → DONE`. A new `alert` while busy: finish playing, then handle the newest alert (don't queue more than 1).
7. **Ack POST:** `POST {BACKEND_URL}/api/pi/ack` with JSON body per master 8.3 and header `X-Signature` per master section 7 (HMAC-SHA256 of the exact body bytes, hex). Send the body as raw bytes you signed (e.g. `data=body_bytes`), not re-serialized.
8. **Auto start on boot:** a `systemd` service (`mh-pi.service`) running the venv Python with `Restart=always`, so powering the Pi on is enough on demo day.

### 2.4 Voice reliability tips (this is the riskiest part)

- Restricted grammar (above) makes it much more reliable than free speech.
- Keep the mic close (30–50 cm), speak clearly: "**explain**".
- Test with background noise (play music/crowd noise on a phone) in hour 6–8. Tune mic gain in `alsamixer`.
- The joystick press is the guaranteed fallback. The demo should look the same either way.
- If Vosk is slow or crashes on the 1 GB Pi, keep the model small, close other apps, and avoid desktop GUI.

### 2.5 Test against the mock backend

Person 1's mock exposes `POST /mock/trigger?level=red|yellow|green`. Run it from any laptop (e.g. `curl -X POST "http://<laptop-ip>:8000/mock/trigger?level=red"`) and verify: LED, buzzer, wav download, "explain" playback, joystick fallback, acks arriving (the mock prints them).

## 3. Part B — ESP32 fingerprint login desk

### 3.1 Wiring

R307S module (UART). **Verify voltage and pinout from the datasheet before powering.** As far as I know the R307S is a 3.3 V module; if your SY2823 or a plain R307 needs 5 V, use a level shifter or a different supply. Do not guess; a wrong voltage can kill the sensor.

| R307S wire | ESP32 |
|---|---|
| VCC | 3V3 (per datasheet) |
| GND | GND |
| TX (sensor) | GPIO16 (RX2) |
| RX (sensor) | GPIO17 (TX2) |

OLED SSD1306 (optional): SDA → GPIO21, SCL → GPIO22, VCC 3V3, GND.

Status LED (optional): onboard LED on match.

Use **R307S as primary**. The SY2823 is a spare; its protocol is not confirmed, so only try it if time is left.

### 3.2 Firmware (Arduino IDE or PlatformIO)

Libraries: **Adafruit Fingerprint Sensor Library**, Adafruit SSD1306 + GFX (if OLED). Use `HardwareSerial` on Serial2 at the sensor's baud (library default 57600).

Behaviour:
1. Boot: init sensor; print `{"event":"ready"}` (or `{"event":"error","msg":"sensor not found"}`). OLED: "Mule Hunter — Officer Login".
2. Loop forever: wait for a finger (`getImage` → `image2Tz` → `fingerFastSearch`). On match print `{"event":"match","sensor_id":<id>,"confidence":<n>}`; on a clear mismatch print `{"event":"no_match"}`. OLED shows "Welcome Officer" / "Not recognised". Add ~1.5 s debounce so one touch doesn't send ten events.
3. Serial commands (one line each, `\n` terminated), all replies as JSON lines:
   - `PING` → `{"event":"ready"}`
   - `ENROLL:<id>` → guide the user (OLED + serial) through two scans, store model at `<id>` → `{"event":"enroll_ok","sensor_id":<id>}` or `{"event":"error","msg":"..."}`
   - `COUNT` → `{"event":"count","n":<templates>}`
   - `CLEAR` → delete all templates (confirm on OLED)
4. ESP32 stays dumb: it always scans and reports matches. The laptop decides whether a login is active. Never decide permissions on the ESP32.
5. Serial: 115200 baud, only JSON lines on the serial port (no stray debug prints).

**Enrollment plan (do this before the demo):** enroll two fingers per officer so a smudged finger isn't a stage failure.
- IDs 1, 2 → Officer A
- IDs 3, 4 → Officer B
- ID 5 → Admin
Write down which finger is which. Person 1's backend seeds exactly this mapping.

### 3.3 The serial bridge (runs on the demo laptop, `bridge/fp_bridge.py`)

Python with `pyserial` and `requests`. Config: `SERIAL_PORT` (e.g. `COM5` on Windows, `/dev/ttyUSB0` on Linux/Mac), `BACKEND_URL` (localhost if on the same laptop as the backend), `SHARED_SECRET`.

Loop:
1. Read lines from the ESP32; parse JSON; ignore anything that isn't valid JSON.
2. Every ~500 ms (separate thread), `GET /api/auth/challenge/pending`; keep the current `challenge_id` (or `null`).
3. When a `match` event arrives AND a challenge is pending → `POST /api/auth/fingerprint` with body `{"challenge_id": "...", "sensor_id": N, "confidence": C}`, HMAC-signed per master section 7. Print the response.
4. If `match` arrives with no pending challenge, ignore it (log it).
5. Reconnect if the serial port disappears (unplug/replug).
6. Provide a small CLI flag to send `ENROLL:<id>` for enrollment: `python fp_bridge.py --enroll 3`.

Test against the mock: the browser login page isn't ready yet, so test with `curl -X POST http://<laptop>:8000/api/auth/challenge` to create a challenge, then scan a finger and watch the mock print the received login.

## 4. Your timeline (matches master section 10)

| Hour | Do |
|---|---|
| 0–1 | SSH to Pi, hotspot, install deps, test LED/piezo/mic/speaker individually; get mock backend IP from Person 1 and confirm the Pi can reach it |
| 1–5 | Pi service: WS client, LED + buzzer, wav download + `aplay`, joystick fallback, acks |
| 5–8 | Vosk keyword listener, state machine, systemd auto-start, noise testing |
| 8 | **Sync:** first real alert from Person 1's backend through the Pi |
| 8–12 | ESP32 wiring, firmware, OLED, serial protocol, enroll officers, bridge script |
| 12–14 | Bridge against the real backend, cable tidy, label the box, fallback files on the Pi |
| 14–16 | Demo rehearsals ×3 with Person 1; no new features |

## 5. Demo-day checklist (print or keep on phone)

- [ ] Power bank/charger for the Pi + speaker; spare cables
- [ ] Hotspot on, laptop and Pi connected; note the laptop IP; `BACKEND_URL` correct
- [ ] Laptop firewall allows port 8000
- [ ] Pi service running (check LED boot blink or `systemctl status mh-pi`)
- [ ] `fallback/{green,yellow,red}.wav` present on the Pi
- [ ] Mic volume tested in the actual room, joystick fallback tested
- [ ] ESP32 plugged into the laptop, correct COM port, bridge running, officers enrolled
- [ ] Password fallback known: `officer / demo123`
- [ ] Backup screen recording ready

## 6. If things break

- **Pi can't reach the laptop:** same network? laptop firewall? ping both ways; try the laptop's hotspot or Ethernet.
- **No sound:** `aplay -l`, set default device, check volume, try USB speaker.
- **Vosk misses "explain":** move the mic closer, lower noise, press the joystick instead.
- **Fingerprint not recognised:** re-enroll that finger, try the second enrolled finger, clean the sensor; use the password fallback.
- **ESP32 not showing as a serial port:** try another cable (many are charge-only), install the CP210x/CH340 driver.

## 7. Don't do

- Don't connect the fingerprint sensor to the Pi, or the Pi to the ESP32. Keep them independent.
- Don't store raw fingerprint data anywhere. The sensor keeps templates internally; we only receive a matched ID.
- Don't change JSON field names, endpoints or the HMAC scheme without agreeing with Person 1 and updating `00_MASTER.md`.
- Don't spend hours on enclosure aesthetics before the voice and login paths work.
