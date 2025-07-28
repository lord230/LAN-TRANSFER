import tkinter as tk
from tkinter import filedialog, messagebox
import socket
import threading
import json
import os
import time

# ======================= CONFIG =========================
PORT = 5001
BROADCAST_PORT = 54545
BROADCAST_INTERVAL = 5
RECEIVE_DIR = os.path.expanduser("~/ReceivedFiles")
os.makedirs(RECEIVE_DIR, exist_ok=True)

online_peers = {}  # {ip: {"name": ..., "last_seen": ...}} the way it's supposed to be
MY_IP = socket.gethostbyname(socket.gethostname())

# =================== BROADCAST PRESENCE ===================
def broadcast_presence():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    message = json.dumps({"name": socket.gethostname(), "port": PORT}).encode()
    while True:
        sock.sendto(message, ('<broadcast>', BROADCAST_PORT))
        time.sleep(BROADCAST_INTERVAL)

# =================== LISTEN FOR PEERS ===================
def listen_for_peers():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', BROADCAST_PORT))
    while True:
        data, addr = sock.recvfrom(1024)
        try:
            info = json.loads(data.decode())
            ip = addr[0]
            if ip != MY_IP:
                online_peers[ip] = {"name": info["name"], "last_seen": time.time()}
        except:
            pass

def remove_stale_peers():
    while True:
        now = time.time()
        stale = [ip for ip, data in online_peers.items() if now - data["last_seen"] > 10]
        for ip in stale:
            del online_peers[ip]
        time.sleep(2)

# =================== SEND FILE ===================
def send_file(filepath, ip, progress_callback=None, stop_event=None):
    try:
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((ip, PORT))
            s.send(f"{filename}:{filesize}".encode())
            ack = s.recv(1024)
            if ack.decode() != "OK":
                return False

            start_time = time.time()
            sent = 0
            with open(filepath, 'rb') as f:
                while True:
                    if stop_event and stop_event.is_set():
                        print(f"->> Upload to {ip} stopped.")
                        return False

                    chunk = f.read(4096)
                    if not chunk:
                        break
                    s.sendall(chunk)
                    sent += len(chunk)
                    if progress_callback:
                        elapsed = time.time() - start_time + 0.01
                        speed = sent / 1024 / 1024 / elapsed
                        eta = (filesize - sent) / 1024 / 1024 / speed if speed else 0
                        progress_callback(ip, sent / filesize, speed, eta)

        print(f"->> File sent to {ip}")
        return True
    except Exception as e:
        print(f"Send failed to {ip}: {e}")
        return False

# =================== RECEIVE FILE ===================
def start_receiver():
    def handler():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(('', PORT))
            server.listen()
            while True:
                conn, addr = server.accept()
                stop_event = threading.Event()
                threading.Thread(target=receive_file, args=(conn, addr, stop_event), daemon=True).start()
    threading.Thread(target=handler, daemon=True).start()

def receive_file(conn, addr, stop_event=None):
    with conn:
        meta = conn.recv(1024).decode()
        filename, filesize = meta.split(":")
        filesize = int(filesize)
        conn.send(b"OK")

        filepath = os.path.join(RECEIVE_DIR, filename)
        received = 0
        start = time.time()

        try:
            with open(filepath, 'wb') as f:
                while received < filesize:
                    if stop_event and stop_event.is_set():
                        print(f"->> Download from {addr[0]} stopped.")
                        return
                    chunk = conn.recv(min(4096, filesize - received))
                    if not chunk:
                        raise Exception("Connection lost")
                    f.write(chunk)
                    received += len(chunk)

                    percent = received / filesize
                    elapsed = time.time() - start + 0.01
                    speed = received / 1024 / 1024 / elapsed
                    eta = (filesize - received) / 1024 / 1024 / speed if speed else 0

                    label = app.status_labels.get(addr[0])
                    text = f"{addr[0]}: Downloading {filename} | {percent*100:.1f}% | {speed:.2f} MB/s | ETA: {eta:.1f}s"
                    if label:
                        def update_gui_safe(l, t):
                            if l.winfo_exists():
                                l.config(text=t, fg="white")
                        label.after(0, update_gui_safe, label, text)


        except Exception as e:
            print(f"->> Failed to receive complete file from {addr[0]}: {e}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return

        print(f"->> Received file: {filename} from {addr[0]}")
        label = app.status_labels.get(addr[0])
        if label and label.winfo_exists():
            label.after(0, lambda l=label: l.config(text=f"{addr[0]}: <><> Complete <><>", fg="green"))

# =================== GUI APP ===================
class FileSenderApp:
    def __init__(self, master):
        self.master = master
        self.master.title("LAN File Sender")
        self.master.configure(bg="#1e1e1e")
        self.file_path = None
        self.master.geometry("450x580")
        self.status_labels = {}
        self.active_transfers = {}

        tk.Label(master, text="LAN File Sender", font=("Segoe UI", 18, "bold"), bg="#1e1e1e", fg="white").pack(pady=10)
        tk.Label(master, text="Select a file to send:", bg="#1e1e1e", fg="white", font=("Segoe UI", 11)).pack(pady=5)

        tk.Button(master, text="Browse", command=self.choose_file, font=("Segoe UI", 11, "bold"),
                  bg="#007acc", fg="black", relief=tk.FLAT, padx=15, pady=5).pack()

        self.file_label = tk.Label(master, text="No file selected", fg="gray", bg="#1e1e1e", font=("Segoe UI", 10))
        self.file_label.pack(pady=5)

        tk.Label(master, text="Online Peers:", bg="#1e1e1e", fg="white", font=("Segoe UI", 11)).pack(pady=5)

        self.peers_frame = tk.Frame(master, bg="#1e1e1e")
        self.peers_frame.pack(pady=5)
        self.peers_listbox = tk.Listbox(self.peers_frame, selectmode=tk.MULTIPLE, width=50, height=8,
                                        bg="#2d2d2d", fg="white", font=("Segoe UI", 10))
        self.peers_listbox.grid(row=0, column=0, padx=10)

        self.status_frame = tk.Frame(master, bg="#1e1e1e")
        self.status_frame.pack(pady=10)

        tk.Button(master, text="Refresh Peers", command=self.update_peer_list,
                  font=("Segoe UI", 11, "bold"), bg="#444", fg="black", relief=tk.FLAT, padx=15, pady=5).pack(pady=5)

        tk.Button(master, text="Send File", command=self.send_to_selected,
                  font=("Segoe UI", 11, "bold"), bg="#28a745", fg="black", relief=tk.FLAT, padx=15, pady=5).pack(pady=10)

        tk.Button(master, text="Stop Transfers", command=self.stop_transfers,
                  font=("Segoe UI", 11, "bold"), bg="#dc3545", fg="black", relief=tk.FLAT, padx=15, pady=5).pack(pady=5)

        self.update_peer_list_periodically()

    def choose_file(self):
        path = filedialog.askopenfilename()
        if path:
            self.file_path = path
            self.file_label.config(text=os.path.basename(path), fg="white")

    def update_peer_list(self):
        selected_ips = set()
        for i in self.peers_listbox.curselection():
            entry = self.peers_listbox.get(i)
            ip = entry.split('(')[-1].strip(')')
            selected_ips.add(ip)

        self.peers_listbox.delete(0, tk.END)
        for widget in self.status_frame.winfo_children():
            widget.destroy()
        self.status_labels.clear()

        for ip, data in online_peers.items():
            name = data["name"]
            display = f"{name} ({ip})"
            self.peers_listbox.insert(tk.END, display)
            if ip in selected_ips:
                self.peers_listbox.selection_set(tk.END)

            label = tk.Label(self.status_frame, text=f"{ip}: Waiting", bg="#1e1e1e", fg="gray",
                             font=("Segoe UI", 10), anchor='w', justify='left')
            label.pack(fill='x', padx=10, pady=2)
            self.status_labels[ip] = label

    def update_peer_list_periodically(self):
        self.update_peer_list()
        self.master.after(3000, self.update_peer_list_periodically)

    def stop_transfers(self):
        for event in self.active_transfers.values():
            event.set()
        print("->> All transfers stopped.")

    def send_to_selected(self):
        if not self.file_path:
            messagebox.showerror("Error", "Please select a file first.")
            return
        selected_indices = self.peers_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("Error", "Please select at least one recipient.")
            return

        def update_progress(ip, percent, speed, eta):
            label = self.status_labels.get(ip)
            if label and label.winfo_exists():
                text = f"{ip}: ↑ {percent*100:.0f}% | {speed:.1f} MB/s | ETA: {eta:.0f}s"
                label.after(0, lambda l=label, t=text: l.config(text=t, fg="white"))

        for i in selected_indices:
            peer = self.peers_listbox.get(i)
            ip = peer.split('(')[-1].strip(')')
            stop_event = threading.Event()
            self.active_transfers[ip] = stop_event
            threading.Thread(
                target=send_file,
                args=(self.file_path, ip, update_progress, stop_event),
                daemon=True
            ).start()

# =================== RUN APP ===================
if __name__ == '__main__':
    threading.Thread(target=broadcast_presence, daemon=True).start()
    threading.Thread(target=listen_for_peers, daemon=True).start()
    threading.Thread(target=remove_stale_peers, daemon=True).start()
    start_receiver()

    root = tk.Tk()
    app = FileSenderApp(root)
    root.mainloop()
