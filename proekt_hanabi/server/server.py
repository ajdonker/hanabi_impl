import redis,os
import socket, threading, json
from game_logic.state import GameState
from game_logic.cards import Color
from redis.sentinel import Sentinel

HOST, PORT = '0.0.0.0', 12345
# refactored to use sentinel 
# REDIS_HOST = os.getenv("REDIS_HOST", "redis")
# REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

SENTINEL_NODES  = os.getenv("SENTINEL_NODES", "sentinel:26379").split(",")
SENTINEL_MASTER = os.getenv("SENTINEL_MASTER_NAME", "mymaster")

# Parse "host:port" list into tuples
sentinel_endpoints = []
for node in SENTINEL_NODES:
    host, port = node.split(":")
    sentinel_endpoints.append((host, int(port)))

# Connect via Sentinel
sent = Sentinel(sentinel_endpoints, socket_timeout=0.1)
def get_master_client():
    """
    Return a fresh Redis client pointing to the current master.
    """
    return sent.master_for(
        SENTINEL_MASTER,
        socket_timeout=0.1,
        decode_responses=True
    )
r = get_master_client()

print(f"[*] Connected to Redis master via Sentinel '{SENTINEL_MASTER}' at {sentinel_endpoints}")

LOBBY_SIZE = 2  # number of players required to start. >2, <= 5

clients = []      # list of (conn, addr, name)
lobby_names = []  # track names until game starts
game = None # global variable. A single server process handles only 1 game instance. 
lock = threading.Lock()

def broadcast_state():
    """Send current game state to all connected clients.
    When master changed, rediscover master client"""
    global r
    snap = game.serialize_state()
    snap_json = json.dumps(snap)
    msg  = json.dumps({"type":"STATE", **snap}) + "\n"
    state_key = f"hanabi:state:{game.game_id}"
    # persist for future reloads
    for attempt in range(2):
        try:
            r.set(state_key,snap_json)
            r.set("hanabi:state", msg.strip())
            break
        except (redis.exceptions.ReadOnlyError, redis.exceptions.ConnectionError) as e:
            # Master has been demoted, re-fetch the new one
            print("[WARN] Master changed, re-discovering via Sentinel:", e)
            
            r = get_master_client()
    else:
        print("[ERROR] Could not write to Redis master after retry")
    # send to all clients
    for conn, _, _ in clients:
        try:
            conn.sendall(msg.encode())
        except:
            pass

def handle_client(conn, addr):
    global game
    conn_file = conn.makefile('r')

    line = conn_file.readline()
    if not line:
        conn.close()
        return
    join   = json.loads(line)
    name   = join.get("player")
    old_id = join.get("game_id")

    with lock:
        if game is None:
            if name in lobby_names:
                err = json.dumps({"type":"ERROR","msg":"Name already taken"}) + "\n"
                conn.sendall(err.encode())
                return

            idx = len(lobby_names)
            lobby_names.append(name)
            clients.append((conn, addr, name))

            msg = json.dumps({"type":"ASSIGN_IDX","idx":idx}) + "\n"
            conn.sendall(msg.encode())

            if len(lobby_names) == LOBBY_SIZE:
                if old_id:
                    raw = r.get(f"hanabi:state:{old_id}")
                    if raw:
                        data = json.loads(raw)
                        game = GameState.from_serialized(data)
                    else:
                        game = GameState(lobby_names)
                else:
                    game = GameState(lobby_names)
                broadcast_state()

        else:
            err = json.dumps({"type":"ERROR","msg":"Game already in progress"}) + "\n"
            conn.sendall(err.encode())
            return

    while True:
        line = conn_file.readline()
        if not line:
            break
        msg = json.loads(line)
        with lock:
            try:
                if msg.get("type") == "PLAY":
                    game.play_card(msg["player_idx"], msg["card_idx"])
                elif msg.get("type") == "HINT":
                    if "color" in msg:
                        game.give_hint(msg["from"], msg["to"],color=Color[msg["color"]])
                    elif "number" in msg:
                        game.give_hint(msg["from"], msg["to"],number=msg["number"])
                elif msg.get("type") == "DISC":
                    game.discard(msg["player_idx"], msg["card_idx"])
                broadcast_state()
            except Exception as e:
                err = json.dumps({"type":"ERROR","msg":str(e)}) + "\n"
                conn.sendall(err.encode())
    with lock:
        clients[:] = [c for c in clients if c[0] != conn]
        conn_file.close()
        conn.close()


def main():
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        print(f"Server listening on {HOST}:{PORT}, waiting for {LOBBY_SIZE} players...")
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()