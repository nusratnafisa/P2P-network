import os
import socket
import threading
import uuid

from protocol import send_msg, recv_msg, recv_exact

CHUNK_SIZE = 64 * 1024          # send / receive files 64 KB at a time
DOWNLOAD_FOLDER = "downloads"   # received files are saved here


class P2PNode:

    # =====================================
    # SETUP
    # =====================================

    def __init__(self, name, port, show):
        self.name = name
        self.port = port
        self.peer_id = uuid.uuid4().hex[:8]   # short unique ID, e.g. "a83f21c4"
        self.show = show                      # function used to display text in the GUI
        self.peers = {}                       # peer_id -> {name, sock, address, lock}
        self.server = None
        self.running = False
        os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

    # =====================================
    # START SERVER
    # =====================================
    # socket -> bind -> listen, then wait for peers in the background

    def start(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("0.0.0.0", self.port))   # listen on all network interfaces
        self.server.listen()
        self.running = True

        threading.Thread(target=self.accept_loop, daemon=True).start()
        self.show(f"[SYSTEM] Peer started: {self.name} [{self.peer_id}] on port {self.port}")

    # =====================================
    # STOP SERVER
    # =====================================

    def stop(self):
        self.running = False
        if self.server:
            self.server.close()
        for peer_id in list(self.peers):
            self.remove_peer(peer_id)
        self.show("[SYSTEM] Peer stopped")

    # =====================================
    # ACCEPT CONNECTIONS
    # =====================================
    # Runs in its own thread. Every new connection gets a new thread.

    def accept_loop(self):
        while self.running:
            try:
                sock, address = self.server.accept()
            except OSError:
                break   # server socket was closed by stop()

            threading.Thread(target=self.handle_incoming,
                             args=(sock, address), daemon=True).start()

    # =====================================
    # HANDLE INCOMING CONNECTION (server side handshake)
    # =====================================
    # They send "hello" -> we reply "hello_ack"

    def handle_incoming(self, sock, address):
        try:
            hello = recv_msg(sock)
            send_msg(sock, self.make_hello("hello_ack"))
        except Exception as e:
            self.show(f"[ERROR] Handshake failed: {e}")
            sock.close()
            return

        if self.add_peer(hello, sock, address, outgoing=False):
            self.receive_loop(hello["peer_id"])

    # =====================================
    # CONNECT TO ANOTHER PEER (client side handshake)
    # =====================================
    # We send "hello" -> they reply "hello_ack"

    def connect(self, ip, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)   # give up after 5 seconds if there is no answer
        try:
            sock.connect((ip, port))
            send_msg(sock, self.make_hello("hello"))
            reply = recv_msg(sock)
        except Exception as e:
            sock.close()
            self.show(f"[ERROR] Connection failed: {e}")
            return
        sock.settimeout(None)  # no timeout while chatting

        if self.add_peer(reply, sock, (ip, port), outgoing=True):
            threading.Thread(target=self.receive_loop,
                             args=(reply["peer_id"],), daemon=True).start()

    # =====================================
    # HELLO MESSAGE
    # =====================================

    def make_hello(self, msg_type):
        return {
            "type": msg_type,          # "hello" or "hello_ack"
            "peer_id": self.peer_id,
            "peer_name": self.name,
            "port": self.port,
        }

    # =====================================
    # ADD PEER
    # =====================================
    # Returns False if the peer should not be added.

    def add_peer(self, info, sock, address, outgoing):
        # Do not connect to ourselves
        if info["peer_id"] == self.peer_id:
            sock.close()
            self.show("[ERROR] Cannot connect to yourself")
            return False

        # One connection per peer is enough (TCP works in both directions)
        if info["peer_id"] in self.peers:
            sock.close()
            self.show(f"[SYSTEM] Already connected to {info['peer_name']}")
            return False

        self.peers[info["peer_id"]] = {
            "name": info["peer_name"],
            "sock": sock,
            "address": address,
            "lock": threading.Lock(),   # stops two sends on one socket from mixing
        }

        if outgoing:
            ip, port = address
            self.show(f"[SYSTEM] Connected to {info['peer_name']} ({ip}:{port})")
        else:
            self.show(f"[SYSTEM] Connected to {info['peer_name']}")
        return True

    # =====================================
    # REMOVE PEER
    # =====================================

    def remove_peer(self, peer_id):
        peer = self.peers.pop(peer_id, None)
        if peer:
            peer["sock"].close()
            self.show(f"[SYSTEM] {peer['name']} disconnected")

    # =====================================
    # RECEIVE MESSAGES
    # =====================================
    # One thread per peer. Reads messages until the peer disconnects.

    def receive_loop(self, peer_id):
        peer = self.peers.get(peer_id)
        if peer is None:
            return
        sock = peer["sock"]

        try:
            while True:
                msg = recv_msg(sock)
                if msg["type"] == "text":
                    self.show(f"{msg['sender_name']} -> You: {msg['message']}")
                elif msg["type"] == "file":
                    self.receive_file(sock, msg)
        except Exception:
            pass   # connection closed or broken

        self.remove_peer(peer_id)

    # =====================================
    # RECEIVE FILE
    # =====================================
    # Read exactly 'filesize' bytes and save them in downloads/

    def receive_file(self, sock, msg):
        filename = os.path.basename(msg["filename"])   # keep only the name, no folders
        filesize = int(msg["filesize"])
        path = os.path.join(DOWNLOAD_FOLDER, filename)

        remaining = filesize
        with open(path, "wb") as f:
            while remaining > 0:
                chunk = recv_exact(sock, min(CHUNK_SIZE, remaining))
                f.write(chunk)
                remaining -= len(chunk)

        self.show(f"{msg['sender_name']} -> You: File received: {filename}",
                  status=f"Received: {path}")

    # =====================================
    # SEND TEXT
    # =====================================

    def send_text(self, peer_id, text):
        peer = self.peers.get(peer_id)
        if peer is None:
            self.show("[ERROR] Peer not found")
            return

        msg = {
            "type": "text",
            "sender_id": self.peer_id,
            "sender_name": self.name,
            "message": text,
        }
        try:
            with peer["lock"]:
                send_msg(peer["sock"], msg)
            self.show(f"You -> {peer['name']}: {text}")
        except Exception as e:
            self.show(f"[ERROR] Send failed: {e}")

    # =====================================
    # SEND FILE
    # =====================================
    # Step 1: metadata (name + size)   Step 2: raw bytes in chunks

    def send_file(self, peer_id, path):
        peer = self.peers.get(peer_id)
        if peer is None:
            self.show("[ERROR] Peer not found")
            return
        if not os.path.isfile(path):
            self.show("[ERROR] File does not exist")
            return

        filename = os.path.basename(path)
        filesize = os.path.getsize(path)
        msg = {
            "type": "file",
            "sender_id": self.peer_id,
            "sender_name": self.name,
            "filename": filename,
            "filesize": filesize,
        }
        try:
            with peer["lock"]:
                send_msg(peer["sock"], msg)              # step 1

                with open(path, "rb") as f:              # step 2
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        peer["sock"].sendall(chunk)

            self.show(f"You -> {peer['name']}: File sent: {filename}")
        except Exception as e:
            self.show(f"[ERROR] File send failed: {e}")