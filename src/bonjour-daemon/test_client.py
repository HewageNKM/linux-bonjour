import socket
import json
import os

socket_path = "/tmp/linux-bonjour.sock"

def test_verify():
    if not os.path.exists(socket_path):
        print(f"❌ Socket {socket_path} not found!")
        return

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(socket_path)
        
        # Send ENROLL command
        request = {"cmd": "ENROLL", "user": "kawishika_test"}
        client.sendall((json.dumps(request) + "\n").encode())
        
        # Listen for responses
        while True:
            data = client.recv(1024)
            if not data:
                break
            
            # Line-delimited JSON
            for line in data.decode().splitlines():
                if not line.strip(): continue
                res = json.loads(line)
                print(f"📥 Received: {res}")
                
                # Exit on final status
                if res.get("status") in ["SUCCESS", "FAILURE"]:
                    return

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    test_verify()
