import json
import struct

# =====================================
# READ EXACT BYTES
# =====================================


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            # Empty bytes means the other peer closed the connection
            raise ConnectionError("Peer disconnected")
        data += chunk
    return data


# =====================================
# SEND MESSAGE
# =====================================


def send_msg(sock, message):
    payload = json.dumps(message).encode("utf-8")   
    header = struct.pack("!I", len(payload))        # length -> 4 bytes
    sock.sendall(header + payload)


# =====================================
# RECEIVE MESSAGE
# =====================================


def recv_msg(sock):
    header = recv_exact(sock, 4)          # step 1: read the length
    length = struct.unpack("!I", header)[0]
    payload = recv_exact(sock, length)              # step 2: read the JSON
    return json.loads(payload.decode("utf-8"))      