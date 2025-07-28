import socket
import threading
import json
import os
import time
import sys

# ======================= CONFIG =========================
PORT = 5001
BROADCAST_PORT = 54545
BROADCAST_INTERVAL = 5
RECEIVE_DIR = os.path.expanduser("~/ReceivedFiles")
os.makedirs(RECEIVE_DIR, exist_ok=True)

online_peers = {}
MY_IP = socket.gethostbyname(socket.gethostname())

# ======================= PEER DISCOVERY =========================
def broadcast_presence():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    message = json.dumps({"name": socket.gethostname(), "port": PORT}).encode()
    while True:
        sock.sendto(message, ('<broadcast>', BROADCAST_PORT))
        time.sleep(BROADCAST_INTERVAL)

def listen_for_peers():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', BROADCAST_PORT))
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            info = json.loads(data.decode())
            ip = addr[0]
            if ip != MY_IP:
                online_peers[ip] = info["name"]
        except:
            pass

# ======================= FILE SENDER =========================
def send_file(filepath, ip):
    try:
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((ip, PORT))
            s.send(f"{filename}:{filesize}".encode())
            ack = s.recv(1024)
            if ack.decode() != "OK":
                return False

            sent = 0
            start_time = time.time()
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    s.sendall(chunk)
                    sent += len(chunk)

                    elapsed = time.time() - start_time + 0.01
                    speed = sent / 1024 / 1024 / elapsed
                    eta = (filesize - sent) / 1024 / 1024 / speed if speed > 0 else 0
                    percent = sent / filesize * 100

                    sys.stdout.write(f"\rSending to {ip}: {percent:.1f}% | {speed:.2f} MB/s | ETA: {eta:.1f}s")
                    sys.stdout.flush()

        print(f"\nFile sent to {ip}")
        return True

    except Exception as e:
        print(f"\nSend failed to {ip}: {e}")
        return False

# ======================= FILE RECEIVER =========================
def start_receiver():
    def handler():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(('', PORT))
            server.listen()
            while True:
                conn, addr = server.accept()
                threading.Thread(target=receive_file, args=(conn, addr), daemon=True).start()

    threading.Thread(target=handler, daemon=True).start()

def receive_file(conn, addr):
    with conn:
        try:
            meta = conn.recv(1024).decode()
            filename, filesize = meta.split(":")
            filesize = int(filesize)
            conn.send(b"OK")

            filepath = os.path.join(RECEIVE_DIR, filename)
            received = 0
            start = time.time()

            with open(filepath, 'wb') as f:
                while received < filesize:
                    chunk = conn.recv(min(4096, filesize - received))
                    if not chunk:
                        raise Exception("Connection lost")
                    f.write(chunk)
                    received += len(chunk)

                    elapsed = time.time() - start + 0.01
                    speed = received / 1024 / 1024 / elapsed
                    eta = (filesize - received) / 1024 / 1024 / speed if speed > 0 else 0
                    percent = received / filesize * 100

                    sys.stdout.write(f"\rReceiving from {addr[0]}: {percent:.1f}% | {speed:.2f} MB/s | ETA: {eta:.1f}s")
                    sys.stdout.flush()

            print(f"\nReceived file: {filename} from {addr[0]}")
        except Exception as e:
            print(f"\nFailed to receive file from {addr[0]}: {e}")
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    print("Incomplete file deleted.")
            except:
                pass

# ======================= FILE NAVIGATION & CLI =========================
def select_file_via_navigation():
    cwd = os.path.expanduser("~")
    while True:
        print(f"\nCurrent directory: {cwd}")
        items = os.listdir(cwd)
        for i, name in enumerate(items):
            path = os.path.join(cwd, name)
            suffix = "/" if os.path.isdir(path) else ""
            print(f"[{i}] {name}{suffix}")
        print("[..] Go up, [x] Cancel")
        choice = input("Choose index: ").strip()
        if choice.lower() == 'x':
            return None
        elif choice == '..':
            cwd = os.path.dirname(cwd)
        elif choice.isdigit():
            idx = int(choice)
            if 0 <= idx < len(items):
                selected = os.path.join(cwd, items[idx])
                if os.path.isdir(selected):
                    cwd = selected
                else:
                    return selected
        else:
            print("Invalid input.")

def print_menu():
    print("\nLAN File Sender")
    print("1. List Online Peers")
    print("2. Send File")
    print("3. Exit")

def run_cli():
    while True:
        print_menu()
        choice = input("Choose option: ").strip()
        if choice == '1':
            print("\nOnline Peers:")
            for ip, name in online_peers.items():
                print(f"{name} ({ip})")
        elif choice == '2':
            filepath = select_file_via_navigation()
            if not filepath or not os.path.isfile(filepath):
                print("Invalid or no file selected.")
                continue
            print("Choose recipient:")
            peers = list(online_peers.items())
            for i, (ip, name) in enumerate(peers):
                print(f"[{i}] {name} ({ip})")
            try:
                index = int(input("Enter recipient number: ").strip())
                ip = peers[index][0]
                send_file(filepath, ip)
            except:
                print("Invalid selection.")
        elif choice == '3':
            print("Exiting.")
            break
        else:
            print("Invalid choice.")

# ======================= MAIN =========================
if __name__ == '__main__':
    print("Starting LAN File Sender (headless)...")
    threading.Thread(target=broadcast_presence, daemon=True).start()
    threading.Thread(target=listen_for_peers, daemon=True).start()
    start_receiver()
    run_cli()
