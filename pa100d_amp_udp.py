"""
================================================================================
RS-928 / PA100D Terminal Monitor & Control (with UDP Remote Bridge)
================================================================================
Summary:
    A real-time Python terminal interface for the RS-928 (JUMA PA100D clone)
    RF Power Amplifier. Features auto-reconnect, dynamic single-line status
    updates, instant hotkey response, AND UDP telemetry bridge matching
    the IW7DLE / Thetis protocol structure. (returned paramaters may differ...)

Keyboard Shortcuts:
    - O / o   : OPERATE Mode
    - S / s   : STANDBY Mode
    - 1 - 4   : Gain Levels (G1 -6dB to G4 0dB)
    - C / c   : Clear Alarm & Resume OPER
    - Q / q   : Exit Script
================================================================================
"""

import json
import os
import socket
import sys
import time
import serial

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    import ctypes
    import msvcrt

    def enable_ansi_support():
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

    def get_key():
        if msvcrt.kbhit():
            return msvcrt.getch().decode("utf-8", errors="ignore").lower()
        return None

else:
    import select
    import termios
    import tty

    def enable_ansi_support():
        pass

    def get_key():
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1).lower()
        return None

enable_ansi_support()

# Configuration
SERIAL_PORT = "COM9" if IS_WINDOWS else "/dev/ttyUSB0"
BAUD_RATE = 115200

TIMEOUT_SECONDS = 3.0

# Network Configuration for Thetis
UDP_BROADCAST_IP = "255.255.255.255"  # Broadcasts telemetry to subnet
UDP_TX_PORT = 9000                   # Port where Thetis container receives telemetry
UDP_RX_PORT = 10000                  # Port where Pi listens for commands from Thetis

# ANSI Control Sequences
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_GRAY = "\033[90m"
COLOR_RESET = "\033[0m"
CLEAR_LINE = "\033[K"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"

BAND_MAP = {
    "0": "error", "1": "160M", "2": "80M", "3": "40m",
    "4": "30m",  "5": "20m",  "6": "17m", "7": "15M",
    "8": "12M",  "9": "10M",
}

GAIN_MAP = {"1": "-6dB", "2": "-4dB", "3": "-2dB", "4": "0dB"}

def parse_pa100d_frame(raw_str):
    parts = [p.strip() for p in raw_str.split(":")]
    if len(parts) >= 13:
        raw_mode = parts[0].strip().upper()
        op_mode = "OPER" if raw_mode == "O" else "STBY"
        amp_state = 1 if raw_mode.strip() == "O" else 0

        alarm_raw = parts[12]
        alarm_disp = f"{COLOR_GREEN}0{COLOR_RESET}" if alarm_raw == "0" else f"{COLOR_RED}{alarm_raw}{COLOR_RESET}"
        alarm_state = 0 if alarm_raw == "0" else int(alarm_raw) if alarm_raw.isdigit() else 1

        band_idx = parts[4]
        band_str = BAND_MAP.get(band_idx, f"B{band_idx}")
        band_disp = f"{COLOR_RED}ERR{COLOR_RESET}" if band_str == "error" else band_str

        gain_idx = parts[5]
        gain_disp = GAIN_MAP.get(gain_idx, f"G{gain_idx}")
        attn_val = f"-{gain_idx}dB" if gain_idx in ["1", "2", "3", "4"] else "0dB"

        raw_swr = parts[6]
        try:
            swr_val = float(raw_swr)
            if swr_val <= 1.5:
                swr_disp = f"{COLOR_GREEN}{raw_swr}{COLOR_RESET}"
            elif swr_val <= 2.0:
                swr_disp = f"{COLOR_YELLOW}{raw_swr}{COLOR_RESET}"
            else:
                swr_disp = f"{COLOR_RED}{raw_swr}{COLOR_RESET}"
        except ValueError:
            swr_disp = raw_swr
            swr_val = 0.0

        volts_raw = parts[7]
        try:
            v_val = float(volts_raw)
            volts_disp = f"{COLOR_RED}{volts_raw}V{COLOR_RESET}" if v_val < 12.0 else f"{volts_raw}V"
        except ValueError:
            volts_disp = f"{volts_raw}V"
            v_val = 0.0

        amps_raw = parts[8]
        pwr_raw = parts[9]
        temp_raw = parts[10]
        fan_flag = parts[11]
        fan_state = 1 if fan_flag != "0" else 0

        return {
            "op_mode": op_mode,
            "ampState": amp_state,
            "alarm": alarm_disp,
            "alarm_raw": alarm_raw,
            "alarmState": alarm_state,
            "band": band_disp,
            "band_raw": band_idx,
            "bandSelect": band_str,
            "gain": gain_disp,
            "gain_raw": gain_idx,
            "attn": attn_val,
            "pwr": pwr_raw,
            "swr": swr_disp,
            "swr_raw": raw_swr,
            "temp": temp_raw,
            "volts": volts_disp,
            "volts_raw": volts_raw,
            "amps": amps_raw,
            "fanState": fan_state,
            "raw_frame": raw_str,
        }
    return None

def main():
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()

    old_settings = None
    if not IS_WINDOWS:
        try:
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except Exception:
            pass

    print(f"\n=== PA-100D / RS-928 Amp Monitor/Control + UDP Bridge ===")
    print(f"[*] Port: {SERIAL_PORT} @ {BAUD_RATE}")
    print(f"[*] UDP Output: {UDP_BROADCAST_IP}:{UDP_TX_PORT} | UDP Command RX: Port {UDP_RX_PORT}")
    print("[*] Hotkeys: [O]per [S]tby [1-4]Gain [C]lear Alarm [Q]uit\n")

    # Socket Initialization
    udp_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    udp_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_rx.setblocking(False)
    udp_rx.bind(("0.0.0.0", UDP_RX_PORT))

    ser = None
    buffer = ""
    last_poll = 0
    last_packet_time = time.time()

    def send_cmd(cmd_str):
        if ser and ser.is_open:
            ser.write(f"{cmd_str}\r\n".encode("utf-8"))
            ser.flush()

    try:
        while True:
            # 1. Hotkey Handling (Local SSH Session)
            key = get_key()
            if key:
                if key == "q":
                    sys.stdout.write(f"\n{SHOW_CURSOR}[*] Exiting...\n")
                    sys.stdout.flush()
                    break
                elif key == "o":
                    send_cmd("=O")
                elif key == "s":
                    send_cmd("=S")
                elif key == "c":
                    send_cmd("=C")
                    time.sleep(0.05)
                    send_cmd("=O")
                elif key in ["1", "2", "3", "4"]:
                    send_cmd(f"=G{key}")

            # 2. Remote UDP Command Handling (From Thetis Buttons)
            try:
                data, addr = udp_rx.recvfrom(1024)
                raw_cmd = data.decode("utf-8", errors="ignore").strip()

                if raw_cmd:
                    # Parse JSON if wrapped, otherwise handle direct string commands
                    try:
                        payload = json.loads(raw_cmd)
                        cmd = str(payload.get("cmd") or payload.get("command") or payload.get("state") or "").strip().upper()
                    except json.JSONDecodeError:
                        cmd = raw_cmd.upper()

                    # Process parsed action or relay JUMA text command
                    if cmd in ["OPER", "ON", "1"]:
                        send_cmd("=O")
                    elif cmd in ["STBY", "OFF", "0"]:
                        send_cmd("=S")
                    elif cmd == "CLEAR":
                        send_cmd("=C")
                        time.sleep(0.3)
                        send_cmd("=O")
                    elif cmd in ["G1", "G2", "G3", "G4"]:
                        send_cmd(f"={cmd}")
                    elif cmd.startswith("="):
                        send_cmd(cmd)

            except BlockingIOError:
                pass  # No UDP data received this cycle

            # 3. Connection & Polling Management
            if ser is None or not ser.is_open:
                sys.stdout.write(f"\r{COLOR_GRAY}[OFFLINE] Attempting connection to {SERIAL_PORT}...{COLOR_RESET}{CLEAR_LINE}")
                sys.stdout.flush()
                try:
                    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
                    sys.stdout.write(f"\r{COLOR_GREEN}[CONNECTED] PA100D Online{COLOR_RESET}{CLEAR_LINE}\n")
                    sys.stdout.flush()
                    last_packet_time = time.time()
                except Exception:
                    time.sleep(2.0)
                    continue

            # Dynamic Polling Interval: 0.4s when online, 3.0s when offline
            is_offline = (time.time() - last_packet_time) > TIMEOUT_SECONDS
            poll_interval = 3.0 if is_offline else 0.4

            if time.time() - last_poll > poll_interval:
                try:
                    ser.write(b"=R\r\n")
                    ser.flush()
                    last_poll = time.time()
                except serial.SerialException:
                    ser.close()
                    ser = None
                    continue

            # 4. Read & Render Telemetry + Broadcast JSON UDP
            try:
                if ser.in_waiting > 0:
                    raw_bytes = ser.read(ser.in_waiting)
                    buffer += raw_bytes.decode("utf-8", errors="ignore")

                    while "\n" in buffer or "\r" in buffer:
                        pos_n = buffer.find("\n")
                        pos_r = buffer.find("\r")
                        positions = [p for p in [pos_n, pos_r] if p != -1]
                        split_pos = min(positions)

                        line = buffer[:split_pos].strip()
                        buffer = buffer[split_pos + 1 :]

                        if line:
                            p = parse_pa100d_frame(line)
                            if p:
                                last_packet_time = time.time()

                                # Update Terminal UI
                                out = (
                                    f"[{p['op_mode']}] "
                                    f"Alm:{p['alarm']} | "
                                    f"Band:{p['band']} | "
                                    f"G:{p['gain']} | "
                                    f"P:{p['pwr']}W | "
                                    f"SWR:{p['swr']} | "
                                    f"T:{p['temp']}C | "
                                    f"{p['volts']} | "
                                    f"{p['amps']}A"
                                )
                                sys.stdout.write(f"\r{out}{CLEAR_LINE}")
                                sys.stdout.flush()

                                # Broadcast Telemetry JSON Payload to Thetis Container
                                json_payload = json.dumps({
                                    "id": "OWN3",
                                    "connState": "CONNECTED",
                                    "tempUnit": "C",
                                    "ampState":"ON" if p["op_mode"] == "OPER" else "OFF",
                                    "alarmState": p["alarmState"],
                                    "bandSelect": p["bandSelect"],
                                    "band": p["band_raw"],
                                    "attn": p["attn"],
                                    "gain": p["gain"],
                                    "fanState": p["fanState"],
                                    "volts": p["volts_raw"],
                                    "amps": p["amps"],
                                    "pwr": p["pwr"],
                                    "swr": p["swr_raw"],
                                    "temp": p["temp"],
                                    "raw": p["raw_frame"],
                                }).encode("utf-8")

                                udp_tx.sendto(json_payload, (UDP_BROADCAST_IP, UDP_TX_PORT))

                elif time.time() - last_packet_time > TIMEOUT_SECONDS:
                    off_msg = f"{COLOR_GRAY}[OFFLINE] PA100D Powered Off / Standby{COLOR_RESET}"
                    sys.stdout.write(f"\r{off_msg}{CLEAR_LINE}")
                    sys.stdout.flush()

            except serial.SerialException:
                ser.close()
                ser = None

            time.sleep(0.05)

    except KeyboardInterrupt:
        sys.stdout.write(f"\n{SHOW_CURSOR}[*] Stopped by user.\n")
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()
        if not IS_WINDOWS and old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        if ser and ser.is_open:
            ser.close()
        udp_tx.close()
        udp_rx.close()

if __name__ == "__main__":
    main()
