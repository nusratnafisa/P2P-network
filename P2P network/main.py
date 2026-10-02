import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from p2p_node import P2PNode


class App:

    # =====================================
    # SETUP
    # =====================================

    def __init__(self, root):
        self.root = root
        self.root.title("UAP P2P Network")
        self.root.geometry("950x650")

        self.node = None              # our P2PNode (created when "Start Peer" is pressed)
        self.events = queue.Queue()   # text coming from network threads waits here
        self.peer_ids = []            # peer IDs in the same order as the peer list

        self.build_layout()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.check_events()

    # =====================================
    # BUILD GUI
    # =====================================

    def build_layout(self):

        # ---------- MY PEER ----------
        top = tk.LabelFrame(self.root, text="My Peer")
        top.pack(fill="x", padx=8, pady=4)

        row = tk.Frame(top)
        row.pack(fill="x", padx=4, pady=2)

        tk.Label(row, text="Name:").pack(side="left")
        self.name_entry = tk.Entry(row, width=15)
        self.name_entry.pack(side="left", padx=4)

        tk.Label(row, text="Port:").pack(side="left")
        self.port_entry = tk.Entry(row, width=8)
        self.port_entry.pack(side="left", padx=4)

        self.start_btn = tk.Button(row, text="Start Peer", command=self.start_peer)
        self.start_btn.pack(side="left", padx=4)

        self.stop_btn = tk.Button(row, text="Stop", command=self.stop_peer, state="disabled")
        self.stop_btn.pack(side="left", padx=4)

        self.info_label = tk.Label(top, text="Not started", anchor="w")
        self.info_label.pack(fill="x", padx=4, pady=(0, 4))

        # ---------- CONNECT TO ANOTHER PEER ----------
        conn = tk.LabelFrame(self.root, text="Connect to Another Peer")
        conn.pack(fill="x", padx=8, pady=4)

        tk.Label(conn, text="IP:").pack(side="left", padx=(4, 0), pady=4)
        self.ip_entry = tk.Entry(conn, width=15)
        self.ip_entry.insert(0, "127.0.0.1")
        self.ip_entry.pack(side="left", padx=4)

        tk.Label(conn, text="Port:").pack(side="left")
        self.remote_port_entry = tk.Entry(conn, width=8)
        self.remote_port_entry.pack(side="left", padx=4)

        tk.Button(conn, text="Connect", command=self.connect_peer).pack(side="left", padx=4)

        # ---------- CONNECTED PEERS + MESSAGES / EVENTS ----------
        middle = tk.Frame(self.root)
        middle.pack(fill="both", expand=True, padx=8, pady=4)

        left = tk.LabelFrame(middle, text="Connected Peers")
        left.pack(side="left", fill="y")
        self.peer_list = tk.Listbox(left, width=35, exportselection=False)
        self.peer_list.pack(fill="both", expand=True)

        right = tk.LabelFrame(middle, text="Messages / Events")
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.log_box = tk.Text(right, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True)

        # ---------- SEND TEXT ----------
        text_frame = tk.LabelFrame(self.root, text="Send Text")
        text_frame.pack(fill="x", padx=8, pady=4)

        self.msg_entry = tk.Entry(text_frame)
        self.msg_entry.pack(side="left", fill="x", expand=True, padx=4, pady=4)
        self.msg_entry.bind("<Return>", lambda event: self.send_text())   # Enter key = Send

        tk.Button(text_frame, text="Send", width=8, command=self.send_text).pack(side="right", padx=4)

        # ---------- SEND FILE ----------
        file_frame = tk.LabelFrame(self.root, text="Send File")
        file_frame.pack(fill="x", padx=8, pady=4)

        tk.Label(file_frame, text="Text, image, audio, video, PDF, ZIP, etc.").pack(side="left", padx=4, pady=4)
        tk.Button(file_frame, text="Choose File & Send", command=self.send_file).pack(side="right", padx=4)

        # ---------- STATUS BAR ----------
        self.status_label = tk.Label(self.root, text="Ready", anchor="w", relief="sunken", bd=1)
        self.status_label.pack(fill="x", side="bottom")

    # =====================================
    # EVENT / LOG
    # =====================================
   

    def show(self, text, status=None):
        if status is None:
            status = text.replace("[SYSTEM] ", "")   # status bar text
        self.events.put((text, status))

    def check_events(self):
        while not self.events.empty():
            text, status = self.events.get()
            self.log_box.config(state="normal")
            self.log_box.insert("end", text + "\n")
            self.log_box.see("end")                 # scroll to the newest line
            self.log_box.config(state="disabled")
            self.status_label.config(text=status)

        self.refresh_peers()
        self.root.after(200, self.check_events)     # run again after 200 ms

    # =====================================
    # UPDATE PEER LIST
    # =====================================

    def refresh_peers(self):
        peers = dict(self.node.peers) if self.node else {}
        ids = list(peers)
        if ids == self.peer_ids:
            return   # nothing changed

        self.peer_ids = ids
        self.peer_list.delete(0, "end")
        for pid in ids:
            ip, port = peers[pid]["address"]
            self.peer_list.insert("end", f"{peers[pid]['name']} [{pid}]  {ip}:{port}")

    # =====================================
    # CHECK PORT INPUT
    # =====================================

    def read_port(self, entry):
        text = entry.get().strip()
        if not text.isdigit() or not (1024 <= int(text) <= 65535):
            messagebox.showerror("Invalid port", "Port must be a number between 1024 and 65535")
            return None
        return int(text)

    # =====================================
    # GET SELECTED PEER
    # =====================================

    def selected_peer(self):
        if self.node is None:
            messagebox.showwarning("Not started", "Start your peer first")
            return None
        selection = self.peer_list.curselection()
        if not selection:
            messagebox.showwarning("No peer", "Please select a peer from the list")
            return None
        return self.peer_ids[selection[0]]

    # =====================================
    # START PEER BUTTON
    # =====================================

    def start_peer(self):
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showerror("Missing name", "Please enter a peer name")
            return
        port = self.read_port(self.port_entry)
        if port is None:
            return

        try:
            self.node = P2PNode(name, port, self.show)
            self.node.start()
        except OSError as e:
            # e.g. the port is already used by another program
            self.node = None
            messagebox.showerror("Error", f"Could not start peer: {e}")
            return

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.info_label.config(text=f"{name} | ID: {self.node.peer_id} | Port: {port}")

    # =====================================
    # STOP PEER BUTTON
    # =====================================

    def stop_peer(self):
        if self.node:
            self.node.stop()
            self.node = None
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.info_label.config(text="Not started")

    # =====================================
    # CONNECT BUTTON
    # =====================================

    def connect_peer(self):
        if self.node is None:
            messagebox.showwarning("Not started", "Start your peer first")
            return
        ip = self.ip_entry.get().strip()
        port = self.read_port(self.remote_port_entry)
        if port is None:
            return

        # Run in a thread so the window does not freeze while connecting
        threading.Thread(target=self.node.connect, args=(ip, port), daemon=True).start()

    # =====================================
    # SEND TEXT BUTTON
    # =====================================

    def send_text(self):
        peer_id = self.selected_peer()
        if peer_id is None:
            return
        text = self.msg_entry.get().strip()
        if not text:
            return

        threading.Thread(target=self.node.send_text, args=(peer_id, text), daemon=True).start()
        self.msg_entry.delete(0, "end")

    # =====================================
    # SEND FILE BUTTON
    # =====================================

    def send_file(self):
        peer_id = self.selected_peer()
        if peer_id is None:
            return
        path = filedialog.askopenfilename(title="Choose a file to send")
        if not path:
            return   # user pressed Cancel

        # Big files take time, so send in a thread to keep the window responsive
        threading.Thread(target=self.node.send_file, args=(peer_id, path), daemon=True).start()

    # =====================================
    # CLOSE WINDOW
    # =====================================

    def on_close(self):
        if self.node:
            self.node.stop()
        self.root.destroy()


# =====================================
# RUN PROGRAM
# =====================================

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()